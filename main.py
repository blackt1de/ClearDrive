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
from vehicle_data import get_available_trims, get_vehicle_by_id, get_vehicle_image, format_vehicle_string, format_vehicle_context
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


class ImageRequest(BaseModel):
    year: str
    make: str
    model: str


@app.post("/trims")
async def get_trims(request: TrimRequest):
    """Get available trims for a vehicle from CarsXE API."""
    trims = await get_available_trims(request.year, request.make, request.model)
    return {"trims": trims}


@app.post("/vehicle-image")
async def vehicle_image(request: ImageRequest):
    """Get a vehicle image from CarsXE API."""
    image_data = await get_vehicle_image(request.year, request.make, request.model)
    if image_data:
        return {
            "success": True,
            "url": image_data.get("url", ""),
            "width": image_data.get("width", 0),
            "height": image_data.get("height", 0),
            "thumbnail": image_data.get("thumbnail", "")
        }
    return {"success": False, "url": "", "message": "No image found"}


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
    uvicorn.run(app, host="127.0.0.1", port=8000)
