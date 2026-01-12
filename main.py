import random
import urllib.parse
import httpx
import obd
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from schemas import DTCCode, OBDSnapshot
from ollama_client import ask_ollama, check_ollama
from database import init_db, log_scan, get_recent_scans
from obd_reader import get_reader, connect_obd
from vehicle_data import get_available_trims, get_vehicle_by_id, get_vehicle_image, format_vehicle_string, format_vehicle_context, decode_obd_codes_batch
from code_scraper import get_code_info, format_code_context
from forum_scraper import scrape_reddit_fallback, format_reddit_context

app = FastAPI(title="ClearDrive", version="0.7.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()


# =============================================================================
# SAFETY RATING DEFINITIONS
# =============================================================================

SAFETY_DEFINITIONS = {
    "SAFE": {
        "meaning": "Low Urgency - Safe to Drive",
        "description": "This issue is minor and won't damage your vehicle. You can continue driving normally while scheduling a repair at your convenience.",
        "action": "Schedule service when convenient",
        "icon": "🟢"
    },
    "CAUTION": {
        "meaning": "Medium Urgency - Schedule Service Soon",
        "description": "This issue needs attention within the next 1-2 weeks. Your vehicle is safe for short trips, but the problem will get worse or more expensive if ignored.",
        "action": "Schedule service within 1-2 weeks",
        "icon": "🟡"
    },
    "STOP": {
        "meaning": "High Urgency - Immediate Attention Required",
        "description": "Continuing to drive could cause permanent damage to your engine, transmission, or other major components. This could turn a $500 repair into a $5,000+ repair.",
        "action": "Go to a mechanic immediately or have vehicle towed",
        "icon": "🔴"
    }
}


class TrimRequest(BaseModel):
    year: str
    make: str
    model: str


class InterpretRequest(BaseModel):
    vehicle_id: str
    trim: Optional[str] = ""
    use_live_obd: Optional[bool] = False


class FollowUpRequest(BaseModel):
    question: str
    context: dict
    history: List[dict] = []


def parse_guidance(response: str) -> dict:
    """Parse the SLM response into sections."""
    sections = {
        "safety_level": "CAUTION",
        "dont_panic": "",
        "likely_causes": "",
        "symptoms": "",
        "if_ignored": "",
        "quick_checks": "",
        "diy_fix": "",
        "urgency": "",
        "repair_cost": "",
        "known_issues": "",  # trim-specific issues from database
        "owner_reports": ""
    }
    
    lines = response.strip().split('\n')
    current_section = None
    current_text = []
    
    section_map = {
        "SAFETY LEVEL": "safety_level",
        "DON'T PANIC": "dont_panic",
        "WHAT'S HAPPENING": "dont_panic",
        "LIKELY CAUSES": "likely_causes",
        "WHAT YOU MIGHT NOTICE": "symptoms",
        "IF YOU IGNORE": "if_ignored",
        "QUICK CHECKS": "quick_checks",
        "DIY FIX": "diy_fix",
        "DIY REPAIR": "diy_fix",
        "MECHANIC URGENCY": "urgency",
        "WHEN TO SEE": "urgency",
        "REPAIR COST": "repair_cost",
        "ESTIMATED COST": "repair_cost",
        "KNOWN ISSUES": "known_issues",
        "DATABASE": "known_issues",
        "OTHER OWNERS": "owner_reports",
        "COMMUNITY": "owner_reports"
    }
    
    for line in lines:
        line_upper = line.upper().strip()
        
        matched = False
        for header, key in section_map.items():
            if header in line_upper:
                if current_section and current_text:
                    if current_section == "safety_level":
                        val = ' '.join(current_text).strip().upper()
                        if "STOP" in val:
                            sections[current_section] = "STOP"
                        elif "CAUTION" in val:
                            sections[current_section] = "CAUTION"
                        else:
                            sections[current_section] = "SAFE"
                    else:
                        sections[current_section] = '\n'.join(current_text).strip()
                
                current_section = key
                current_text = []
                
                after_colon = line.split(':', 1)
                if len(after_colon) > 1 and after_colon[1].strip():
                    current_text.append(after_colon[1].strip())
                
                matched = True
                break
        
        if not matched and current_section:
            if line.strip():
                current_text.append(line.strip())
    
    if current_section and current_text:
        if current_section == "safety_level":
            val = ' '.join(current_text).strip().upper()
            if "STOP" in val:
                sections[current_section] = "STOP"
            elif "CAUTION" in val:
                sections[current_section] = "CAUTION"
            else:
                sections[current_section] = "SAFE"
        else:
            sections[current_section] = '\n'.join(current_text).strip()
    
    return sections


def get_mock_snapshot() -> OBDSnapshot:
    """Generate mock OBD data for testing."""
    mock_scenarios = [
        # No codes
        [],
        # Catalyst/Emissions
        [DTCCode(code="P0420", description="Catalyst Efficiency Below Threshold")],
        [DTCCode(code="P0430", description="Catalyst Efficiency Below Threshold Bank 2")],
        [DTCCode(code="P0421", description="Warm Up Catalyst Efficiency Below Threshold")],
        # Misfires
        [DTCCode(code="P0300", description="Random Misfire Detected"),
         DTCCode(code="P0301", description="Cylinder 1 Misfire")],
        [DTCCode(code="P0302", description="Cylinder 2 Misfire"),
         DTCCode(code="P0303", description="Cylinder 3 Misfire")],
        [DTCCode(code="P0304", description="Cylinder 4 Misfire")],
        [DTCCode(code="P0305", description="Cylinder 5 Misfire"),
         DTCCode(code="P0306", description="Cylinder 6 Misfire")],
        [DTCCode(code="P0307", description="Cylinder 7 Misfire"),
         DTCCode(code="P0308", description="Cylinder 8 Misfire")],
        # Fuel System
        [DTCCode(code="P0171", description="System Too Lean Bank 1")],
        [DTCCode(code="P0172", description="System Too Rich Bank 1")],
        [DTCCode(code="P0174", description="System Too Lean Bank 2")],
        [DTCCode(code="P0175", description="System Too Rich Bank 2")],
        [DTCCode(code="P0087", description="Fuel Rail Pressure Too Low")],
        [DTCCode(code="P0088", description="Fuel Rail Pressure Too High")],
        [DTCCode(code="P0190", description="Fuel Rail Pressure Sensor Circuit")],
        [DTCCode(code="P0201", description="Injector Circuit Open Cylinder 1")],
        [DTCCode(code="P0216", description="Injection Timing Control Circuit")],
        # EVAP System
        [DTCCode(code="P0455", description="EVAP System Large Leak")],
        [DTCCode(code="P0442", description="EVAP System Small Leak")],
        [DTCCode(code="P0440", description="EVAP System Malfunction")],
        [DTCCode(code="P0446", description="EVAP Vent Control Circuit")],
        [DTCCode(code="P0456", description="EVAP System Very Small Leak")],
        [DTCCode(code="P0449", description="EVAP Vent Valve/Solenoid Circuit")],
        # Cooling System
        [DTCCode(code="P0128", description="Coolant Thermostat Below Temp")],
        [DTCCode(code="P0115", description="Engine Coolant Temp Circuit")],
        [DTCCode(code="P0116", description="Engine Coolant Temp Range/Performance")],
        [DTCCode(code="P0117", description="Engine Coolant Temp Circuit Low")],
        [DTCCode(code="P0118", description="Engine Coolant Temp Circuit High")],
        [DTCCode(code="P0125", description="Insufficient Coolant Temp for Fuel Control")],
        # Oxygen Sensors
        [DTCCode(code="P0130", description="O2 Sensor Circuit Bank 1 Sensor 1")],
        [DTCCode(code="P0131", description="O2 Sensor Low Voltage Bank 1 Sensor 1")],
        [DTCCode(code="P0132", description="O2 Sensor High Voltage Bank 1 Sensor 1")],
        [DTCCode(code="P0133", description="O2 Sensor Slow Response Bank 1 Sensor 1")],
        [DTCCode(code="P0134", description="O2 Sensor No Activity Bank 1 Sensor 1")],
        [DTCCode(code="P0135", description="O2 Sensor Heater Circuit Bank 1 Sensor 1")],
        [DTCCode(code="P0136", description="O2 Sensor Circuit Bank 1 Sensor 2")],
        [DTCCode(code="P0141", description="O2 Sensor Heater Circuit Bank 1 Sensor 2")],
        [DTCCode(code="P0150", description="O2 Sensor Circuit Bank 2 Sensor 1")],
        [DTCCode(code="P0155", description="O2 Sensor Heater Circuit Bank 2 Sensor 1")],
        # MAF/MAP Sensors
        [DTCCode(code="P0100", description="MAF Sensor Circuit")],
        [DTCCode(code="P0101", description="MAF Sensor Range/Performance")],
        [DTCCode(code="P0102", description="MAF Sensor Circuit Low")],
        [DTCCode(code="P0103", description="MAF Sensor Circuit High")],
        [DTCCode(code="P0105", description="MAP Sensor Circuit")],
        [DTCCode(code="P0106", description="MAP Sensor Range/Performance")],
        [DTCCode(code="P0107", description="MAP Sensor Circuit Low")],
        [DTCCode(code="P0108", description="MAP Sensor Circuit High")],
        # Throttle/Idle
        [DTCCode(code="P0507", description="Idle Air Control RPM Higher Than Expected")],
        [DTCCode(code="P0506", description="Idle Air Control RPM Lower Than Expected")],
        [DTCCode(code="P0505", description="Idle Air Control System")],
        [DTCCode(code="P0120", description="Throttle Position Sensor Circuit")],
        [DTCCode(code="P0121", description="Throttle Position Sensor Range/Performance")],
        [DTCCode(code="P0122", description="Throttle Position Sensor Circuit Low")],
        [DTCCode(code="P0123", description="Throttle Position Sensor Circuit High")],
        [DTCCode(code="P2135", description="Throttle Position Sensor Correlation")],
        # EGR System
        [DTCCode(code="P0401", description="EGR Flow Insufficient")],
        [DTCCode(code="P0402", description="EGR Flow Excessive")],
        [DTCCode(code="P0400", description="EGR System Flow")],
        [DTCCode(code="P0403", description="EGR Control Circuit")],
        [DTCCode(code="P0404", description="EGR Control Circuit Range/Performance")],
        # Ignition System
        [DTCCode(code="P0351", description="Ignition Coil A Primary Circuit")],
        [DTCCode(code="P0352", description="Ignition Coil B Primary Circuit")],
        [DTCCode(code="P0353", description="Ignition Coil C Primary Circuit")],
        [DTCCode(code="P0354", description="Ignition Coil D Primary Circuit")],
        [DTCCode(code="P0355", description="Ignition Coil E Primary Circuit")],
        [DTCCode(code="P0356", description="Ignition Coil F Primary Circuit")],
        [DTCCode(code="P0357", description="Ignition Coil G Primary Circuit")],
        [DTCCode(code="P0358", description="Ignition Coil H Primary Circuit")],
        # Crankshaft/Camshaft
        [DTCCode(code="P0335", description="Crankshaft Position Sensor Circuit")],
        [DTCCode(code="P0336", description="Crankshaft Position Sensor Range/Performance")],
        [DTCCode(code="P0340", description="Camshaft Position Sensor Circuit")],
        [DTCCode(code="P0341", description="Camshaft Position Sensor Range/Performance")],
        [DTCCode(code="P0345", description="Camshaft Position Sensor Circuit Bank 2")],
        # VVT/Timing
        [DTCCode(code="P0010", description="Intake Camshaft Position Actuator Circuit")],
        [DTCCode(code="P0011", description="Intake Camshaft Position Timing Over-Advanced")],
        [DTCCode(code="P0012", description="Intake Camshaft Position Timing Over-Retarded")],
        [DTCCode(code="P0013", description="Exhaust Camshaft Position Actuator Circuit")],
        [DTCCode(code="P0014", description="Exhaust Camshaft Position Timing Over-Advanced")],
        # Knock Sensor
        [DTCCode(code="P0325", description="Knock Sensor 1 Circuit")],
        [DTCCode(code="P0327", description="Knock Sensor 1 Circuit Low")],
        [DTCCode(code="P0328", description="Knock Sensor 1 Circuit High")],
        [DTCCode(code="P0330", description="Knock Sensor 2 Circuit")],
        # Transmission
        [DTCCode(code="P0700", description="Transmission Control System")],
        [DTCCode(code="P0715", description="Input/Turbine Speed Sensor Circuit")],
        [DTCCode(code="P0720", description="Output Speed Sensor Circuit")],
        [DTCCode(code="P0730", description="Incorrect Gear Ratio")],
        [DTCCode(code="P0740", description="Torque Converter Clutch Circuit")],
        [DTCCode(code="P0750", description="Shift Solenoid A")],
        [DTCCode(code="P0755", description="Shift Solenoid B")],
        [DTCCode(code="P0760", description="Shift Solenoid C")],
        [DTCCode(code="P0765", description="Shift Solenoid D")],
        # SERIOUS - Stop driving
        [DTCCode(code="P0217", description="Engine Overheating Condition")],
        [DTCCode(code="P0218", description="Transmission Fluid Overheating")],
        [DTCCode(code="P0520", description="Engine Oil Pressure Sensor Circuit")],
        [DTCCode(code="P0521", description="Engine Oil Pressure Range/Performance")],
        [DTCCode(code="P0522", description="Engine Oil Pressure Sensor Low")],
        [DTCCode(code="P0523", description="Engine Oil Pressure Sensor High")],
        [DTCCode(code="P0524", description="Engine Oil Pressure Too Low")],
        # Multiple codes scenarios
        [DTCCode(code="P0171", description="System Too Lean Bank 1"),
         DTCCode(code="P0174", description="System Too Lean Bank 2")],
        [DTCCode(code="P0300", description="Random Misfire"),
         DTCCode(code="P0420", description="Catalyst Efficiency Below Threshold")],
        [DTCCode(code="P0172", description="System Too Rich Bank 1"),
         DTCCode(code="P0175", description="System Too Rich Bank 2")],
        [DTCCode(code="P0135", description="O2 Heater Circuit Bank 1"),
         DTCCode(code="P0141", description="O2 Heater Circuit Bank 1 Sensor 2")],
        [DTCCode(code="P0011", description="Camshaft Timing Over-Advanced"),
         DTCCode(code="P0014", description="Exhaust Cam Timing Over-Advanced"),
         DTCCode(code="P0300", description="Random Misfire")],
    ]
    
    return OBDSnapshot(
        timestamp=datetime.now(),
        dtc_codes=random.choice(mock_scenarios),
        rpm=round(random.uniform(650, 850), 0),
        speed_mph=0.0,
        coolant_temp_f=round(random.uniform(185, 220), 1),
        is_mock=True,
    )


def build_engine_profile(vehicle_data: dict) -> dict:
    """
    Build a detailed engine profile for diagnostic context.
    All logic is based on engine characteristics - NO hardcoded vehicle names.
    """
    if not vehicle_data:
        return {}
    
    profile = {
        "displacement": 0,
        "cylinders": 0,
        "is_supercharged": False,
        "is_turbocharged": False,
        "is_naturally_aspirated": True,
        "is_hybrid": False,
        "is_electric": False,
        "performance_tier": "standard",  # standard, sport, high-performance
        "engine_layout": "",  # V6, V8, I4, etc.
        "maintenance_factors": [],
        "cost_multiplier": 1.0,  # Parts/labor cost multiplier
    }
    
    # Extract values
    try:
        profile["displacement"] = float(vehicle_data.get("displacement", 0) or 0)
    except:
        profile["displacement"] = 0
    
    try:
        profile["cylinders"] = int(vehicle_data.get("cylinders", 0) or 0)
    except:
        profile["cylinders"] = 0
    
    profile["is_supercharged"] = vehicle_data.get("supercharged", False)
    profile["is_turbocharged"] = vehicle_data.get("turbocharged", False)
    profile["is_naturally_aspirated"] = not (profile["is_supercharged"] or profile["is_turbocharged"])
    
    fuel_type = vehicle_data.get("fuel_type", "").lower()
    profile["is_hybrid"] = "hybrid" in fuel_type or bool(vehicle_data.get("ev_motor"))
    profile["is_electric"] = "electric" in fuel_type and "hybrid" not in fuel_type
    
    # Determine engine layout
    cyl = profile["cylinders"]
    if cyl == 4:
        profile["engine_layout"] = "inline-4"
    elif cyl == 6:
        profile["engine_layout"] = "V6"
    elif cyl == 8:
        profile["engine_layout"] = "V8"
    elif cyl == 10:
        profile["engine_layout"] = "V10"
    elif cyl == 12:
        profile["engine_layout"] = "V12"
    elif cyl == 3:
        profile["engine_layout"] = "3-cylinder"
    elif profile["is_electric"]:
        profile["engine_layout"] = "electric motor"
    
    # Determine performance tier and cost multiplier based on engine characteristics
    disp = profile["displacement"]
    
    if profile["is_supercharged"]:
        profile["performance_tier"] = "high-performance"
        profile["cost_multiplier"] = 1.8
        profile["maintenance_factors"].append("Supercharger system requires belt inspection and intercooler maintenance")
        profile["maintenance_factors"].append("Higher fuel octane requirements (premium or higher)")
        profile["maintenance_factors"].append("More frequent oil changes due to higher engine stress")
        profile["maintenance_factors"].append("Specialized parts that may require dealer or performance shop")
    elif profile["is_turbocharged"]:
        if disp >= 3.0:
            profile["performance_tier"] = "high-performance"
            profile["cost_multiplier"] = 1.5
        else:
            profile["performance_tier"] = "sport"
            profile["cost_multiplier"] = 1.2
        profile["maintenance_factors"].append("Turbocharger requires proper warm-up and cool-down")
        profile["maintenance_factors"].append("Intercooler and boost pipes need periodic inspection")
        profile["maintenance_factors"].append("Use recommended fuel octane to prevent knock")
    elif cyl >= 8 and disp >= 5.0:
        profile["performance_tier"] = "sport"
        profile["cost_multiplier"] = 1.4
        profile["maintenance_factors"].append("Large displacement engine uses more oil - check frequently")
        profile["maintenance_factors"].append("More spark plugs to replace (8+)")
        profile["maintenance_factors"].append("Higher capacity cooling system")
    elif cyl >= 8:
        profile["performance_tier"] = "sport"
        profile["cost_multiplier"] = 1.3
        profile["maintenance_factors"].append("V8 engines have more ignition components")
    elif cyl == 6 and disp >= 3.5:
        profile["performance_tier"] = "sport"
        profile["cost_multiplier"] = 1.15
    else:
        profile["performance_tier"] = "standard"
        profile["cost_multiplier"] = 1.0
    
    if profile["is_hybrid"]:
        profile["maintenance_factors"].append("Hybrid battery health affects overall performance")
        profile["maintenance_factors"].append("Regenerative braking system")
        profile["cost_multiplier"] *= 1.1
    
    if profile["is_electric"]:
        profile["performance_tier"] = "electric"
        profile["cost_multiplier"] = 1.3
        profile["maintenance_factors"] = [
            "No traditional engine maintenance needed",
            "Battery health and thermal management are critical",
            "Electric motor and inverter require specialized diagnostics",
            "Regenerative braking reduces brake wear"
        ]
    
    return profile


def build_comprehensive_vehicle_context(vehicle_data: dict, trim: str = "") -> str:
    """
    Build extremely detailed vehicle context for the AI.
    This helps the AI give trim-specific, engine-specific advice.
    """
    if not vehicle_data:
        return "Vehicle information not available."
    
    profile = build_engine_profile(vehicle_data)
    
    lines = []
    
    # Basic identity
    year = vehicle_data.get("year", "")
    make = vehicle_data.get("make", "")
    model = vehicle_data.get("model", "")
    
    vehicle_name = f"{year} {make} {model}"
    if trim:
        vehicle_name += f" {trim}"
    
    lines.append(f"VEHICLE: {vehicle_name}")
    lines.append("")
    
    # Engine details
    lines.append("ENGINE SPECIFICATIONS:")
    
    engine_str = vehicle_data.get("engine", "")
    if engine_str:
        lines.append(f"  Engine: {engine_str}")
    
    if profile["displacement"]:
        lines.append(f"  Displacement: {profile['displacement']}L")
    
    if profile["cylinders"]:
        lines.append(f"  Cylinders: {profile['cylinders']} ({profile['engine_layout']})")
    
    # Aspiration - this dramatically affects diagnostics
    if profile["is_supercharged"]:
        lines.append(f"  Aspiration: SUPERCHARGED (forced induction)")
        lines.append(f"    - This engine has a belt-driven supercharger that forces air into the engine")
        lines.append(f"    - Produces significantly more power than naturally aspirated versions")
        lines.append(f"    - Has intercooler system to cool compressed air")
        lines.append(f"    - Requires premium fuel and more frequent maintenance")
        lines.append(f"    - Parts and labor costs are HIGHER than standard engines")
    elif profile["is_turbocharged"]:
        lines.append(f"  Aspiration: TURBOCHARGED (forced induction)")
        lines.append(f"    - This engine has exhaust-driven turbocharger(s)")
        lines.append(f"    - More efficient power delivery than superchargers")
        lines.append(f"    - Has intercooler and boost control systems")
        lines.append(f"    - May require premium fuel")
    else:
        lines.append(f"  Aspiration: Naturally Aspirated")
        lines.append(f"    - Standard atmospheric breathing - no forced induction")
        lines.append(f"    - Generally simpler and less expensive to maintain")
    
    lines.append("")
    
    # Performance tier
    lines.append("PERFORMANCE CLASSIFICATION:")
    if profile["performance_tier"] == "high-performance":
        lines.append(f"  Tier: HIGH-PERFORMANCE")
        lines.append(f"  - This is a high-output engine designed for maximum power")
        lines.append(f"  - Expect 50-100% higher parts costs than base models")
        lines.append(f"  - May require specialist mechanics or dealers for some repairs")
        lines.append(f"  - Uses performance-grade components throughout")
    elif profile["performance_tier"] == "sport":
        lines.append(f"  Tier: SPORT/PERFORMANCE")
        lines.append(f"  - This is an upgraded powertrain with more power than base")
        lines.append(f"  - Expect 20-50% higher parts costs than base models")
        lines.append(f"  - Most independent shops can service this engine")
    elif profile["performance_tier"] == "electric":
        lines.append(f"  Tier: ELECTRIC VEHICLE")
        lines.append(f"  - No internal combustion engine")
        lines.append(f"  - Different maintenance profile than traditional vehicles")
        lines.append(f"  - Requires EV-certified technicians for many repairs")
    else:
        lines.append(f"  Tier: STANDARD")
        lines.append(f"  - Base-level powertrain with standard components")
        lines.append(f"  - Parts are widely available and reasonably priced")
        lines.append(f"  - Any qualified mechanic can service this engine")

    # Note: cost_multiplier is used internally for cost estimation guidance
    # but is NOT shown to the user - keep it as internal logic only
    lines.append("")

    # Drivetrain
    drive = vehicle_data.get("drive", "")
    if drive:
        lines.append("DRIVETRAIN:")
        lines.append(f"  Configuration: {drive}")
        
        drive_lower = drive.lower()
        if "front" in drive_lower or "fwd" in drive_lower:
            lines.append(f"  - Front-Wheel Drive: Power goes to front wheels only")
            lines.append(f"  - Transaxle combines transmission and differential")
            lines.append(f"  - CV axles connect transaxle to front wheels")
        elif "rear" in drive_lower or "rwd" in drive_lower:
            lines.append(f"  - Rear-Wheel Drive: Power goes to rear wheels only")
            lines.append(f"  - Has driveshaft running to rear differential")
            lines.append(f"  - Separate transmission and differential units")
        elif "all" in drive_lower or "awd" in drive_lower:
            lines.append(f"  - All-Wheel Drive: Power goes to all four wheels")
            lines.append(f"  - Has transfer case and multiple differentials")
            lines.append(f"  - More complex drivetrain = higher maintenance costs")
            lines.append(f"  - Extra fluids to change (transfer case, front/rear diff)")
        elif "4" in drive_lower or "4wd" in drive_lower:
            lines.append(f"  - Four-Wheel Drive: Selectable 4WD system")
            lines.append(f"  - Has transfer case with 2WD/4WD modes")
            lines.append(f"  - May have low-range gearing for off-road")
        lines.append("")
    
    # Transmission
    transmission = vehicle_data.get("transmission", "")
    if transmission:
        lines.append("TRANSMISSION:")
        lines.append(f"  Type: {transmission}")
        trans_lower = transmission.lower()
        if "auto" in trans_lower:
            lines.append(f"  - Automatic transmission with torque converter")
        elif "manual" in trans_lower:
            lines.append(f"  - Manual transmission with clutch")
        elif "cvt" in trans_lower:
            lines.append(f"  - Continuously Variable Transmission (belt-driven)")
        elif "dct" in trans_lower or "dual" in trans_lower:
            lines.append(f"  - Dual-Clutch Transmission (automated manual)")
        lines.append("")
    
    # Fuel
    fuel_type = vehicle_data.get("fuel_type", "")
    if fuel_type:
        lines.append("FUEL SYSTEM:")
        lines.append(f"  Fuel Type: {fuel_type}")
        if profile["is_supercharged"] or (profile["is_turbocharged"] and profile["displacement"] >= 2.5):
            lines.append(f"  Recommendation: Premium fuel (91+ octane) likely required")
        lines.append("")
    
    # Maintenance factors
    if profile["maintenance_factors"]:
        lines.append("MAINTENANCE CONSIDERATIONS FOR THIS SPECIFIC CONFIGURATION:")
        for factor in profile["maintenance_factors"]:
            lines.append(f"  - {factor}")
        lines.append("")
    
    return "\n".join(lines)


@app.get("/", response_class=HTMLResponse)
async def home():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/manifest.json")
async def manifest():
    return FileResponse("manifest.json", media_type="application/manifest+json")


@app.get("/sw.js")
async def service_worker():
    return FileResponse("sw.js", media_type="application/javascript")


@app.get("/icons/{icon_name}")
async def icons(icon_name: str):
    return FileResponse(f"icons/{icon_name}", media_type="image/png")


@app.get("/health")
async def health():
    ollama_status = await check_ollama()
    return {"status": "ok", "ollama": ollama_status}


@app.get("/obd/ports")
async def obd_ports():
    """List available COM ports for OBD adapter."""
    try:
        import serial.tools.list_ports
        ports = list(serial.tools.list_ports.comports())
        return {
            "ports": [
                {
                    "device": p.device,
                    "description": p.description,
                    "hwid": p.hwid
                }
                for p in ports
            ]
        }
    except ImportError:
        return {"ports": [], "error": "pyserial not installed"}
    except Exception as e:
        return {"ports": [], "error": str(e)}


class OBDConnectRequest(BaseModel):
    port: Optional[str] = None  # COM port like "COM3", None for auto-detect


@app.post("/obd/connect")
async def obd_connect(request: OBDConnectRequest):
    """Connect to OBD adapter on specified port."""
    reader = get_reader()

    # Disconnect first if already connected
    if reader.is_connected():
        reader.disconnect()

    # Set port if specified
    if request.port:
        reader.port = request.port
        print(f"[OBD] Attempting connection on {request.port}...")
    else:
        reader.port = None
        print("[OBD] Attempting auto-detect...")

    success = reader.connect()

    if success:
        return {
            "connected": True,
            "port": reader.connection.port_name() if reader.connection else request.port,
            "message": f"Connected to {reader.connection.port_name()}" if reader.connection else "Connected"
        }
    else:
        return {
            "connected": False,
            "port": request.port,
            "message": f"Failed to connect{' to ' + request.port if request.port else ' (auto-detect failed)'}"
        }


@app.get("/obd/status")
async def obd_status():
    """Check if OBD adapter is connected."""
    reader = get_reader()

    # Get available ports for UI
    available_ports = []
    try:
        import serial.tools.list_ports
        ports = list(serial.tools.list_ports.comports())
        available_ports = [{"device": p.device, "description": p.description} for p in ports]
    except:
        pass

    if reader.is_connected():
        return {
            "connected": True,
            "port": reader.connection.port_name() if reader.connection else "Unknown",
            "available_ports": available_ports
        }
    else:
        # Try auto-detect first, then common ports
        success = False
        for port in [None, "COM3", "COM4", "COM5"]:  # None = auto-detect, then try specific ports
            print(f"[API] Trying port: {port if port else 'auto-detect'}", flush=True)
            if port:
                reader.port = port
            success = connect_obd(port)
            if success:
                print(f"[API] Success on port: {port if port else 'auto-detect'}", flush=True)
                break
            print(f"[API] Failed on port: {port if port else 'auto-detect'}", flush=True)

        if success:
            return {
                "connected": True,
                "port": reader.connection.port_name() if reader.connection else "Unknown",
                "available_ports": available_ports
            }
        else:
            print("[API] All connection attempts failed", flush=True)
            return {
                "connected": False,
                "message": "No OBD adapter found on COM3, COM4, or COM5. Select manually or check connection.",
                "available_ports": available_ports
            }


@app.get("/obd/live")
async def obd_live_data():
    """Get live OBD data for real-time display."""
    reader = get_reader()

    if not reader.is_connected():
        return {
            "connected": False,
            "rpm": None,
            "speed": None,
            "coolant_temp": None
        }

    try:
        # Read live data
        rpm = None
        speed = None
        coolant_temp = None

        # RPM
        try:
            rpm_response = reader.connection.query(obd.commands.RPM)
            if not rpm_response.is_null():
                rpm = int(rpm_response.value.magnitude)
        except:
            pass

        # Speed (convert km/h to mph)
        try:
            speed_response = reader.connection.query(obd.commands.SPEED)
            if not speed_response.is_null():
                speed = int(speed_response.value.magnitude * 0.621371)
        except:
            pass

        # Coolant temp (convert Celsius to Fahrenheit)
        try:
            coolant_response = reader.connection.query(obd.commands.COOLANT_TEMP)
            if not coolant_response.is_null():
                celsius = coolant_response.value.magnitude
                coolant_temp = int((celsius * 9/5) + 32)
        except:
            pass

        return {
            "connected": True,
            "rpm": rpm,
            "speed": speed,
            "coolant_temp": coolant_temp
        }
    except Exception as e:
        print(f"[OBD] Error reading live data: {e}", flush=True)
        return {
            "connected": False,
            "rpm": None,
            "speed": None,
            "coolant_temp": None
        }


@app.get("/obd/read-vin")
async def obd_read_vin():
    """
    Read VIN from connected OBD adapter and decode it.
    Returns vehicle information if successful, or error if VIN reading fails.
    """
    reader = get_reader()

    if not reader.is_connected():
        return {
            "success": False,
            "error": "OBD adapter not connected"
        }

    # Read VIN with 5-second timeout
    vin = reader.read_vin(timeout=5.0)

    if not vin:
        return {
            "success": False,
            "error": "VIN not available"
        }

    # Decode VIN using CarsXE API
    from vehicle_data import decode_vin
    vehicle_info = await decode_vin(vin)

    return vehicle_info


class VinDecodeRequest(BaseModel):
    vin: str


@app.post("/vin/decode")
async def decode_vin_endpoint(request: VinDecodeRequest):
    """
    Decode a VIN manually (for fallback when OBD reading fails).
    """
    from vehicle_data import decode_vin
    return await decode_vin(request.vin)


class ImageRequest(BaseModel):
    year: str
    make: str
    model: str
    trim: Optional[str] = ""


@app.post("/trims")
async def get_trims(request: TrimRequest):
    """Get available trims for a vehicle from CarsXE API."""
    trims = await get_available_trims(request.year, request.make, request.model)
    return {"trims": trims}


@app.post("/vehicle-image")
async def vehicle_image(request: ImageRequest):
    """Get a vehicle image from CarsXE API."""
    print(f"[Image API] Request: {request.year} {request.make} {request.model} trim='{request.trim}'")
    image_data = await get_vehicle_image(request.year, request.make, request.model, request.trim or "")
    if image_data:
        # Return a proxied URL to avoid CORS issues
        original_url = image_data.get("url", "")
        thumbnail_url = image_data.get("thumbnail", "")

        if original_url:
            proxied_url = f"/image-proxy?url={urllib.parse.quote(original_url, safe='')}"
            # Always provide thumbnail as fallback in case main image is Cloudflare blocked
            if thumbnail_url:
                proxied_url += f"&fallback={urllib.parse.quote(thumbnail_url, safe='')}"
        else:
            proxied_url = ""
        return {
            "success": True,
            "url": proxied_url,
            "width": image_data.get("width", 0),
            "height": image_data.get("height", 0),
            "thumbnail": thumbnail_url
        }
    return {"success": False, "url": "", "message": "No image found"}


@app.get("/image-proxy")
async def image_proxy(url: str, fallback: str = None):
    """Proxy external images to avoid CORS issues."""
    print(f"[Image Proxy] Fetching: {url[:80]}...")
    if fallback:
        print(f"[Image Proxy] Has fallback: {fallback[:60]}...")

    # Extract domain from URL for referer
    from urllib.parse import urlparse
    parsed = urlparse(url)
    domain = f"{parsed.scheme}://{parsed.netloc}"

    # Try multiple header configurations - order matters, most likely to work first
    header_configs = [
        # Config 1: Full browser headers with groovecar referer (curl test showed this works)
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "image/webp,image/apng,image/png,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.groovecar.com/",
            "Connection": "keep-alive",
        },
        # Config 2: Use same domain as referer
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": domain + "/",
        },
        # Config 3: Google Images referer (often allowed)
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.google.com/"
        },
        # Config 4: Minimal headers - some CDNs prefer simplicity
        {
            "User-Agent": "Mozilla/5.0",
            "Accept": "*/*",
        },
        # Config 5: curl-like (no extra headers)
        {
            "User-Agent": "curl/8.0",
        }
    ]

    for i, headers in enumerate(header_configs):
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                response = await client.get(url, headers=headers)
                # Log more details for debugging
                resp_headers = dict(response.headers)
                cf_ray = resp_headers.get('cf-ray', 'none')
                print(f"[Image Proxy] Config {i+1} response: {response.status_code} (CF-Ray: {cf_ray})")

                if response.status_code == 200:
                    content_type = response.headers.get("content-type", "image/png")
                    # Verify we got actual image content, not an error page
                    if content_type.startswith("image/") and len(response.content) > 1000:
                        print(f"[Image Proxy] Success! Content-Type: {content_type}, Size: {len(response.content)} bytes")
                        return Response(
                            content=response.content,
                            media_type=content_type,
                            headers={"Cache-Control": "public, max-age=86400"}  # Cache for 1 day
                        )
                    else:
                        print(f"[Image Proxy] Got 200 but content suspicious: {content_type}, {len(response.content)} bytes")
                        continue
                elif response.status_code in (403, 401, 404, 503):
                    # Try all configs for stubborn sources like groovecar
                    # Log response body snippet for debugging CF issues
                    body_preview = response.text[:200] if response.text else "(empty)"
                    print(f"[Image Proxy] Config {i+1} got {response.status_code}: {body_preview[:100]}...")
                    continue
                else:
                    print(f"[Image Proxy] Failed with status {response.status_code}")
                    continue  # Try next config
        except Exception as e:
            print(f"[Image Proxy] Config {i+1} error: {type(e).__name__}: {e}")
            continue

    # Try fallback URL if provided (e.g., Google cached thumbnail for groovecar)
    if fallback:
        print(f"[Image Proxy] Trying fallback URL: {fallback[:60]}...")
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                response = await client.get(fallback, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "image/*,*/*",
                })
                if response.status_code == 200:
                    content_type = response.headers.get("content-type", "image/jpeg")
                    if len(response.content) > 500:
                        print(f"[Image Proxy] Fallback SUCCESS! Size: {len(response.content)} bytes")
                        return Response(
                            content=response.content,
                            media_type=content_type,
                            headers={"Cache-Control": "public, max-age=86400"}
                        )
        except Exception as e:
            print(f"[Image Proxy] Fallback error: {e}")

    # Return a 1x1 transparent PNG on error
    print(f"[Image Proxy] All configs failed for: {url[:60]}...")
    return Response(
        content=b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82',
        media_type="image/png",
        status_code=404
    )


@app.post("/interpret")
async def interpret(request: InterpretRequest):
    """
    Main diagnostic endpoint with DEEP trim-specific personalization.
    Uses engine characteristics (displacement, forced induction, cylinders) 
    to provide highly relevant diagnostics.
    """
    
    # Get OBD snapshot
    if request.use_live_obd:
        reader = get_reader()
        # Try to connect if not already connected
        if not reader.is_connected():
            print("[OBD] Attempting to connect...", flush=True)
            # Try auto-detect first, then common ports
            success = False
            for port in [None, "COM3", "COM4", "COM5"]:
                print(f"[OBD] Trying port: {port if port else 'auto-detect'}", flush=True)
                if port:
                    reader.port = port
                success = connect_obd(port)
                if success:
                    break

        if reader.is_connected():
            snapshot = reader.read_snapshot()
            obd_source = "Live OBD-II Data"
        else:
            snapshot = get_mock_snapshot()
            obd_source = "Demo Mode (OBD not connected)"
    else:
        snapshot = get_mock_snapshot()
        obd_source = "Demo Mode"
    
    # Get vehicle data by ID
    vehicle_data = await get_vehicle_by_id(request.vehicle_id)
    trim = request.trim or ""
    
    # Build engine profile for cost estimation and context
    engine_profile = build_engine_profile(vehicle_data)
    
    vehicle_str = format_vehicle_string(vehicle_data, include_engine=False) if vehicle_data else "Unknown Vehicle"
    if trim:
        vehicle_str_with_trim = f"{vehicle_str} {trim}"
    else:
        vehicle_str_with_trim = vehicle_str
    
    # Build comprehensive vehicle context
    vehicle_context = build_comprehensive_vehicle_context(vehicle_data, trim)
    
    # Initialize response
    response_data = {
        "codes": [],
        "vehicle": vehicle_str_with_trim,
        "engine": vehicle_data.get("engine", "") if vehicle_data else "",
        "fuel_type": vehicle_data.get("fuel_type", "") if vehicle_data else "",
        "drive": vehicle_data.get("drive", "") if vehicle_data else "",
        "transmission": vehicle_data.get("transmission", "") if vehicle_data else "",
        "supercharged": vehicle_data.get("supercharged", False) if vehicle_data else False,
        "turbocharged": vehicle_data.get("turbocharged", False) if vehicle_data else False,
        "hybrid": engine_profile.get("is_hybrid", False),
        "electric": engine_profile.get("is_electric", False),
        "performance_tier": engine_profile.get("performance_tier", "standard"),
        "rpm": int(snapshot.rpm) if snapshot.rpm else 750,
        "speed": int(snapshot.speed_mph) if snapshot.speed_mph else 0,
        "coolant_temp": int(snapshot.coolant_temp_f) if snapshot.coolant_temp_f else 205,
        "safety_level": "SAFE",
        "safety_meaning": SAFETY_DEFINITIONS["SAFE"]["meaning"],
        "safety_description": SAFETY_DEFINITIONS["SAFE"]["description"],
        "safety_action": SAFETY_DEFINITIONS["SAFE"]["action"],
        "dont_panic": "",
        "likely_causes": "",
        "symptoms": "",
        "if_ignored": "",
        "quick_checks": "",
        "diy_fix": "",
        "urgency": "",
        "repair_cost": "",
        "known_issues": "",
        "owner_reports": "",
        "data_sources": [],
        "obd_source": obd_source,
        "trim": trim
    }
    
    if vehicle_data:
        response_data["data_sources"].append("CarsXE")
    
    # No codes detected
    if not snapshot.dtc_codes:
        response_data["dont_panic"] = "No trouble codes detected. Your vehicle appears to be running fine."
        
        if vehicle_data:
            prompt = f"""You are a friendly vehicle assistant helping a car owner.

The owner scanned their vehicle and NO trouble codes were found.

{vehicle_context}

Write a helpful response (4-5 sentences) that:
1. Confirms no codes were found - their car's computer isn't reporting any problems
2. Give ONE maintenance tip that is SPECIFIC to their engine configuration:
   - If supercharged: mention supercharger belt or intercooler inspection
   - If turbocharged: mention turbo health, boost leaks, or intercooler
   - If large displacement V8: mention spark plugs, oil consumption checks
   - If AWD/4WD: mention transfer case fluid or differential service
   - If standard engine: mention timing belt/chain service or spark plugs
3. Mention their performance tier and what that means for maintenance

RULES:
- Use simple language - explain technical terms
- Be specific to THIS engine and drivetrain configuration
- NO analogies or metaphors
- English only"""

            ai_response = await ask_ollama(prompt)
            if not ai_response.startswith("ERROR:"):
                response_data["dont_panic"] = ai_response
        
        return response_data
    
    # Process codes
    codes_list = [c.code for c in snapshot.dtc_codes]
    response_data["codes"] = codes_list

    # Get official OBD code diagnoses from CarsXE
    obd_decoded = await decode_obd_codes_batch(codes_list)

    # Build codes text with official diagnoses when available
    codes_text_parts = []
    for c in snapshot.dtc_codes:
        decoded = obd_decoded.get(c.code.upper(), {})
        if decoded.get("success") and decoded.get("diagnosis"):
            # Use CarsXE's official diagnosis
            codes_text_parts.append(f"{c.code}: {decoded['diagnosis']}")
        else:
            # Fall back to OBD reader's description
            codes_text_parts.append(f"{c.code}: {c.description}")
    codes_text = ", ".join(codes_text_parts)

    print(f"\n[Main] Processing codes: {codes_list}")
    print(f"[Main] Vehicle: {vehicle_str_with_trim}")
    print(f"[Main] Engine: {response_data.get('engine', 'Unknown')}")
    print(f"[Main] Performance Tier: {engine_profile.get('performance_tier', 'standard')}")
    print(f"[Main] Cost Multiplier: {engine_profile.get('cost_multiplier', 1.0)}x")

    # Log decoded OBD info and track data source
    obd_decoded_count = sum(1 for d in obd_decoded.values() if d.get("success"))
    if obd_decoded_count > 0:
        print(f"[Main] CarsXE decoded {obd_decoded_count}/{len(codes_list)} codes")
        if "CarsXE OBD" not in response_data["data_sources"]:
            response_data["data_sources"].append("CarsXE OBD")
    
    # Get code info from reliable sources
    code_context = ""
    make = vehicle_data.get("make", "") if vehicle_data else ""
    model = vehicle_data.get("model", "") if vehicle_data else ""
    year = vehicle_data.get("year", "") if vehicle_data else ""
    engine_str = response_data.get("engine", "")
    
    for code in codes_list[:2]:
        # Pass trim and engine for personalized code info
        code_info = await get_code_info(code, make, model, year, trim, engine_str)
        
        if code_info:
            ctx = format_code_context(code_info, vehicle_str, trim, engine_str)
            if ctx:
                code_context += ctx + "\n\n"
                
                if code_info.get("obd_codes"):
                    if "OBD-Codes.com" not in response_data["data_sources"]:
                        response_data["data_sources"].append("OBD-Codes.com")
                if code_info.get("car_complaints"):
                    if "CarComplaints.com" not in response_data["data_sources"]:
                        response_data["data_sources"].append("CarComplaints.com")
                if code_info.get("repairpal"):
                    if "RepairPal.com" not in response_data["data_sources"]:
                        response_data["data_sources"].append("RepairPal.com")
    
    # Get Reddit data
    reddit_context = ""
    if make and model:
        for code in codes_list[:1]:
            reddit_data = await scrape_reddit_fallback(code, make, model, year)
            reddit_ctx = format_reddit_context(reddit_data)
            if reddit_ctx:
                reddit_context = reddit_ctx
                if "Community Forums" not in response_data["data_sources"]:
                    response_data["data_sources"].append("Community Forums")
    
    # Build the diagnostic prompt with DEEP vehicle context
    # NOTE: Structure is important to prevent prompt leakage with smaller models
    # Instructions go at START, output format in MIDDLE, data at END
    prompt = f"""[SYSTEM INSTRUCTIONS - DO NOT OUTPUT THIS SECTION]
You are ClearDrive, a friendly car expert. Write like you're talking to a friend who doesn't know cars.
- Explain technical terms in parentheses
- Be specific to this exact car and engine
- Be reassuring but honest
- No jargon without explanation
- No analogies or metaphors
- English only

[VEHICLE INFO]
{vehicle_context}

[TROUBLE CODE]
{codes_text}

[VEHICLE-SPECIFIC CODE ANALYSIS]
The codes above have been decoded by our OBD database. Now consider how these codes specifically affect THIS vehicle:
- Engine type: {response_data.get('engine', 'Unknown')} ({engine_profile.get('engine_layout', 'standard')})
- Aspiration: {'Supercharged' if engine_profile.get('is_supercharged') else 'Turbocharged' if engine_profile.get('is_turbocharged') else 'Naturally Aspirated'}
- Drivetrain: {response_data.get('drive', 'Unknown')}
- Performance tier: {engine_profile.get('performance_tier', 'standard')}

When explaining the code, relate it to these specific characteristics. For example:
- A misfire on a supercharged engine might indicate boost leak or intercooler issues
- A lean code on a turbo engine could be wastegate or boost control related
- An O2 sensor code on a V8 affects one bank (4 cylinders) vs both banks
- AWD vehicles may have additional sensors that can trigger codes

[YOUR RESPONSE - START HERE]

SAFETY LEVEL: [Pick ONE: SAFE, CAUTION, or STOP]

IMPORTANT - Be consistent! Your safety level MUST match your "WHEN TO SEE A MECHANIC" advice:

- SAFE = Truly minor issues that can wait weeks/months with no consequences.
  Examples: loose gas cap (P0442), minor O2 sensor drift, small EVAP leaks, cosmetic codes.
  Your mechanic advice should say "fix whenever convenient" or "can wait a few weeks."

- CAUTION = Needs attention within 1-2 weeks. Won't strand you today, but will get worse or affect performance.
  Examples: occasional misfires (P0300), catalyst efficiency (P0420), lean/rich codes (P0171/P0174), most sensor failures.
  Your mechanic advice should say "schedule service soon" or "get checked in the next week or two."

- STOP = Continuing to drive WILL cause expensive damage or is unsafe. Use this for:
  * Overheating codes (P0217, P0218) - will destroy engine
  * Oil pressure codes (P0520, P0521) - engine will seize
  * Severe/constant misfires with flashing CEL - destroys catalytic converter ($1000+)
  * Transmission overheating/slipping codes - will burn up transmission
  * Any code with symptoms like: burning smell, smoke, loud knocking, metal shavings, loss of power steering/brakes
  Your mechanic advice should say "stop driving immediately" or "have it towed" or "go straight to a mechanic."

Don't be afraid to use STOP when warranted - it could save them thousands in damage!

"""

    if code_context:
        prompt += f"""WHAT WE FOUND FROM CAR DATABASES:
We checked OBD-Codes.com, CarComplaints.com, and RepairPal.com for information about this code.
Look for any issues marked "SPECIFIC TO THIS TRIM/ENGINE" - those are from owners with the same engine as you!

{code_context}

"""

    # Add engine-specific diagnostic guidance based on characteristics (NOT hardcoded makes/models)
    if engine_profile.get("is_supercharged"):
        prompt += """ABOUT THIS ENGINE - SUPERCHARGED:
This car has a supercharger (a belt-driven air pump that makes the engine more powerful). This means:
- There are extra parts that can wear out (the supercharger belt, pulleys)
- If air is leaking anywhere, the engine won't run right
- It needs premium fuel and more frequent oil changes
- Repairs cost more because the parts are pricier (expect 50-100% more than a regular engine)

"""
    elif engine_profile.get("is_turbocharged"):
        prompt += """ABOUT THIS ENGINE - TURBOCHARGED:
This car has a turbo (uses exhaust gases to spin a turbine that pushes more air into the engine). This means:
- Air leaks in the intake system cause problems
- The turbo needs clean oil to stay healthy
- Carbon can build up on the valves over time
- Repairs cost more than a regular engine (20-50% more)

"""
    
    if engine_profile.get("cylinders", 0) >= 8:
        prompt += """ABOUT THIS ENGINE - V8:
This car has a V8 engine (8 cylinders). This means:
- There are 8 spark plugs and 8 ignition coils - more parts that can go bad
- If a problem is on "Bank 1" or "Bank 2," that tells the mechanic which side of the engine
- V8s tend to use a bit more oil than smaller engines, which is normal
- Some V8s shut off half the cylinders to save gas - this system can sometimes cause issues

"""
    
    drive = vehicle_data.get("drive", "") if vehicle_data else ""
    if "all" in drive.lower() or "awd" in drive.lower():
        prompt += """ABOUT THIS CAR - ALL-WHEEL DRIVE:
This car sends power to all four wheels. This means:
- There are extra parts (transfer case, extra differential) that need maintenance
- All four tires should be the same size and wear level, or you can damage the system
- There's extra fluid that needs to be changed periodically
- Vibrations or grinding noises could be from the AWD system

"""
    
    cost_mult = engine_profile.get("cost_multiplier", 1.0)
    perf_tier = engine_profile.get("performance_tier", "standard")
    
    # Don't mention multiplier to user - just use it internally for guidance
    prompt += f"""REPAIR COST GUIDANCE:
This is a {perf_tier} vehicle. Keep in mind:
- Performance vehicles have pricier parts than economy cars
- Dealers charge more than independent shops (usually 30-50% more)
- Some repairs need special tools or expertise

RESPONSE FORMAT - Follow EXACTLY:

SAFETY LEVEL: [SAFE, CAUTION, or STOP]
(Remember: SAFE means truly fine to ignore for weeks. If you're saying "get checked soon" or "in the next few days" - use CAUTION!)

WHAT'S HAPPENING:
Start with "Your {vehicle_str_with_trim} is showing code {codes_list[0]}."
Explain in 4-5 simple sentences that anyone can understand:
- What this code actually means (imagine explaining to someone who knows nothing about cars)
- Why this might be happening on this particular engine
- Reassure them if it's not serious, or be honest if it is

LIKELY CAUSES:
List 5 possible causes, starting with the most likely:
1. [Most likely cause] - Explain in plain English what this part does and why it might fail
2. [Second cause] - Simple explanation
3. [Third cause] - Simple explanation
4. [Fourth cause] - Simple explanation
5. [Fifth cause] - Simple explanation

If we found issues reported by OTHER OWNERS of this same engine, mention those first!

WHAT YOU MIGHT NOTICE:
List 4 things the driver might experience:
1. [What they'll feel/hear/see] - Why this happens
2. [Symptom] - Explanation
3. [Symptom] - Explanation
4. [Symptom] - Explanation

IF YOU IGNORE THIS:
Explain what could happen if they don't fix it:
- What might happen in the next few days/weeks
- What could happen long-term
- How much more expensive it could get
- Any safety concerns

QUICK CHECKS:
List 3 things they can check themselves (if safe to do so):
1. [Simple check] - Step by step instructions anyone can follow
2. [Check] - Step by step
3. [Check] - Step by step

Keep it simple - don't suggest anything that requires special tools or expertise.

DIY FIX:
If this is something a beginner/intermediate DIYer could realistically fix at home, provide:
1. Difficulty level (Beginner/Intermediate/Advanced)
2. Tools needed (be specific - socket sizes, etc.)
3. Brief step-by-step approach (3-5 steps)
4. Estimated time

If this is NOT a good DIY repair, clearly say:
"This repair is NOT recommended for DIY because [specific reason - needs special tools, requires lifting the car, safety risk, needs computer programming, etc.]. A professional mechanic should handle this."

Be honest - don't encourage DIY if it could make things worse or be dangerous.

WHEN TO SEE A MECHANIC:
Tell them clearly when to go. Examples:
- "This can wait a week or two, but don't forget about it"
- "Try to get this looked at in the next few days"
- "Go to a mechanic today - don't drive more than necessary"

ESTIMATED REPAIR COST:
Give honest cost ranges:
- Parts: $X - $Y
- Labor: $X - $Y  
- Total at independent shop: $X - $Y
- Total at dealer: $X - $Y (dealers charge more)
- Let them know if this needs a specialist

KNOWN ISSUES FOR THIS ENGINE (from database):
If the data above contains trim-specific or engine-specific issues from CarComplaints.com,
write 2-3 sentences summarizing what other owners of this exact engine experienced.
If there are TSBs or recalls mentioned, note them here.
If no trim-specific data was found, skip this section."""

    if reddit_context:
        prompt += f"""

OTHER OWNERS REPORT:
Based on community data, write 2-3 sentences about what owners of similar vehicles experienced:
{reddit_context}"""

    # End marker to help model know where to stop
    prompt += """

[END OF RESPONSE FORMAT]"""

    # Get AI response
    ai_response = await ask_ollama(prompt)
    
    if ai_response.startswith("ERROR:"):
        response_data["safety_level"] = "UNKNOWN"
        response_data["dont_panic"] = ai_response
        return response_data
    
    # Parse response
    parsed = parse_guidance(ai_response)
    
    # Set safety level and meaning
    safety_level = parsed["safety_level"]
    response_data["safety_level"] = safety_level
    response_data["safety_meaning"] = SAFETY_DEFINITIONS.get(safety_level, SAFETY_DEFINITIONS["CAUTION"])["meaning"]
    response_data["safety_description"] = SAFETY_DEFINITIONS.get(safety_level, SAFETY_DEFINITIONS["CAUTION"])["description"]
    response_data["safety_action"] = SAFETY_DEFINITIONS.get(safety_level, SAFETY_DEFINITIONS["CAUTION"])["action"]
    
    response_data["dont_panic"] = parsed["dont_panic"]
    response_data["likely_causes"] = parsed["likely_causes"]
    response_data["symptoms"] = parsed["symptoms"]
    response_data["if_ignored"] = parsed["if_ignored"]
    response_data["quick_checks"] = parsed["quick_checks"]
    response_data["diy_fix"] = parsed["diy_fix"]
    response_data["urgency"] = parsed["urgency"]
    response_data["repair_cost"] = parsed["repair_cost"]
    response_data["known_issues"] = parsed["known_issues"]
    response_data["owner_reports"] = parsed["owner_reports"]
    
    # Log scan
    log_scan(", ".join(codes_list), parsed["safety_level"], ai_response)
    
    return response_data


@app.post("/followup")
async def followup(request: FollowUpRequest):
    """Handle follow-up questions with full vehicle context from CarsXE."""

    # Extract all available context
    vehicle = request.context.get("vehicle", "the vehicle")
    engine = request.context.get("engine", "")
    drive = request.context.get("drive", "")
    transmission = request.context.get("transmission", "")
    trim = request.context.get("trim", "")
    codes = request.context.get("codes", [])
    safety = request.context.get("safety_level", "UNKNOWN")
    supercharged = request.context.get("supercharged", False)
    turbocharged = request.context.get("turbocharged", False)
    is_hybrid = request.context.get("hybrid", False)
    is_electric = request.context.get("electric", False)
    performance_tier = request.context.get("performance_tier", "standard")
    fuel_type = request.context.get("fuel_type", "")

    # Additional CarsXE details
    msrp = request.context.get("msrp", "")
    horsepower = request.context.get("horsepower", "")
    body_style = request.context.get("body_style", "")
    summary = request.context.get("summary", "")
    likely_causes = request.context.get("likely_causes", "")

    # Build powertrain description
    if is_electric:
        powertrain = "electric"
    elif is_hybrid:
        powertrain = "hybrid (gas + electric)"
    elif supercharged:
        powertrain = "supercharged"
    elif turbocharged:
        powertrain = "turbocharged"
    else:
        powertrain = "naturally aspirated"

    # Build rich vehicle context
    vehicle_details = [f"{vehicle} {trim}".strip()]
    if engine:
        vehicle_details.append(f"Engine: {engine}")
    if horsepower:
        vehicle_details.append(f"Power: {horsepower} hp")
    if transmission:
        vehicle_details.append(f"Trans: {transmission}")
    if drive:
        vehicle_details.append(f"Drive: {drive}")
    if fuel_type:
        vehicle_details.append(f"Fuel: {fuel_type}")
    if msrp:
        vehicle_details.append(f"MSRP: ${msrp}")
    if body_style:
        vehicle_details.append(f"Body: {body_style}")

    vehicle_context = " | ".join(vehicle_details)

    # Performance context
    perf_context = ""
    if performance_tier == "high-performance":
        perf_context = "This is a HIGH-PERFORMANCE vehicle - parts and repairs cost 50-100% more than standard."
    elif performance_tier == "sport":
        perf_context = "This is a SPORT-tier vehicle - expect 20-50% higher parts costs than economy cars."

    history_text = ""
    if request.history:
        history_text = "\n\nPrevious conversation:\n"
        for msg in request.history[-4:]:
            role = "Owner" if msg["role"] == "user" else "Assistant"
            history_text += f"{role}: {msg['content']}\n"

    # Include diagnostic summary for context
    diag_context = ""
    if summary:
        diag_context = f"\nDiagnosis summary: {summary[:200]}..."
    if likely_causes:
        diag_context += f"\nLikely causes: {likely_causes[:200]}..."

    prompt = f"""[SYSTEM - DO NOT OUTPUT]
You are ClearDrive, a helpful car diagnostic assistant. Be specific and actionable.

RULES:
- If asked HOW to do something: give numbered step-by-step instructions
- If asked for videos/links: say "I can't provide links, but here's what to search for: [specific search terms]"
- If asked about a part: explain what it does and where it's located on this specific vehicle
- If asked about cost: factor in the performance tier (high-performance parts cost more!)
- Be specific to this {powertrain} engine
- Use the horsepower, MSRP, and trim info to give accurate answers
- 3-5 sentences unless steps are needed
- English only

CRITICAL - MATCH SAFETY LEVEL WITH DRIVING ADVICE:
The safety level is {safety}. Your driving advice MUST match this:
- SAFE = Can drive normally for weeks/months, no rush
- CAUTION = Safe to drive short distances, but schedule service within 1-2 weeks. DON'T say "don't drive" or "avoid driving" - they CAN drive!
- STOP = Should NOT drive at all (except to mechanic). Only say "don't drive" if safety level is STOP.

If someone asks "can I drive?" or similar:
- CAUTION: "Yes, you can drive but schedule service soon" NOT "I wouldn't recommend driving"
- STOP: "No, you should go straight to a mechanic or have it towed"

[VEHICLE DETAILS]
{vehicle_context}
Performance tier: {performance_tier}
{perf_context}

[CURRENT DIAGNOSTIC]
Codes: {', '.join(codes) if codes else 'None'}
Safety Level: {safety}
{diag_context}
{history_text}

[QUESTION]
{request.question}

[ANSWER]"""

    response = await ask_ollama(prompt)

    if response.startswith("ERROR:"):
        return {"answer": "Sorry, I couldn't process that question. Please try again."}

    return {"answer": response.strip()}


@app.get("/history")
async def history():
    scans = get_recent_scans(10)
    return [
        {"timestamp": s[0], "codes": s[1], "safety": s[2], "guidance": s[3]}
        for s in scans
    ]


@app.get("/safety-definitions")
async def get_safety_definitions():
    """Return the safety level definitions for the frontend."""
    return SAFETY_DEFINITIONS


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
