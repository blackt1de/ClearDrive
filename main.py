import random
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from schemas import DTCCode, OBDSnapshot
from ollama_client import ask_ollama, check_ollama
from database import init_db, log_scan, get_recent_scans
from obd_reader import get_reader, connect_obd
from vehicle_data import get_available_trims, get_vehicle_by_id, format_vehicle_string, format_vehicle_context
from code_scraper import get_code_info, format_code_context
from forum_scraper import scrape_reddit_fallback, format_reddit_context

app = FastAPI(title="ClearDrive", version="0.5.0")

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
        "urgency": "",
        "repair_cost": "",
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
        "MECHANIC URGENCY": "urgency",
        "WHEN TO SEE": "urgency",
        "REPAIR COST": "repair_cost",
        "ESTIMATED COST": "repair_cost",
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
        [],
        [DTCCode(code="P0420", description="Catalyst Efficiency Below Threshold")],
        [DTCCode(code="P0300", description="Random Misfire Detected"),
         DTCCode(code="P0301", description="Cylinder 1 Misfire")],
        [DTCCode(code="P0171", description="System Too Lean Bank 1")],
        [DTCCode(code="P0455", description="EVAP System Large Leak")],
        [DTCCode(code="P0128", description="Coolant Thermostat Below Temp")],
        [DTCCode(code="P0507", description="Idle Air Control RPM Higher Than Expected")],
        [DTCCode(code="P0442", description="EVAP System Small Leak")],
        [DTCCode(code="P0401", description="EGR Flow Insufficient")],
        [DTCCode(code="P0174", description="System Too Lean Bank 2")],
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
    
    lines.append(f"  Cost Multiplier: {profile['cost_multiplier']}x compared to economy vehicles")
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


@app.get("/health")
async def health():
    ollama_status = await check_ollama()
    return {"status": "ok", "ollama": ollama_status}


@app.get("/obd/status")
async def obd_status():
    """Check if OBD adapter is connected."""
    reader = get_reader()
    if reader.is_connected():
        return {
            "connected": True,
            "port": reader.connection.port_name() if reader.connection else "Unknown"
        }
    else:
        success = connect_obd()
        if success:
            return {
                "connected": True,
                "port": reader.connection.port_name() if reader.connection else "Unknown"
            }
        else:
            return {
                "connected": False,
                "message": "No OBD adapter found. Make sure it's plugged in and paired via Bluetooth."
            }


@app.post("/trims")
async def get_trims(request: TrimRequest):
    """Get available trims for a vehicle from FuelEconomy.gov."""
    trims = await get_available_trims(request.year, request.make, request.model)
    return {"trims": trims}


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
        "urgency": "",
        "repair_cost": "",
        "owner_reports": "",
        "data_sources": [],
        "obd_source": obd_source,
        "trim": trim
    }
    
    if vehicle_data:
        response_data["data_sources"].append("FuelEconomy.gov")
    
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
    codes_text = ", ".join([f"{c.code}: {c.description}" for c in snapshot.dtc_codes])
    codes_list = [c.code for c in snapshot.dtc_codes]
    response_data["codes"] = codes_list
    
    print(f"\n[Main] Processing codes: {codes_list}")
    print(f"[Main] Vehicle: {vehicle_str_with_trim}")
    print(f"[Main] Engine: {response_data.get('engine', 'Unknown')}")
    print(f"[Main] Performance Tier: {engine_profile.get('performance_tier', 'standard')}")
    print(f"[Main] Cost Multiplier: {engine_profile.get('cost_multiplier', 1.0)}x")
    
    # Get code info from reliable sources
    code_context = ""
    make = vehicle_data.get("make", "") if vehicle_data else ""
    model = vehicle_data.get("model", "") if vehicle_data else ""
    year = vehicle_data.get("year", "") if vehicle_data else ""
    
    for code in codes_list[:2]:
        code_info = await get_code_info(code, make, model, year)
        
        if code_info:
            ctx = format_code_context(code_info, vehicle_str)
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
    prompt = f"""You are ClearDrive, a vehicle diagnostic assistant that provides HIGHLY PERSONALIZED advice based on the specific vehicle configuration.

YOUR TASK: Diagnose trouble codes for this SPECIFIC vehicle. Your advice must be tailored to the exact engine type, forced induction system (if any), displacement, and drivetrain.

{vehicle_context}

DIAGNOSTIC TROUBLE CODES: {codes_text}

SAFETY RATING DEFINITIONS:
- SAFE = Minor issue, won't damage vehicle. Safe to drive. Schedule repair when convenient.
- CAUTION = Needs attention in 1-2 weeks. Safe for short trips but will worsen if ignored.
- STOP = Continuing to drive could cause PERMANENT DAMAGE. Go to mechanic immediately.

"""

    if code_context:
        prompt += f"""TECHNICAL REFERENCE DATA:
{code_context}

"""

    # Add engine-specific diagnostic guidance based on characteristics (NOT hardcoded makes/models)
    if engine_profile.get("is_supercharged"):
        prompt += """SUPERCHARGED ENGINE DIAGNOSTIC CONSIDERATIONS:
- This engine has a supercharger that adds complexity
- Boost leaks can cause lean conditions and misfires
- Supercharger belt and tensioner are additional failure points
- Intercooler issues can affect performance
- Higher cylinder pressures mean ignition issues are more critical
- Parts costs are 50-100% higher than naturally aspirated versions

"""
    elif engine_profile.get("is_turbocharged"):
        prompt += """TURBOCHARGED ENGINE DIAGNOSTIC CONSIDERATIONS:
- This engine has turbocharger(s) adding complexity
- Boost leaks cause lean conditions and power loss
- Wastegate and blow-off valve issues are common
- Oil quality is critical - turbo bearings need clean oil
- Carbon buildup on intake valves is common (especially direct injection)
- Parts costs are 20-50% higher than naturally aspirated versions

"""
    
    if engine_profile.get("cylinders", 0) >= 8:
        prompt += """V8 ENGINE DIAGNOSTIC CONSIDERATIONS:
- Has 8 cylinders with individual ignition coils/plugs
- More ignition components = more potential failure points
- Cylinder deactivation systems (if equipped) can cause issues
- Bank 1 vs Bank 2 matters for diagnosis
- Oil consumption tends to be higher than smaller engines

"""
    
    drive = vehicle_data.get("drive", "") if vehicle_data else ""
    if "all" in drive.lower() or "awd" in drive.lower():
        prompt += """AWD SYSTEM DIAGNOSTIC CONSIDERATIONS:
- All-wheel drive adds transfer case and extra differential
- Drivetrain binding can occur if tire sizes don't match
- More fluids to maintain (transfer case, differentials)
- AWD issues can cause vibrations, noise, and handling problems

"""
    
    cost_mult = engine_profile.get("cost_multiplier", 1.0)
    perf_tier = engine_profile.get("performance_tier", "standard")
    
    prompt += f"""COST ESTIMATION GUIDANCE:
This vehicle is classified as "{perf_tier}" with a cost multiplier of {cost_mult}x.
- Base repair costs should be multiplied by {cost_mult}
- High-performance variants require specialized parts
- Dealer vs independent shop price difference is typically 30-50%

RESPONSE FORMAT - Follow EXACTLY:

SAFETY LEVEL: [SAFE, CAUTION, or STOP]

WHAT'S HAPPENING:
Start with "Your {vehicle_str_with_trim} is showing code {codes_list[0]}."
Explain in 4-5 sentences:
- What this code means (explain technical terms)
- Why THIS SPECIFIC ENGINE CONFIGURATION might trigger this code
- If supercharged/turbocharged: mention if boost system could be involved
- If V8: mention which bank might be affected
- If AWD: mention if drivetrain could be related

LIKELY CAUSES:
List 5 causes, ORDERED BY LIKELIHOOD for THIS engine type:
1. [Most likely cause for this engine] - [What it is and why it fails on this configuration]
2. [Second cause] - [Explanation specific to this engine type]
3. [Third cause] - [Explanation]
4. [Fourth cause] - [Explanation]
5. [Fifth cause] - [Explanation]

For supercharged engines, include boost-related causes.
For turbocharged engines, include turbo-related causes.
For V8s, include ignition system causes.

WHAT YOU MIGHT NOTICE:
List 4 symptoms SPECIFIC to this engine configuration:
1. [Symptom] - [Why this happens on this engine type]
2. [Symptom] - [Explanation]
3. [Symptom] - [Explanation]
4. [Symptom] - [Explanation]

IF YOU IGNORE THIS:
Write 4 sentences explaining:
- Short term consequences (specific to this engine type)
- Long term damage potential
- Cost escalation (using the {cost_mult}x multiplier)
- Safety implications

QUICK CHECKS:
List 3 checks appropriate for this engine configuration:
1. [Check specific to this engine] - [Step by step]
2. [Check] - [Step by step]
3. [Check] - [Step by step]

If supercharged: include boost leak check or belt inspection
If turbocharged: include intercooler pipe check or wastegate check
If V8: include coil/plug inspection

WHEN TO SEE A MECHANIC:
Based on safety level, state urgency and explain why this engine configuration matters.

ESTIMATED REPAIR COST:
Give costs SPECIFIC to this "{perf_tier}" vehicle:
- Parts: $X - $Y (adjusted for {cost_mult}x multiplier)
- Labor: $X - $Y
- Total at independent shop: $X - $Y
- Total at dealer: $X - $Y (30-50% higher)
- Note if specialized tools or expertise needed for this engine type"""

    if reddit_context:
        prompt += f"""

OTHER {make.upper()} {model.upper()} OWNERS REPORT:
Based on community data, write 2-3 sentences about what owners of similar vehicles experienced:
{reddit_context}"""

    prompt += """

CRITICAL RULES:
- Make advice SPECIFIC to this exact engine configuration
- Mention supercharger/turbo if equipped and relevant
- Use the cost multiplier for repair estimates
- Explain every technical term
- NO generic advice that could apply to any car
- NO analogies or metaphors
- English only"""

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
    response_data["urgency"] = parsed["urgency"]
    response_data["repair_cost"] = parsed["repair_cost"]
    response_data["owner_reports"] = parsed["owner_reports"]
    
    # Log scan
    log_scan(", ".join(codes_list), parsed["safety_level"], ai_response)
    
    return response_data


@app.post("/followup")
async def followup(request: FollowUpRequest):
    """Handle follow-up questions with full vehicle context."""
    
    vehicle = request.context.get("vehicle", "the vehicle")
    engine = request.context.get("engine", "")
    drive = request.context.get("drive", "")
    trim = request.context.get("trim", "")
    codes = request.context.get("codes", [])
    safety = request.context.get("safety_level", "UNKNOWN")
    summary = request.context.get("summary", "")
    supercharged = request.context.get("supercharged", False)
    turbocharged = request.context.get("turbocharged", False)
    performance_tier = request.context.get("performance_tier", "standard")
    
    # Build aspiration context
    aspiration = "naturally aspirated"
    if supercharged:
        aspiration = "supercharged"
    elif turbocharged:
        aspiration = "turbocharged"
    
    history_text = ""
    if request.history:
        history_text = "\n\nPrevious conversation:\n"
        for msg in request.history[-4:]:
            role = "Owner" if msg["role"] == "user" else "Assistant"
            history_text += f"{role}: {msg['content']}\n"
    
    prompt = f"""You are ClearDrive, a vehicle diagnostic assistant.

VEHICLE CONTEXT:
- Full name: {vehicle}
- Trim: {trim or 'Not specified'}
- Engine: {engine or 'Not specified'}
- Aspiration: {aspiration}
- Performance tier: {performance_tier}
- Drivetrain: {drive or 'Not specified'}
- Codes: {', '.join(codes) if codes else 'None'}
- Safety Level: {safety}
- Previous Diagnosis: {summary}
{history_text}

RULES:
- Give advice SPECIFIC to this {aspiration} {engine or 'engine'}
- If supercharged/turbocharged, consider boost system in your answer
- Use simple language, explain technical terms
- Keep answers 3-5 sentences unless more detail requested
- NO analogies or metaphors
- English only

Question: {request.question}

Answer:"""

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
    uvicorn.run(app, host="127.0.0.1", port=8000)
