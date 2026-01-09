"""
Vehicle Data Lookup
Uses FuelEconomy.gov for specs + Ollama for trim identification.
"""

import httpx
import json
import re
from pathlib import Path
from datetime import datetime

CACHE_FILE = Path(__file__).parent / "vehicle_cache.json"
FUELECONOMY_URL = "https://www.fueleconomy.gov/ws/rest"
OLLAMA_URL = "http://localhost:11434/api/generate"

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "ClearDrive/1.0"
}


def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {"vehicles": {}, "trims": {}, "last_updated": None}


def save_cache(data: dict):
    data["last_updated"] = datetime.now().isoformat()
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)


async def identify_trims_with_ollama(year: str, make: str, model: str, specs_list: list) -> dict:
    """Ask Ollama to identify trim names for each spec configuration."""
    
    if not specs_list:
        return {}
    
    # Clean up specs for better identification
    cleaned_specs = []
    for s in specs_list:
        clean = s
        clean = re.sub(r'Auto \d+-spd,?\s*', '', clean)
        clean = re.sub(r'Man \d+-spd,?\s*', '', clean)
        clean = re.sub(r',?\s*FFV', '', clean)
        clean = clean.strip().strip(',').strip()
        cleaned_specs.append(clean)
    
    specs_text = "\n".join([f"{i+1}. {year} {make} {model} with {cleaned_specs[i]}" for i in range(len(cleaned_specs))])
    
    prompt = f"""What is the trim level name for each of these vehicles?

{specs_text}

Reply with ONLY a numbered list of trim names. One trim per line. No explanations."""

    try:
        print(f"[VehicleData] Asking Ollama to identify {len(specs_list)} trims...")
        
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                OLLAMA_URL,
                json={
                    "model": "llama3:8b",
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,
                        "num_predict": 300
                    }
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                text = data.get("response", "").strip()
                
                print(f"[VehicleData] Ollama response:\n{text}\n")
                
                results = {}
                lines = text.split('\n')
                
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    
                    match = re.match(r'^(\d+)[.\:\)\-]\s*(.+)$', line)
                    if match:
                        idx = int(match.group(1)) - 1
                        trim = match.group(2).strip().strip('"\'.,')
                        
                        # Clean up
                        trim = trim.split(' - ')[0].split(' (')[0].strip()
                        trim = re.sub(r'\s*(AWD|RWD|4WD|FWD)\s*$', '', trim, flags=re.IGNORECASE).strip()
                        
                        if 0 <= idx < len(specs_list) and len(trim) < 40 and trim:
                            results[specs_list[idx]] = trim
                            print(f"[VehicleData] Mapped: {specs_list[idx]} -> {trim}")
                
                return results
                    
    except Exception as e:
        print(f"[VehicleData] Ollama error: {e}")
    
    return {}


async def get_models(year: str, make: str) -> list:
    """Get all models for a year/make from FuelEconomy.gov."""
    try:
        url = f"{FUELECONOMY_URL}/vehicle/menu/model"
        params = {"year": year, "make": make}
        
        async with httpx.AsyncClient(headers=HEADERS, timeout=15) as client:
            response = await client.get(url, params=params)
            
            if response.status_code != 200:
                return []
            
            data = response.json()
            if not data:
                return []
            
            items = data.get("menuItem", [])
            if isinstance(items, dict):
                items = [items]
            
            return [item.get("value", "") for item in items if item]
            
    except Exception as e:
        print(f"[VehicleData] Error fetching models: {e}")
        return []


async def find_matching_models(year: str, make: str, model: str) -> list:
    """Find all model variants that match user input."""
    models = await get_models(year, make)
    
    if not models:
        return []
    
    model_lower = model.lower().strip()
    
    matches = []
    for m in models:
        m_lower = m.lower()
        if m_lower.startswith(model_lower) or model_lower in m_lower:
            matches.append(m)
    
    return matches


async def get_vehicle_options(year: str, make: str, model: str) -> list:
    """Get all trim/engine options for a specific model variant."""
    try:
        url = f"{FUELECONOMY_URL}/vehicle/menu/options"
        params = {"year": year, "make": make, "model": model}
        
        async with httpx.AsyncClient(headers=HEADERS, timeout=15) as client:
            response = await client.get(url, params=params)
            
            if response.status_code != 200:
                return []
            
            data = response.json()
            if not data:
                return []
            
            options = data.get("menuItem", [])
            if options is None:
                return []
            if isinstance(options, dict):
                options = [options]
            
            return options
            
    except Exception as e:
        print(f"[VehicleData] Error fetching options: {e}")
        return []


def extract_specs(full_name: str, year: str, make: str, model_variant: str) -> str:
    """Extract specs from full name."""
    specs = full_name
    specs = specs.replace(year, "", 1).strip()
    specs = re.sub(re.escape(make), "", specs, count=1, flags=re.IGNORECASE).strip()
    specs = re.sub(re.escape(model_variant), "", specs, count=1, flags=re.IGNORECASE).strip()
    specs = " ".join(specs.split())
    return specs


def get_drivetrain_from_variant(variant: str, model: str) -> str:
    """Extract drivetrain from variant name."""
    suffix = re.sub(r'^' + re.escape(model) + r'\s*', "", variant, flags=re.IGNORECASE).strip().lower()
    
    if "awd" in suffix:
        return "AWD"
    elif "4wd" in suffix:
        return "4WD"
    elif "fwd" in suffix:
        return "FWD"
    elif "rwd" in suffix:
        return "RWD"
    
    return ""


def get_trim_from_variant(variant: str, model: str) -> str:
    """Extract actual trim name from variant."""
    suffix = re.sub(r'^' + re.escape(model) + r'\s*', "", variant, flags=re.IGNORECASE).strip()
    suffix = re.sub(r'\b(AWD|4WD|FWD|RWD|2WD)\b', '', suffix, flags=re.IGNORECASE).strip()
    return suffix


async def get_available_trims(year: str, make: str, model: str) -> list:
    """Get available trims for a vehicle."""
    cache = load_cache()
    cache_key = f"trims_{year}_{make}_{model}".lower().replace(" ", "_")
    
    # Check cache (7 days)
    if cache_key in cache.get("trims", {}):
        cached = cache["trims"][cache_key]
        cached_time = datetime.fromisoformat(cached.get("cached_at", "2000-01-01"))
        if (datetime.now() - cached_time).days < 7:
            print(f"[VehicleData] Using cached trims for {cache_key}")
            return cached.get("options", [])
    
    print(f"[VehicleData] Fetching trims for {year} {make} {model}...")
    
    model_variants = await find_matching_models(year, make, model)
    
    if not model_variants:
        print(f"[VehicleData] No matching models found")
        return []
    
    print(f"[VehicleData] Found model variants: {model_variants}")
    
    # Collect all options
    all_raw_options = []
    seen = set()
    
    for variant in model_variants:
        options = await get_vehicle_options(year, make, variant)
        
        drivetrain = get_drivetrain_from_variant(variant, model)
        variant_trim = get_trim_from_variant(variant, model)
        
        for opt in options:
            if not opt:
                continue
            
            full_name = opt.get("text", "")
            vehicle_id = opt.get("value", "")
            
            if vehicle_id in seen:
                continue
            seen.add(vehicle_id)
            
            specs = extract_specs(full_name, year, make, variant)
            
            all_raw_options.append({
                "id": vehicle_id,
                "full_name": full_name,
                "model_variant": variant,
                "variant_trim": variant_trim,
                "drivetrain": drivetrain,
                "specs": specs
            })
    
    # Get ALL specs and ask Ollama to identify them
    all_specs = [opt["specs"] for opt in all_raw_options if opt["specs"]]
    
    trim_map = {}
    if all_specs:
        trim_map = await identify_trims_with_ollama(year, make, model, all_specs)
    
    # Build final options
    seen_combos = set()
    all_options = []
    
    for opt in all_raw_options:
        specs = opt["specs"]
        drivetrain = opt["drivetrain"]
        variant_trim = opt["variant_trim"]
        
        # Prefer Ollama's answer, fallback to variant trim
        trim_name = trim_map.get(specs, "") or variant_trim
        
        # Build full trim with drivetrain
        if trim_name and drivetrain:
            full_trim = f"{trim_name} {drivetrain}"
        elif trim_name:
            full_trim = trim_name
        elif drivetrain:
            full_trim = drivetrain
        else:
            full_trim = ""
        
        # Dedup by trim + core engine
        core_specs = re.sub(r',?\s*FFV', '', specs).strip()
        dedup_key = f"{full_trim}|{core_specs}"
        
        if dedup_key in seen_combos:
            continue
        seen_combos.add(dedup_key)
        
        # Format display
        if full_trim:
            display_name = f"{full_trim} ({specs})"
        else:
            display_name = specs
        
        all_options.append({
            "id": opt["id"],
            "name": display_name,
            "full_name": opt["full_name"],
            "model_variant": opt["model_variant"],
            "trim": full_trim,
            "specs": specs
        })
    
    # Sort
    all_options.sort(key=lambda x: (x.get("trim", "") or "zzz", x.get("specs", "")))
    
    print(f"[VehicleData] Found {len(all_options)} total trim options")
    
    # Cache
    if "trims" not in cache:
        cache["trims"] = {}
    cache["trims"][cache_key] = {
        "options": all_options,
        "cached_at": datetime.now().isoformat()
    }
    save_cache(cache)
    
    return all_options


async def get_vehicle_details(vehicle_id: str) -> dict:
    """Get detailed specs for a specific vehicle ID."""
    try:
        url = f"{FUELECONOMY_URL}/vehicle/{vehicle_id}"
        
        async with httpx.AsyncClient(headers=HEADERS, timeout=15) as client:
            response = await client.get(url)
            
            if response.status_code != 200:
                return {}
            
            return response.json()
    except Exception as e:
        print(f"[VehicleData] Error fetching details: {e}")
        return {}


def build_engine_string(details: dict) -> str:
    """Build engine string."""
    if not details:
        return ""
    
    parts = []
    
    displacement = details.get("displ")
    if displacement:
        parts.append(f"{displacement}L")
    
    if details.get("sCharger"):
        parts.append("Supercharged")
    elif details.get("tCharger"):
        parts.append("Turbo")
    
    cylinders = details.get("cylinders")
    if cylinders:
        cyl = str(cylinders)
        if int(cyl) >= 6:
            parts.append(f"V{cyl}")
        elif int(cyl) == 4:
            parts.append("I4")
        else:
            parts.append(f"{cyl}-cyl")
    
    if details.get("evMotor"):
        ev = details.get("evMotor")
        parts.append(f"Electric ({ev})" if ev else "Electric")
    
    return " ".join(parts) if parts else ""


async def get_vehicle_by_id(vehicle_id: str) -> dict:
    """Get full vehicle data by ID."""
    cache = load_cache()
    cache_key = f"vehicle_{vehicle_id}"
    
    if cache_key in cache.get("vehicles", {}):
        cached = cache["vehicles"][cache_key]
        cached_time = datetime.fromisoformat(cached.get("cached_at", "2000-01-01"))
        if (datetime.now() - cached_time).days < 30:
            return cached
    
    details = await get_vehicle_details(vehicle_id)
    
    if not details:
        return {}
    
    engine_string = build_engine_string(details)
    
    result = {
        "vehicle_id": vehicle_id,
        "year": str(details.get("year", "")),
        "make": details.get("make", ""),
        "model": details.get("model", ""),
        "full_name": f"{details.get('year', '')} {details.get('make', '')} {details.get('model', '')}",
        "engine": engine_string,
        "displacement": details.get("displ", ""),
        "cylinders": details.get("cylinders", ""),
        "supercharged": bool(details.get("sCharger")),
        "turbocharged": bool(details.get("tCharger")),
        "transmission": details.get("trany", ""),
        "drive": details.get("drive", ""),
        "fuel_type": details.get("fuelType", ""),
        "mpg_city": details.get("city08", ""),
        "mpg_highway": details.get("highway08", ""),
        "ev_motor": details.get("evMotor", ""),
        "vehicle_class": details.get("VClass", ""),
        "cached_at": datetime.now().isoformat()
    }
    
    if "vehicles" not in cache:
        cache["vehicles"] = {}
    cache["vehicles"][cache_key] = result
    save_cache(cache)
    
    return result


def format_vehicle_string(vehicle_data: dict, include_engine: bool = True) -> str:
    if not vehicle_data:
        return ""
    
    name = vehicle_data.get("full_name", "")
    if not name:
        name = f"{vehicle_data.get('year', '')} {vehicle_data.get('make', '')} {vehicle_data.get('model', '')}"
    
    if include_engine and vehicle_data.get("engine"):
        return f"{name} ({vehicle_data['engine']})"
    
    return name


def format_vehicle_context(vehicle_data: dict) -> str:
    if not vehicle_data:
        return ""
    
    parts = []
    
    if vehicle_data.get("engine"):
        parts.append(f"ENGINE: {vehicle_data['engine']}")
    
    if vehicle_data.get("drive"):
        parts.append(f"DRIVE TYPE: {vehicle_data['drive']}")
    
    if vehicle_data.get("transmission"):
        parts.append(f"TRANSMISSION: {vehicle_data['transmission']}")
    
    if vehicle_data.get("fuel_type"):
        parts.append(f"FUEL: {vehicle_data['fuel_type']}")
    
    return "\n".join(parts)


# CLI test
if __name__ == "__main__":
    import sys
    import asyncio
    
    async def test():
        if len(sys.argv) < 4:
            print("Usage: python vehicle_data.py <year> <make> <model>")
            return
        
        year = sys.argv[1]
        make = sys.argv[2]
        model = sys.argv[3]
        
        print(f"\nFetching trims for {year} {make} {model}...\n")
        
        trims = await get_available_trims(year, make, model)
        
        if trims:
            print(f"\n{'='*60}")
            print(f"FINAL RESULTS - {len(trims)} trims:")
            print('='*60)
            for t in trims:
                print(f"  {t['name']}")
        else:
            print("No trims found")
    
    asyncio.run(test())
