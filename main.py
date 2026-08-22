import os
import random
import re
import urllib.parse
import httpx
import obd
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from schemas import (
    DTCCode, OBDSnapshot, FuelTrim, FreezeFrame, Mode06Test, CapabilityProfile,
)
from ollama_client import ask_ollama, check_ollama
from database import (
    init_db,
    log_scan,
    get_recent_scans,
    log_followup,
    log_feedback,
    init_research_table,
    log_research_scan,
)
from obd_reader import get_reader, connect_obd
from vehicle_data import get_available_trims, get_vehicle_by_id, get_vehicle_image, format_vehicle_string, format_vehicle_context, decode_obd_codes_batch, format_engine_string, format_transmission_string, format_drive_string
from code_scraper import get_code_info, format_code_context
import dtc_definitions
import diagnostics
import fixtures
from knowledge import build_retrieval_block

app = FastAPI(title="ClearDrive", version="0.7.0")

# =============================================================================
# SCRAPED-CONTENT FLAGS
# =============================================================================
# Per-request live scraping makes prompt content depend on what a website said
# that day, so a baseline is not reproducible and eval arms are not comparable
# across time. Scraped context is therefore being removed from the prompt path.
#
# Reddit (forum_scraper) is already gone from /interpret — worst provenance,
# uncitable in an evidence pointer. forum_scraper.py itself stays because
# scrape_training_data.py:75 imports its primitives.
#
# OBD-Codes / CarComplaints / RepairPal (code_scraper) are gated OFF here and
# get deleted once their sourced replacements land: SAE J2012 + a manufacturer
# definitions table for code semantics, NHTSA complaints + the platform KB for
# vehicle-specific failure patterns. Both replacements carry source and
# retrieved_at; nothing is lost.
#
# The flag exists only so the old path can be re-enabled for a controlled
# A/B against the replacement. It must stay OFF in any run that produces
# published numbers.
ENABLE_SCRAPED_CODE_CONTEXT = os.environ.get("ENABLE_SCRAPED_CODE_CONTEXT", "0") == "1"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()
init_research_table()


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
    },
    "UNKNOWN": {
        "meaning": "Could Not Be Determined",
        "description": "The scan did not return the measurements needed to judge how safe this vehicle is to drive. Treat this as unassessed, not as safe.",
        "action": "Have the vehicle checked rather than assuming it is fine",
        "icon": "⚪"
    }
}

# The verdict is computed in diagnostics.compute_safety and the model restates
# it. These are the legacy labels iOS and the PWA already render.
VERDICT_TO_LEGACY = {
    diagnostics.VERDICT_OK: "SAFE",
    diagnostics.VERDICT_CAUTION: "CAUTION",
    diagnostics.VERDICT_STOP: "STOP",
    diagnostics.VERDICT_INSUFFICIENT: "UNKNOWN",
}


def apply_safety(response_data: dict, verdict: diagnostics.SafetyVerdict) -> str:
    """Write the computed verdict into the response; returns the legacy label."""
    label = VERDICT_TO_LEGACY[verdict.verdict]
    response_data["safety"] = verdict.to_dict()
    response_data["safety_level"] = label
    response_data["safety_meaning"] = SAFETY_DEFINITIONS[label]["meaning"]
    response_data["safety_description"] = SAFETY_DEFINITIONS[label]["description"]
    response_data["safety_action"] = SAFETY_DEFINITIONS[label]["action"]
    return label


class TrimRequest(BaseModel):
    year: str
    make: str
    model: str


class InterpretRequest(BaseModel):
    # vehicle_id is not required when `scenario` supplies its own vehicle.
    vehicle_id: str = ""
    trim: Optional[str] = ""
    color: Optional[str] = None  # Selected exterior color for image matching
    transmission: Optional[str] = None  # User-selected transmission option
    use_live_obd: Optional[bool] = False
    # Client-provided OBD data (from phone's Bluetooth connection)
    client_codes: Optional[List[str]] = None
    client_rpm: Optional[int] = None
    client_speed: Optional[int] = None
    client_coolant_temp: Optional[int] = None
    obd_source: Optional[str] = None

    # --- payload v2, all optional so existing iOS builds are unaffected ---
    # Odometer is not readable over generic OBD-II on most vehicles, so mileage
    # is user-entered. Distance-since-codes-cleared is a different PID entirely.
    client_mileage: Optional[int] = None
    client_engine_load_pct: Optional[float] = None
    client_intake_air_temp: Optional[float] = None
    client_pending_codes: Optional[List[str]] = None
    client_permanent_codes: Optional[List[str]] = None
    client_fuel_trims: Optional[List[dict]] = None
    client_freeze_frames: Optional[List[dict]] = None
    client_mode06: Optional[List[dict]] = None
    client_capability: Optional[dict] = None

    # Name of a deterministic synthetic fixture from fixtures.py. Development
    # and regression only — a scenario response is never research-logged.
    scenario: Optional[str] = None


class FollowUpRequest(BaseModel):
    question: str
    context: dict
    history: List[dict] = []
    scan_id: Optional[int] = None
    is_human_generated: bool = True


class FeedbackRequest(BaseModel):
    scan_id: int
    rating: str


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
        "service_recommendations": "",  # oil type, interval, notes
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
        "WHATS HAPPENING": "dont_panic",
        "LIKELY CAUSES": "likely_causes",
        "POSSIBLE CAUSES": "likely_causes",
        "WHAT YOU MIGHT NOTICE": "symptoms",
        "SYMPTOMS": "symptoms",
        "IF YOU IGNORE": "if_ignored",
        "CONSEQUENCES": "if_ignored",
        "QUICK CHECKS": "quick_checks",
        "CHECKS YOU CAN DO": "quick_checks",
        "DIY FIX": "diy_fix",
        "DIY REPAIR": "diy_fix",
        "DO IT YOURSELF": "diy_fix",
        "MECHANIC URGENCY": "urgency",
        "WHEN TO SEE": "urgency",
        "SEE A MECHANIC": "urgency",
        # "ESTIMATED REPAIR COST" must be listed explicitly. Anchored prefix
        # matching does not see "REPAIR COST" inside it the way the old
        # substring matching did, and the prompt emits the longer form — so
        # without this entry the section parses as empty. test_diagnostics.py
        # asserts every header the prompt emits resolves, so this cannot recur.
        "ESTIMATED REPAIR COST": "repair_cost",
        "REPAIR COST": "repair_cost",
        "ESTIMATED COST": "repair_cost",
        "COST ESTIMATE": "repair_cost",
        "SERVICE RECOMMENDATIONS": "service_recommendations",
        "SERVICE": "service_recommendations",
        "OIL TYPE": "service_recommendations",
        "MAINTENANCE": "service_recommendations",
        "KNOWN ISSUES": "known_issues",
        # "DATABASE" was a section key here. It never appears as a legitimate
        # header and, under the old substring matching, any prose mentioning a
        # database silently opened the known_issues section. Removed.
        "ENGINE ISSUES": "known_issues",
        "COMMON ISSUES": "known_issues",
        "OTHER OWNERS": "owner_reports",
        "COMMUNITY": "owner_reports",
        "OWNER REPORTS": "owner_reports"
    }
    
    # Header matching is ANCHORED, not substring-anywhere.
    #
    # The previous implementation tested `if header in line_upper` against every
    # line, so any prose containing "DATABASE", "SERVICE", or "COMMUNITY" silently
    # started a new section and dropped whatever preceded it. The prompt itself
    # contained the words "CAR DATABASES", which made the failure self-inflicted
    # and means the measured format-adherence score was partly grading this bug
    # rather than the model.
    #
    # A line is a header candidate only if it is the label part before a colon,
    # or a short all-caps line. Candidates are matched by PREFIX, longest header
    # first, so "KNOWN ISSUES FOR THIS ENGINE:" resolves to "KNOWN ISSUES" while
    # "WHAT WE FOUND FROM CAR DATABASES:" matches nothing.
    ordered_headers = sorted(section_map.items(), key=lambda kv: -len(kv[0]))

    def _header_for(raw_line: str):
        stripped = raw_line.strip().lstrip("#*-• ").strip()
        if not stripped:
            return None
        head = stripped.upper()
        colon = head.find(":")
        if 0 < colon <= 60:
            candidate = head[:colon].strip()
        elif head == stripped.upper() and stripped.upper() == stripped and len(stripped) <= 60:
            candidate = head.strip()
        else:
            return None
        for header, key in ordered_headers:
            if candidate.startswith(header):
                return key
        return None

    def _flush(section, text):
        if not section or not text:
            return
        if section == "safety_level":
            val = ' '.join(text).strip().upper()
            sections[section] = "STOP" if "STOP" in val else "CAUTION" if "CAUTION" in val else "SAFE"
        else:
            sections[section] = '\n'.join(text).strip()

    for line in lines:
        key = _header_for(line)

        if key:
            _flush(current_section, current_text)
            current_section = key
            current_text = []

            after_colon = line.split(':', 1)
            if len(after_colon) > 1 and after_colon[1].strip():
                current_text.append(after_colon[1].strip())
        elif current_section and line.strip():
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
    
    # Get engine string for parsing
    engine_str = vehicle_data.get("engine", "").lower()
    fuel_type = vehicle_data.get("fuel_type", "").lower()

    # Detect forced induction from vehicle_data flags OR engine string
    profile["is_supercharged"] = (
        vehicle_data.get("supercharged", False) or
        "supercharg" in engine_str or
        "s/c" in engine_str
    )
    profile["is_turbocharged"] = (
        vehicle_data.get("turbocharged", False) or
        "turbo" in engine_str or
        "twin turbo" in engine_str or
        "twinturbo" in engine_str or
        bool(re.search(r'\d+\.?\d*t\b', engine_str))  # Detect "2.0t", "3.0t" patterns
    )
    profile["is_naturally_aspirated"] = not (profile["is_supercharged"] or profile["is_turbocharged"])

    # Detect hybrid/electric from fuel_type, engine string, or ev_motor flag
    profile["is_hybrid"] = (
        "hybrid" in fuel_type or
        "hybrid" in engine_str or
        bool(vehicle_data.get("ev_motor"))
    )
    profile["is_electric"] = (
        ("electric" in fuel_type and "hybrid" not in fuel_type) or
        ("electric" in engine_str and "hybrid" not in engine_str) or
        "ev" in engine_str.split() or  # standalone "EV"
        "bev" in engine_str
    )
    
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
    ai_status = await check_ollama()
    return {"status": "ok", "ai": ai_status}


@app.get("/health/dtc")
async def health_dtc():
    """DTC-lookup health: canonical-dict size + CarsXE fallback count over 24h."""
    from vehicle_data import get_dtc_stats
    return {"status": "ok", **get_dtc_stats()}


@app.get("/demo/snapshot")
async def demo_snapshot():
    """
    Demo endpoint for testing - returns random mock OBD data.
    Use this to test the iOS app without real OBD hardware.
    """
    snapshot = get_mock_snapshot()
    return {
        "timestamp": snapshot.timestamp.isoformat(),
        "dtc_codes": [{"code": c.code, "description": c.description} for c in snapshot.dtc_codes],
        "rpm": snapshot.rpm,
        "speed_mph": snapshot.speed_mph,
        "coolant_temp_f": snapshot.coolant_temp_f,
        "is_mock": True
    }


@app.get("/demo/scenarios")
async def demo_scenarios():
    """List the deterministic synthetic scan fixtures.

    Run one with: POST /interpret {"scenario": "<name>"}. A fixture supplies its
    own vehicle profile, so a scenario run is fully offline and reproducible, and
    is never written to research_scans.
    """
    return {
        "scenarios": fixtures.list_scenarios(),
        "usage": 'POST /interpret with {"scenario": "<name>"}',
        "warning": (
            "Synthetic data. Suitable for development and regression only — a "
            "fixture encodes an assumption about how a car behaves and cannot "
            "validate diagnostic logic. Validation needs real captures."
        ),
    }


@app.get("/demo/scenario/{name}")
async def demo_scenario(name: str):
    """Return one fixture's raw payload without running the model."""
    s = fixtures.get_scenario(name)
    if not s:
        return {"error": f"Unknown scenario '{name}'",
                "available": [x["name"] for x in fixtures.list_scenarios()]}
    snap = s["snapshot"]
    return {
        "name": s["name"], "description": s["description"],
        "vehicle": s["vehicle"], "trim": s["trim"],
        "snapshot": snap.model_dump(mode="json"),
        "resolved_definitions": dtc_definitions.resolve_all([c.code for c in snap.dtc_codes]),
        "safety": diagnostics.compute_safety(
            diagnostics.analyze(snap, s["vehicle"]), snap, s["vehicle"]).to_dict(),
        "analysis": {
            "derived": diagnostics.analyze(snap, s["vehicle"]).derived,
            "findings": [
                {"rule": f.rule_id, "conclusion": f.conclusion,
                 "confidence": f.confidence, "basis": f.basis,
                 "evidence": [{"pointer": e.pointer, "restatement": e.restatement}
                              for e in f.evidence],
                 "next_checks": f.next_checks}
                for f in diagnostics.analyze(snap, s["vehicle"]).findings
            ],
            "not_assessed": [
                {"rule": a.rule_id, "reason": a.reason, "missing": a.missing}
                for a in diagnostics.analyze(snap, s["vehicle"]).abstentions
            ],
        },
    }


@app.get("/demo/vehicle")
async def demo_vehicle():
    """
    Demo endpoint - returns a sample vehicle for testing.
    """
    return {
        "success": True,
        "vin": "1HGBH41JXMN109186",
        "year": "2021",
        "make": "Honda",
        "model": "Accord",
        "trim": "Sport",
        "engine": "1.5L Turbo I4",
        "drive": "FWD",
        "transmission": "CVT",
        "fuel_type": "Gasoline"
    }


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
            "coolant_temp": None,
            "fuel_level": None,
            "odometer": None
        }

    try:
        # Read live data
        rpm = None
        speed = None
        coolant_temp = None
        fuel_level = None
        odometer = None

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

        # Fuel level (percentage)
        try:
            fuel_response = reader.connection.query(obd.commands.FUEL_LEVEL)
            if not fuel_response.is_null():
                fuel_level = int(fuel_response.value.magnitude)
                print(f"[OBD] Fuel level: {fuel_level}%", flush=True)
        except Exception as e:
            print(f"[OBD] Fuel level not supported: {e}", flush=True)

        # Odometer - try different methods
        # Method 1: Standard OBD2 (rarely supported)
        try:
            # Try DISTANCE_SINCE_DTC_CLEAR as a proxy (cumulative distance)
            dist_response = reader.connection.query(obd.commands.DISTANCE_SINCE_DTC_CLEAR)
            if not dist_response.is_null():
                # This gives km, convert to miles
                odometer = int(dist_response.value.magnitude * 0.621371)
                print(f"[OBD] Distance since DTC clear: {odometer} mi", flush=True)
        except:
            pass

        return {
            "connected": True,
            "rpm": rpm,
            "speed": speed,
            "coolant_temp": coolant_temp,
            "fuel_level": fuel_level,
            "odometer": odometer
        }
    except Exception as e:
        print(f"[OBD] Error reading live data: {e}", flush=True)
        return {
            "connected": False,
            "rpm": None,
            "speed": None,
            "coolant_temp": None,
            "fuel_level": None,
            "odometer": None
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
    color: Optional[str] = None


@app.post("/trims")
async def get_trims(request: TrimRequest):
    """Get available trims for a vehicle from CarsXE API."""
    trims = await get_available_trims(request.year, request.make, request.model)
    return {"trims": trims}


@app.post("/vehicle-image")
async def vehicle_image(request: ImageRequest):
    """Get a vehicle image from CarsXE API."""
    print(f"[Image API] Request: {request.year} {request.make} {request.model} trim='{request.trim}' color='{request.color or 'none'}'")
    image_data = await get_vehicle_image(request.year, request.make, request.model, request.trim or "", request.color)
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

    Supports three modes:
    1. Client-provided OBD data (from phone's Bluetooth connection)
    2. Server-side live OBD reading
    3. Demo mode with mock data
    """

    scenario_vehicle = None

    # Deterministic synthetic fixture. Development and regression only — the
    # snapshot carries is_mock=True and fixture_name, so it can never be
    # research-logged or mistaken for a capture.
    if request.scenario:
        fixture = fixtures.get_scenario(request.scenario)
        if not fixture:
            return {
                "error": f"Unknown scenario '{request.scenario}'",
                "available": [s["name"] for s in fixtures.list_scenarios()],
            }
        snapshot = fixture["snapshot"]
        scenario_vehicle = fixture["vehicle"]
        obd_source = f"Synthetic fixture: {fixture['name']}"
        print(f"[Fixture] {fixture['name']} — {len(snapshot.dtc_codes)} codes", flush=True)

    # Check if client provided OBD data (from phone's Bluetooth)
    elif request.client_codes is not None:
        print(f"[OBD] Using client-provided data: {len(request.client_codes)} codes", flush=True)

        def _models(raw, cls):
            out = []
            for item in (raw or []):
                try:
                    out.append(cls(**item))
                except Exception as exc:
                    print(f"[OBD] discarding malformed {cls.__name__}: {exc}")
            return out

        # A real OBDSnapshot rather than an ad-hoc shim, so the v2 fields and
        # the trims_at()/freeze_frame_for() helpers work on the live path too.
        snapshot = OBDSnapshot(
            dtc_codes=[DTCCode(code=c, description="") for c in request.client_codes],
            pending_codes=[DTCCode(code=c, description="", status="pending")
                           for c in (request.client_pending_codes or [])],
            permanent_codes=[DTCCode(code=c, description="", status="permanent")
                             for c in (request.client_permanent_codes or [])],
            rpm=request.client_rpm,
            speed_mph=request.client_speed,
            coolant_temp_f=request.client_coolant_temp,
            engine_load_pct=request.client_engine_load_pct,
            intake_air_temp_f=request.client_intake_air_temp,
            fuel_trims=_models(request.client_fuel_trims, FuelTrim),
            freeze_frames=_models(request.client_freeze_frames, FreezeFrame),
            mode06=_models(request.client_mode06, Mode06Test),
            mileage=request.client_mileage,
            capability=(CapabilityProfile(**request.client_capability)
                        if request.client_capability else CapabilityProfile()),
            is_mock=False,
        )
        obd_source = request.obd_source or "Bluetooth (iOS)"
    elif request.use_live_obd:
        # Server-side OBD reading
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
    
    # A fixture supplies its own vehicle profile, so a scenario run is fully
    # offline and reproducible — it never depends on a live vehicle API.
    if scenario_vehicle is not None:
        vehicle_data = scenario_vehicle
        trim = request.trim or fixtures.get_scenario(request.scenario)["trim"]
        print(f"[Interpret] Fixture vehicle: {vehicle_data.get('full_name')}", flush=True)
    else:
        print(f"[Interpret] Looking up vehicle_id: '{request.vehicle_id}'", flush=True)
        vehicle_data = await get_vehicle_by_id(request.vehicle_id)
        trim = request.trim or ""

    # Mileage is user-entered; an explicit request value wins over a fixture's.
    if request.client_mileage is not None:
        snapshot.mileage = request.client_mileage

    if vehicle_data:
        print(f"[Interpret] Found vehicle_data: {vehicle_data.get('full_name', 'unknown')} turbo={vehicle_data.get('turbocharged')} super={vehicle_data.get('supercharged')}", flush=True)
    else:
        print(f"[Interpret] WARNING: No vehicle_data found for '{request.vehicle_id}'", flush=True)

    # Build engine profile for cost estimation and context
    engine_profile = build_engine_profile(vehicle_data)
    
    vehicle_str = format_vehicle_string(vehicle_data, include_engine=False) if vehicle_data else "Unknown Vehicle"
    if trim:
        vehicle_str_with_trim = f"{vehicle_str} {trim}"
    else:
        vehicle_str_with_trim = vehicle_str
    
    # Build comprehensive vehicle context
    vehicle_context = build_comprehensive_vehicle_context(vehicle_data, trim)
    
    # Fetch vehicle image - pass color if provided for better matching
    vehicle_image_url = None
    selected_color = request.color
    if vehicle_data:
        year = vehicle_data.get("year", "")
        make = vehicle_data.get("make", "")
        model = vehicle_data.get("model", "")
        image_data = await get_vehicle_image(year, make, model, trim, color=selected_color)
        if image_data and image_data.get("url"):
            # Return proxied URL to avoid CORS issues
            original_url = image_data.get("url", "")
            vehicle_image_url = f"/image-proxy?url={urllib.parse.quote(original_url, safe='')}"
            print(f"[Interpret] Vehicle image URL: {vehicle_image_url[:60]}... (color={selected_color or 'none'})")

    # Initialize response - apply formatters to clean up raw API data
    raw_engine = vehicle_data.get("engine", "") if vehicle_data else ""
    # Use user-selected transmission if provided, otherwise fall back to vehicle data
    raw_trans = request.transmission if request.transmission else (vehicle_data.get("transmission", "") if vehicle_data else "")
    raw_drive = vehicle_data.get("drive", "") if vehicle_data else ""

    # Debug: show raw vs formatted
    formatted_engine = format_engine_string(raw_engine) if raw_engine else ""
    formatted_trans = format_transmission_string(raw_trans) if raw_trans else ""
    print(f"[Interpret] Transmission: request.transmission='{request.transmission}', using raw_trans='{raw_trans}'")
    if raw_engine != formatted_engine:
        print(f"[Interpret] Engine formatted: '{raw_engine}' -> '{formatted_engine}'")
    if raw_trans != formatted_trans:
        print(f"[Interpret] Trans formatted: '{raw_trans}' -> '{formatted_trans}'")

    # Debug turbo/supercharged detection
    engine_turbo = engine_profile.get("is_turbocharged", False)
    vehicle_turbo = vehicle_data.get("turbocharged", False) if vehicle_data else False
    engine_super = engine_profile.get("is_supercharged", False)
    vehicle_super = vehicle_data.get("supercharged", False) if vehicle_data else False
    print(f"[Interpret] Turbo check: engine_profile={engine_turbo}, vehicle_data={vehicle_turbo}")
    print(f"[Interpret] Super check: engine_profile={engine_super}, vehicle_data={vehicle_super}")
    print(f"[Interpret] MPG data: city={vehicle_data.get('mpg_city', '')} hwy={vehicle_data.get('mpg_highway', '')} combined={vehicle_data.get('mpg_combined', '')} tank={vehicle_data.get('tank_capacity', '')}" if vehicle_data else "[Interpret] No vehicle_data")

    response_data = {
        "codes": [],
        "vehicle": vehicle_str_with_trim,
        "engine": format_engine_string(raw_engine) if raw_engine else "",
        "fuel_type": vehicle_data.get("fuel_type", "") if vehicle_data else "",
        "drive": format_drive_string(raw_drive) if raw_drive else "",
        "transmission": format_transmission_string(raw_trans) if raw_trans else "",
        "supercharged": engine_profile.get("is_supercharged", False) or (vehicle_data.get("supercharged", False) if vehicle_data else False),
        "turbocharged": engine_profile.get("is_turbocharged", False) or (vehicle_data.get("turbocharged", False) if vehicle_data else False),
        "hybrid": engine_profile.get("is_hybrid", False),
        "electric": engine_profile.get("is_electric", False),
        "performance_tier": engine_profile.get("performance_tier", "standard"),
        "mpg_city": vehicle_data.get("mpg_city", "") if vehicle_data else "",
        "mpg_highway": vehicle_data.get("mpg_highway", "") if vehicle_data else "",
        "mpg_combined": vehicle_data.get("mpg_combined", "") if vehicle_data else "",
        "tank_capacity": vehicle_data.get("tank_capacity", "") if vehicle_data else "",
        "horsepower": vehicle_data.get("horsepower", "") if vehicle_data else "",
        # A measurement we do not have is null, never a plausible-looking
        # substitute. `is not None` (not truthiness) is load-bearing: 0 RPM is
        # a real reading meaning the engine is not running, and the previous
        # `if snapshot.rpm else 750` rendered it as a warm idle. Likewise 0 F
        # coolant became 205 F. Clients already treat these as optional —
        # APIClient.swift:915-917 declares Int?, index.html:1901-1916 null-checks.
        "rpm": int(snapshot.rpm) if snapshot.rpm is not None else None,
        "speed": int(snapshot.speed_mph) if snapshot.speed_mph is not None else None,
        "coolant_temp": int(snapshot.coolant_temp_f) if snapshot.coolant_temp_f is not None else None,
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
        "trim": trim,
        "vehicleImageURL": vehicle_image_url,
        # --- v2 additions. Purely additive keys: Swift's Codable and the PWA
        # both ignore unknown fields, so no existing client is affected. These
        # are the fields the eventual JSON output contract will formalise.
        "mileage": snapshot.mileage,
        "pending_codes": [c.code for c in snapshot.pending_codes],
        "permanent_codes": [c.code for c in snapshot.permanent_codes],
        "capability_limitations": list(snapshot.capability.limitations),
        "code_definitions": [],
        "differential": [],
        "not_assessed": [],
        "is_synthetic": bool(getattr(snapshot, "fixture_name", None)),
    }

    if vehicle_data and scenario_vehicle is None:
        response_data["data_sources"].append("CarsXE")
    
    # No codes detected
    if not snapshot.dtc_codes:
        response_data["dont_panic"] = "No trouble codes detected. Your vehicle appears to be running fine."
        # The verdict is computed on this path too. Without this a clean scan
        # returned the hardcoded SAFE default and no `safety` field — found by
        # the Brief 1c smoke runner, not by the unit suite.
        apply_safety(response_data, diagnostics.compute_safety(
            diagnostics.analyze(snapshot, vehicle_data), snapshot, vehicle_data))

        if vehicle_data:
            # The no-codes path retrieves too, otherwise its KNOWN ISSUES section
            # can only ever report that nothing was found.
            try:
                clean_retrieval, clean_sources = await build_retrieval_block(
                    vehicle_data.get("make", ""), vehicle_data.get("model", ""),
                    vehicle_data.get("year", ""), [], mileage=snapshot.mileage)
            except Exception as exc:
                print(f"[Retrieval] no-codes retrieval failed: {exc}", flush=True)
                clean_retrieval, clean_sources = (
                    '<retrieved_context source="none">\nNONE\n</retrieved_context>', [])
            for s in clean_sources:
                if s not in response_data["data_sources"]:
                    response_data["data_sources"].append(s)

            prompt = f"""You are a friendly vehicle assistant helping a car owner.

The owner scanned their vehicle and NO trouble codes were found.

SOURCING RULE: you reason over the evidence in this prompt. Never supply a fact
about this vehicle from your own knowledge. If the retrieved block says NONE,
you do not know of any issues for this car, and you say so.

{vehicle_context}

[RETRIEVED INFORMATION ABOUT THIS VEHICLE]
{clean_retrieval}

Respond in this EXACT format:

SUMMARY:
Write 3-4 sentences that:
1. Confirms no codes were found - their car's computer isn't reporting any problems
2. Give ONE general maintenance tip that follows from this engine's configuration
   (turbocharged, supercharged, V8, AWD) — a characteristic listed above, not a
   model-specific claim
3. Be encouraging but practical

SERVICE RECOMMENDATIONS:
Oil specifications and intervals are vehicle-specific facts requiring a source, and
we hold no verified maintenance table. Do NOT state an oil weight, specification
code, or mileage interval. Write exactly this: The correct oil specification and
service interval for this engine are in the owner's manual or on the oil filler cap.
We do not yet hold a verified maintenance record for this vehicle.

KNOWN ISSUES:
Use ONLY sourced material provided above in this prompt. Do not add known issues,
recalls, technical service bulletins, or failure patterns from your own knowledge —
not even ones you are confident about.
If no sourced material about this vehicle was provided above, write exactly this sentence
and nothing else: No verified issue history was available for this vehicle.

RULES:
- Use simple language
- Be specific to THIS exact vehicle
- NO analogies or metaphors
- English only"""

            ai_response = await ask_ollama(prompt)
            if not ai_response.startswith("ERROR:"):
                # Parse the response for summary, service recommendations, and known issues
                lines = ai_response.split('\n')
                summary_lines = []
                service_lines = []
                known_issues_lines = []
                current_section = None

                for line in lines:
                    line_upper = line.strip().upper()
                    if line_upper.startswith("SUMMARY"):
                        current_section = "summary"
                    elif line_upper.startswith("SERVICE"):
                        current_section = "service"
                    elif line_upper.startswith("KNOWN"):
                        current_section = "known_issues"
                    elif current_section == "summary":
                        summary_lines.append(line)
                    elif current_section == "service":
                        service_lines.append(line)
                    elif current_section == "known_issues":
                        known_issues_lines.append(line)

                if summary_lines:
                    response_data["dont_panic"] = '\n'.join(summary_lines).strip()
                else:
                    response_data["dont_panic"] = ai_response

                if service_lines:
                    response_data["service_recommendations"] = '\n'.join(service_lines).strip()

                if known_issues_lines:
                    response_data["known_issues"] = '\n'.join(known_issues_lines).strip()

            # --- Logging, mirroring the coded path -------------------------
            # Without this a clean scan left no server-side record at all,
            # which made the real-car arm of a replay comparison unrecordable.
            scan_id = log_scan("", response_data["safety_level"], ai_response)
            response_data["scan_id"] = scan_id
            if getattr(snapshot, "is_mock", False):
                print("[Research] Skipping research log — mock/demo snapshot", flush=True)
            else:
                log_research_scan(
                    model_version="gemma4-e4b-base",
                    vehicle_id=request.vehicle_id,
                    trim=trim,
                    vehicle_profile=vehicle_data,
                    codes=[],
                    rpm=int(snapshot.rpm) if snapshot.rpm is not None else None,
                    speed_mph=int(snapshot.speed_mph) if snapshot.speed_mph is not None else None,
                    coolant_temp_f=int(snapshot.coolant_temp_f) if snapshot.coolant_temp_f is not None else None,
                    obd_source=obd_source,
                    prompt_text=prompt,
                    response_text=ai_response,
                    response_parsed={
                        "safety_level": response_data["safety_level"],
                        "dont_panic": response_data["dont_panic"],
                        "service_recommendations": response_data.get("service_recommendations", ""),
                        "known_issues": response_data.get("known_issues", ""),
                    },
                    safety_level=response_data["safety_level"],
                    had_error=ai_response.startswith("ERROR:"),
                    data_sources=response_data.get("data_sources"),
                )

        return response_data
    
    # Process codes
    codes_list = [c.code for c in snapshot.dtc_codes]
    response_data["codes"] = codes_list

    # Code semantics now come from dtc_definitions, which reports a trust tier
    # per code and refuses to guess at manufacturer-specific meanings. CarsXE is
    # no longer the source for what a code MEANS — ml/CLAUDE.md records it as
    # known-wrong for P0420 — but the call is kept for source bookkeeping on the
    # live path. Fixtures skip it entirely so a scenario stays offline.
    obd_decoded = {} if request.scenario else await decode_obd_codes_batch(codes_list)

    resolved_defs = dtc_definitions.resolve_all(codes_list)
    response_data["code_definitions"] = resolved_defs
    codes_text = dtc_definitions.format_for_prompt(resolved_defs)
    if any(r["tier"] == dtc_definitions.TIER_STRUCTURAL for r in resolved_defs):
        response_data["data_sources"].append("SAE J2012 code structure")

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
    
    make = vehicle_data.get("make", "") if vehicle_data else ""
    model = vehicle_data.get("model", "") if vehicle_data else ""
    year = vehicle_data.get("year", "") if vehicle_data else ""
    engine_str = response_data.get("engine", "")

    # Scraped code context — OFF by default, see ENABLE_SCRAPED_CODE_CONTEXT.
    # Note this also truncates to the first 2 codes; the replacement retrieval
    # path must either cover every code or record that it truncated.
    code_context = ""
    if ENABLE_SCRAPED_CODE_CONTEXT:
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

    # --- Deterministic analysis, before the model sees anything --------------
    # Every arithmetic and comparative step happens here, in Python, where it is
    # testable. Rules abstain with a stated reason rather than guess, and the
    # abstentions are carried into the prompt so the model reports what could
    # not be seen instead of quietly filling the gap.
    analysis = diagnostics.analyze(snapshot, vehicle_data, engine_profile)
    response_data["differential"] = [
        {
            "rule": f.rule_id, "conclusion": f.conclusion, "confidence": f.confidence,
            "basis": f.basis, "next_checks": list(f.next_checks),
            "evidence": [{"pointer": e.pointer, "restatement": e.restatement} for e in f.evidence],
        }
        for f in analysis.causes
    ]
    # Status findings (pending/permanent codes) are facts about the codes, not
    # causes of the fault, and are carried separately so no client renders them
    # as a diagnosis.
    response_data["code_status"] = [
        {"rule": f.rule_id, "conclusion": f.conclusion} for f in analysis.statuses
    ]
    response_data["recommended_checks"] = analysis.all_checks()
    response_data["not_assessed"] = [
        {"rule": a.rule_id, "reason": a.reason, "missing": list(a.missing)}
        for a in analysis.abstentions
    ]
    print(f"[Diagnostics] {len(analysis.findings)} findings, "
          f"{len(analysis.abstentions)} abstentions", flush=True)

    # --- Safety verdict: computed here, restated by the model -----------------
    # A pure function of the rule output and the payload. The model is told the
    # verdict and explains its reasons; it never assigns or adjusts severity.
    safety = diagnostics.compute_safety(analysis, snapshot, vehicle_data)
    safety_label = apply_safety(response_data, safety)
    safety_block = "\n".join(
        [f"VERDICT: {diagnostics.verdict_display(safety.verdict)}  "
         f"(label to write under SAFETY LEVEL: {safety_label}; basis: {safety.basis})"]
        + [f"  - {r.statement}" + "".join(f"\n      evidence [{e.pointer}]: {e.restatement}"
                                          for e in r.evidence)
           for r in safety.reasons]
    )
    print(f"[Safety] {safety.verdict} ({safety_label}), "
          f"{sum(1 for r in safety.reasons if r.raises_to)} escalations", flush=True)

    # --- Retrieval: vehicle facts come from a source, never from weights ------
    # Degrades the answer on failure; never fails the request.
    try:
        retrieval_block, retrieval_sources = await build_retrieval_block(
            make, model, year, codes_list, engine_str, snapshot.mileage)
    except Exception as exc:
        print(f"[Retrieval] block build failed, continuing without: {exc}", flush=True)
        retrieval_block, retrieval_sources = (
            '<retrieved_context source="none">\nNONE — retrieval was unavailable '
            'for this scan.\n</retrieved_context>', [])
    for s in retrieval_sources:
        if s not in response_data["data_sources"]:
            response_data["data_sources"].append(s)

    capability_block = "\n".join(
        f"- {lim}" for lim in snapshot.capability.limitations) or "None recorded."

    measured_block = "\n".join(
        f"- {label}: {value}"
        for label, value in (
            ("engine speed (RPM)", response_data["rpm"]),
            ("vehicle speed (mph)", response_data["speed"]),
            ("coolant temperature (F)", response_data["coolant_temp"]),
            ("engine load (%)", snapshot.engine_load_pct),
            ("intake air temperature (F)", snapshot.intake_air_temp_f),
            ("mileage", snapshot.mileage),
        )
    ).replace(": None", ": unavailable")

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

SOURCING RULE — this governs everything below.
You reason over the evidence in this prompt. You do not supply facts about this
vehicle from your own knowledge. Every claim about what fails on this car, what
is recalled, or what other owners experience must come from the RETRIEVED
INFORMATION block. If that block says NONE, then you do not know of any, and you
say so. A confident wrong answer is worse for this driver than a general one.
The differential below was computed from this vehicle's own measurements before
you were called. Explain it. Do not replace it, reorder it, or add causes to it.
Never restate a number that does not appear in this prompt.

[VEHICLE INFO]
{vehicle_context}

Vehicle specifics:
- Exact vehicle: {vehicle_str_with_trim}
- Engine type: {response_data.get('engine', 'Unknown')} ({engine_profile.get('engine_layout', 'standard')})
- Aspiration: {'Supercharged' if engine_profile.get('is_supercharged') else 'Turbocharged' if engine_profile.get('is_turbocharged') else 'Naturally Aspirated'}
- Drivetrain: {response_data.get('drive', 'Unknown')}
- Transmission: {response_data.get('transmission', 'Unknown')}
- Performance tier: {engine_profile.get('performance_tier', 'standard')}

[TROUBLE CODES AND HOW WELL WE KNOW THEM]
{codes_text}

Where a code's definition confidence is `structural_only`, its exact meaning is
set by the manufacturer and we have not verified it. Say that plainly rather
than guessing what it means.

[MEASURED FROM THIS VEHICLE]
{measured_block}

[WHAT THIS VEHICLE COULD NOT REPORT]
{capability_block}

[COMPUTED DIAGNOSIS — already worked out; your job is to explain it]
{analysis.to_prompt_block()}

[RETRIEVED INFORMATION ABOUT THIS VEHICLE]
{retrieval_block}

[SAFETY VERDICT — already computed from this vehicle's measurements; you do not assign it]
{safety_block}

The safety level has been decided by the checks above. Write the label given
there verbatim under SAFETY LEVEL. Do not raise it, lower it, or pick your own.
Explain the reasons listed, in plain words, wherever urgency comes up. Your
"WHEN TO SEE A MECHANIC" advice must match this verdict: SAFE means it can wait
weeks; CAUTION means schedule service within 1-2 weeks and driving short trips is
fine; STOP means do not drive except straight to a mechanic, or have it towed;
UNKNOWN means the scan could not measure enough to judge — say that, and do not
guess a level.

[YOUR RESPONSE - START HERE]

"""

    if code_context:
        # Only reachable with ENABLE_SCRAPED_CODE_CONTEXT=1, which must stay off
        # for any run producing published numbers. The old header for this block
        # contained the words "CAR DATABASES", which the section parser used to
        # match as a header — the phrasing is deliberately different now.
        prompt += f"""[UNVERIFIED SCRAPED MATERIAL — lower trust than the retrieved block above]

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

SAFETY LEVEL: {safety_label}
(Write exactly that word. It was computed above and is not yours to change.)

WHAT'S HAPPENING:
Start with "Your {vehicle_str_with_trim} is showing code {codes_list[0]}."
Explain in 4-5 simple sentences that anyone can understand:
- What this code actually means (imagine explaining to someone who knows nothing about cars)
- What this vehicle's own readings showed, quoting the evidence lines from the
  computed diagnosis above — this is the part a general web search cannot give them
- If something could not be measured, say so in one sentence
- Reassure them if it's not serious, or be honest if it is

LIKELY CAUSES:
This section lists CAUSES ONLY. Items under "COULD NOT BE ASSESSED" are not causes
and must never be numbered here — they belong in WHAT'S HAPPENING as things that
could not be checked.
If the DIFFERENTIAL section above has entries: restate them in order, one numbered
item each. For every item say what the part does in plain words, then give the
measurement that points at it, using the evidence line already provided. Add no
causes of your own and do not reorder them.
If the DIFFERENTIAL section is empty or absent: write only this single sentence and
nothing else, with no numbered list at all — The available evidence does not narrow
this down to a specific cause.

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
Use the RECOMMENDED CHECKS list above. It is already de-duplicated: reproduce it in
order, each item exactly once, never repeating one. Rewrite each as a step a driver
could follow, and where a check needs equipment they will not have, say who should
do it instead. Add nothing that is not in that list.

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

SERVICE RECOMMENDATIONS:
Oil specifications and service intervals are vehicle-specific facts that must come
from a source. We do not currently hold a verified maintenance table, so do NOT
state an oil weight, a specification code, or an interval in miles — those would be
recalled from memory and may be wrong for this engine.
Write exactly this instead: The correct oil specification and service interval for
this engine are in the owner's manual or on the oil filler cap. We do not yet hold
a verified maintenance record for this vehicle.
Then, if and only if the retrieved block above contains maintenance information,
add what it says and name the source.

KNOWN ISSUES FOR THIS ENGINE:
Use ONLY sourced material provided above in this prompt. Do not add known issues,
recalls, technical service bulletins, or failure patterns from your own knowledge —
not even ones you are confident about.
If no sourced material about this vehicle was provided above, write exactly this sentence
and nothing else: No verified issue history was available for this vehicle.
"""

    # OTHER OWNERS REPORT is now fed by NHTSA complaint retrieval rather than by
    # the deleted Reddit scraper, so the section survives with real provenance.
    prompt += """

OTHER OWNERS REPORT:
Summarise ONLY what the retrieved information block above reports from other
owners of this vehicle, and name which source it came from.
If that block says NONE, write exactly this sentence and nothing else:
No owner-reported history was retrieved for this vehicle."""

    # The prompt used to end with "[END OF RESPONSE FORMAT]", which the model
    # mirrored back as "[End of Report]" along with a preamble and a disclaimer
    # of its own. The final instruction is now imperative and names the exact
    # first line to emit, because for a model this size the last thing in the
    # prompt carries disproportionate weight.
    prompt += f"""

Now write the response.
Write each of these headers once, in this order, each followed by its content:
SAFETY LEVEL, WHAT'S HAPPENING, LIKELY CAUSES, WHAT YOU MIGHT NOTICE,
IF YOU IGNORE THIS, QUICK CHECKS, DIY FIX, WHEN TO SEE A MECHANIC,
ESTIMATED REPAIR COST, SERVICE RECOMMENDATIONS, KNOWN ISSUES FOR THIS ENGINE,
OTHER OWNERS REPORT.
Write each header exactly once and never repeat a header. No preamble, no
disclaimer, no closing note, no headers of your own invention. Begin now with
SAFETY LEVEL."""

    # Get AI response
    ai_response = await ask_ollama(prompt)
    
    if ai_response.startswith("ERROR:"):
        # The computed verdict already sits in response_data; a model failure
        # loses the narration, not the safety level.
        response_data["dont_panic"] = ai_response
        return response_data

    # Parse response
    parsed = parse_guidance(ai_response)

    # The safety fields were set from compute_safety before the model ran and
    # are not overwritten from prose. A mismatch is logged as model
    # non-adherence, which the format-adherence metric should see.
    if parsed["safety_level"] != safety_label:
        print(f"[Safety] model wrote {parsed['safety_level']!r}, computed {safety_label!r} "
              "— computed verdict kept", flush=True)
    parsed["safety_level"] = safety_label

    response_data["dont_panic"] = parsed["dont_panic"]
    response_data["likely_causes"] = parsed["likely_causes"]
    response_data["symptoms"] = parsed["symptoms"]
    response_data["if_ignored"] = parsed["if_ignored"]
    response_data["quick_checks"] = parsed["quick_checks"]
    response_data["diy_fix"] = parsed["diy_fix"]
    response_data["urgency"] = parsed["urgency"]
    response_data["repair_cost"] = parsed["repair_cost"]
    response_data["service_recommendations"] = parsed["service_recommendations"]
    response_data["known_issues"] = parsed["known_issues"]
    response_data["owner_reports"] = parsed["owner_reports"]
    
    # Log scan and return scan_id for followup/feedback linking
    scan_id = log_scan(", ".join(codes_list), safety_label, ai_response)
    response_data["scan_id"] = scan_id

    # Research logging — additive, parallel to log_scan above.
    # Captures the full prompt, response, vehicle context, and OBD data
    # so scans can later be used as training examples and/or replayed
    # for A/B comparison between model variants.
    #
    # This call has its own internal try/except — if the DB write fails
    # for any reason, the user still gets their diagnosis. See the
    # log_research_scan() docstring in database.py.
    #
    # TODO (when consent + A/B shipping):
    #   - Replace model_version literal with a value derived from the
    #     active LLM client (currently ollama_client serving Gemma 4 E4B).
    #   - Pass real user_id_hash from the request once iOS sends one.
    #   - Pass ab_bucket once the assignment logic exists.
    #   - Pass consent_version once the onboarding screen ships.
    #
    # Mock scans never enter the research record. get_mock_snapshot() picks a
    # RANDOM scenario, so a demo row is a randomly generated DTC paired with
    # whatever vehicle happened to be selected — an artifact of the demo path,
    # not an observation. Gating on is_mock rather than on the obd_source
    # string matters: obd_source has two distinct demo spellings and its
    # client-provided value is unvalidated, so it cannot carry this decision.
    if getattr(snapshot, "is_mock", False):
        print("[Research] Skipping research log — mock/demo snapshot", flush=True)
    else:
        log_research_scan(
            model_version="gemma4-e4b-base",
            vehicle_id=request.vehicle_id,
            trim=trim,
            vehicle_profile=vehicle_data,
            codes=codes_list,
            # Straight off the snapshot, not out of response_data. These must
            # stay NULL when the vehicle did not report them — a substituted
            # value is indistinguishable from a measurement once it is a row.
            rpm=int(snapshot.rpm) if snapshot.rpm is not None else None,
            speed_mph=int(snapshot.speed_mph) if snapshot.speed_mph is not None else None,
            coolant_temp_f=int(snapshot.coolant_temp_f) if snapshot.coolant_temp_f is not None else None,
            obd_source=obd_source,
            prompt_text=prompt,
            response_text=ai_response,
            response_parsed=parsed,
            safety_level=safety_label,
            had_error=False,
            data_sources=response_data.get("data_sources"),
        )

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
You are ClearDrive, a helpful car diagnostic assistant that uses the SOCRATIC METHOD to help vehicle owners truly understand their car.

RULES:
- ALWAYS end your response with 1-2 thoughtful follow-up questions that guide the user to better understand their vehicle's issue
- Ask questions that help the user provide useful information (e.g., "Have you noticed any unusual smells when this happens?" or "When did you first notice this - was it after a cold start?")
- Help them learn WHY something matters, not just WHAT to do
- If asked HOW to do something: give numbered step-by-step instructions, then ask if they have the tools and comfort level to attempt it
- If asked for videos/links: say "I can't provide links, but here's what to search for: [specific search terms]"
- If asked about a part: explain what it does and where it's located on this specific vehicle, then ask if they've inspected it
- If asked about cost: factor in the performance tier (high-performance parts cost more!), then ask about their preference (dealer vs independent shop, OEM vs aftermarket parts)
- Be specific to this {powertrain} engine
- Use the horsepower, MSRP, and trim info to give accurate answers
- 3-5 sentences of answer, then 1-2 probing questions
- English only

CRITICAL - MATCH SAFETY LEVEL WITH DRIVING ADVICE:
The safety level is {safety}. Your driving advice MUST match this:
- SAFE = Can drive normally for weeks/months, no rush
- CAUTION = Safe to drive short distances, but schedule service within 1-2 weeks. DON'T say "don't drive" or "avoid driving" - they CAN drive!
- STOP = Should NOT drive at all (except to mechanic). Only say "don't drive" if safety level is STOP.
- UNKNOWN = The scan could not measure enough to judge. Say so; do not assign a level yourself.

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

    answer = response.strip()

    # Log followup for GEPA data collection
    if request.scan_id is not None:
        try:
            log_followup(
                scan_id=request.scan_id,
                question=request.question,
                answer=answer,
                is_human_generated=request.is_human_generated
            )
        except Exception as e:
            print(f"[Followup] Failed to log: {e}")

    return {"answer": answer}


@app.get("/history")
async def history():
    scans = get_recent_scans(10)
    return [
        {"timestamp": s[0], "codes": s[1], "safety": s[2], "guidance": s[3]}
        for s in scans
    ]


@app.post("/feedback")
async def submit_feedback(request: FeedbackRequest):
    """Log user feedback for a scan session."""
    if request.rating not in ("bad", "ok", "good"):
        return {"success": False, "error": "Invalid rating. Must be 'bad', 'ok', or 'good'."}

    feedback_id = log_feedback(request.scan_id, request.rating)
    return {"success": True, "feedback_id": feedback_id}


@app.get("/safety-definitions")
async def get_safety_definitions():
    """Return the safety level definitions for the frontend."""
    return SAFETY_DEFINITIONS


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
