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

app = FastAPI(title="ClearDrive", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()


class TrimRequest(BaseModel):
    year: str
    make: str
    model: str


class InterpretRequest(BaseModel):
    vehicle_id: str  # FuelEconomy.gov vehicle ID
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
    """Main diagnostic endpoint."""
    
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
    
    vehicle_str = format_vehicle_string(vehicle_data, include_engine=False) if vehicle_data else "Unknown Vehicle"
    
    # Initialize response
    response_data = {
        "codes": [],
        "vehicle": vehicle_str,
        "engine": vehicle_data.get("engine", "") if vehicle_data else "",
        "fuel_type": vehicle_data.get("fuel_type", "") if vehicle_data else "",
        "drive": vehicle_data.get("drive", "") if vehicle_data else "",
        "transmission": vehicle_data.get("transmission", "") if vehicle_data else "",
        "supercharged": vehicle_data.get("supercharged", False) if vehicle_data else False,
        "turbocharged": vehicle_data.get("turbocharged", False) if vehicle_data else False,
        "hybrid": False,
        "electric": False,
        "rpm": int(snapshot.rpm) if snapshot.rpm else 750,
        "speed": int(snapshot.speed_mph) if snapshot.speed_mph else 0,
        "coolant_temp": int(snapshot.coolant_temp_f) if snapshot.coolant_temp_f else 205,
        "safety_level": "SAFE",
        "dont_panic": "",
        "likely_causes": "",
        "symptoms": "",
        "if_ignored": "",
        "quick_checks": "",
        "urgency": "",
        "repair_cost": "",
        "owner_reports": "",
        "data_sources": [],
        "obd_source": obd_source
    }
    
    # Check for hybrid/electric
    if vehicle_data:
        fuel_type = vehicle_data.get("fuel_type", "").lower()
        if "electric" in fuel_type:
            response_data["electric"] = True
        if "hybrid" in fuel_type or vehicle_data.get("ev_motor"):
            response_data["hybrid"] = True
        
        response_data["data_sources"].append("FuelEconomy.gov")
    
    # No codes detected
    if not snapshot.dtc_codes:
        response_data["dont_panic"] = "No trouble codes detected. Your vehicle appears to be running fine."
        
        if vehicle_data:
            vehicle_context = format_vehicle_context(vehicle_data)
            
            prompt = f"""You are a vehicle diagnostic assistant. The owner of a {vehicle_str} scanned their vehicle and NO trouble codes were found.

Vehicle specs:
{vehicle_context}

Write a brief response (2-3 sentences):
1. Confirm no codes were found
2. One maintenance tip specific to their engine type

Be direct. No analogies. English only."""

            ai_response = await ask_ollama(prompt)
            if not ai_response.startswith("ERROR:"):
                response_data["dont_panic"] = ai_response
        
        return response_data
    
    # Process codes
    codes_text = ", ".join([f"{c.code}: {c.description}" for c in snapshot.dtc_codes])
    codes_list = [c.code for c in snapshot.dtc_codes]
    response_data["codes"] = codes_list
    
    print(f"\n[Main] Processing codes: {codes_list}")
    print(f"[Main] Vehicle: {vehicle_str}")
    print(f"[Main] Engine: {response_data.get('engine', 'Unknown')}")
    
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
    
    # Get Reddit data as fallback
    reddit_context = ""
    if make and model:
        for code in codes_list[:1]:
            reddit_data = await scrape_reddit_fallback(code, make, model, year)
            reddit_ctx = format_reddit_context(reddit_data)
            if reddit_ctx:
                reddit_context = reddit_ctx
                if "Community Forums" not in response_data["data_sources"]:
                    response_data["data_sources"].append("Community Forums")
    
    # Build vehicle context
    vehicle_context = format_vehicle_context(vehicle_data) if vehicle_data else ""
    engine_str = response_data.get("engine", "")
    
    # Build prompt
    prompt = f"""You are a vehicle diagnostic assistant. Be direct, technical, and concise.

CRITICAL FORMATTING RULES:
- Respond in English only
- Write OBD codes as single words: P0174, P0300, NOT P 0 1 7 4
- Never put line breaks inside codes
- Number lists starting from 1 (not 4 or any other number)
- Be direct and factual - NO analogies or metaphors

VEHICLE: {vehicle_str}
ENGINE: {engine_str or 'Not specified'}
{vehicle_context}

DIAGNOSTIC CODES: {codes_text}
"""

    if code_context:
        prompt += f"""
DIAGNOSTIC DATA:
{code_context}
"""

    prompt += f"""
Respond using this EXACT format:

SAFETY LEVEL: SAFE, CAUTION, or STOP

WHAT'S HAPPENING:
Start with "Your {vehicle_str}". Explain what code {codes_list[0]} means in 2-3 sentences. Be specific to the {engine_str or 'engine'}.

LIKELY CAUSES:
1. Most common cause (one sentence)
2. Second cause (one sentence)
3. Third cause (one sentence)

WHAT YOU MIGHT NOTICE:
1. First symptom
2. Second symptom
3. Third symptom

IF YOU IGNORE THIS:
One paragraph about consequences.

QUICK CHECKS:
1. First check a non-mechanic can do
2. Second check
3. Third check

WHEN TO SEE A MECHANIC:
One sentence with timeframe.

ESTIMATED REPAIR COST:
Cost range for this specific vehicle."""

    if reddit_context:
        prompt += f"""

OTHER OWNERS REPORT:
Based on this community data, write 2-3 sentences:
{reddit_context}"""

    # Get AI response
    ai_response = await ask_ollama(prompt)
    
    if ai_response.startswith("ERROR:"):
        response_data["safety_level"] = "UNKNOWN"
        response_data["dont_panic"] = ai_response
        return response_data
    
    # Parse response
    parsed = parse_guidance(ai_response)
    
    response_data["safety_level"] = parsed["safety_level"]
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
    """Handle follow-up questions."""
    
    vehicle = request.context.get("vehicle", "the vehicle")
    engine = request.context.get("engine", "")
    codes = request.context.get("codes", [])
    safety = request.context.get("safety_level", "UNKNOWN")
    summary = request.context.get("summary", "")
    causes = request.context.get("likely_causes", "")
    
    history_text = ""
    if request.history:
        history_text = "\n\nPrevious conversation:\n"
        for msg in request.history[-4:]:
            role = "Owner" if msg["role"] == "user" else "Assistant"
            history_text += f"{role}: {msg['content']}\n"
    
    prompt = f"""You are a vehicle diagnostic assistant.

CONTEXT:
- Vehicle: {vehicle}
- Engine: {engine or 'Not specified'}
- Codes: {', '.join(codes) if codes else 'None'}
- Safety: {safety}
- Diagnosis: {summary}
{history_text}

RULES:
- English only
- Short answers (2-4 sentences)
- Be specific to this vehicle/engine
- No analogies or metaphors

Question: {request.question}

Answer directly:"""

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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)