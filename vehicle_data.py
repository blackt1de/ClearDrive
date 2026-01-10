"""
Vehicle Data Lookup
Uses FuelEconomy.gov for specs + NHTSA VPIC API for trim names + Ollama for matching.
"""

import httpx
import json
import re
from pathlib import Path
from datetime import datetime

CACHE_FILE = Path(__file__).parent / "vehicle_cache.json"
FUELECONOMY_URL = "https://www.fueleconomy.gov/ws/rest"
NHTSA_API = "https://vpic.nhtsa.dot.gov/api/vehicles"
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
    return {"vehicles": {}, "trims": {}, "nhtsa": {}, "last_updated": None}


def save_cache(data: dict):
    data["last_updated"] = datetime.now().isoformat()
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)


async def get_nhtsa_trims(year: str, make: str, model: str) -> list:
    """
    Get trim information from NHTSA VPIC API (Canadian Vehicle Specifications).
    Extracts trims from the Model field (e.g., "CHALLENGER 2DR COUPE RWD R/T / R/T CLASSIC").
    Returns a list of trim dicts with 'name' key.
    """
    # Try with hyphen variant for models like F-150
    model_variants_to_try = [model]
    if "-" not in model and len(model) > 1:
        # Try adding hyphen before numbers (F150 -> F-150)
        hyphenated = re.sub(r'([A-Za-z])(\d)', r'\1-\2', model)
        if hyphenated != model:
            model_variants_to_try.append(hyphenated)

    cache = load_cache()
    cache_key = f"nhtsa_{year}_{make}_{model}".lower().replace(" ", "_")

    if cache_key in cache.get("nhtsa", {}):
        cached = cache["nhtsa"][cache_key]
        cached_time = datetime.fromisoformat(cached.get("cached_at", "2000-01-01"))
        if (datetime.now() - cached_time).days < 30:
            print(f"[NHTSA] Using cached data")
            return cached.get("trims", [])

    print(f"[NHTSA] Fetching trims for {year} {make} {model}...")

    trims = []
    seen = set()
    results = []

    try:
        url = f"{NHTSA_API}/GetCanadianVehicleSpecifications/"

        async with httpx.AsyncClient(headers=HEADERS, timeout=15) as client:
            # Try each model variant (e.g., "F150" and "F-150")
            for model_try in model_variants_to_try:
                params = {
                    "year": year,
                    "make": make,
                    "model": model_try,
                    "format": "json"
                }
                response = await client.get(url, params=params)

                if response.status_code == 200:
                    data = response.json()
                    results = data.get("Results", [])
                    if results:
                        print(f"[NHTSA] Found results using model name: {model_try}")
                        break

        print(f"[NHTSA] Got {len(results)} results")

        for result in results:
            specs = result.get("Specs", [])
            spec_dict = {s.get("Name", ""): s.get("Value", "") for s in specs}

            # Trim info is embedded in the Model field
            # Format: "CHALLENGER 2DR COUPE RWD R/T / R/T CLASSIC"
            model_value = spec_dict.get("Model", "")

            if not model_value:
                continue

            # Remove the base model name and body style prefix
            # Pattern: MODEL BODY_STYLE DRIVETRAIN TRIM_NAMES
            # e.g., "CHALLENGER 2DR COUPE RWD R/T / R/T CLASSIC"

            # Build pattern to match: MODEL + body style + optional drivetrain
            # Use word boundary to avoid partial matches
            base_model_pattern = re.escape(model.upper())
            pattern = rf'^{base_model_pattern}\s+\d+DR\s+\w+\s+(RWD|FWD|AWD|4WD)?\s*'

            trim_part = re.sub(pattern, '', model_value, flags=re.IGNORECASE).strip()

            # If pattern didn't match, try without drivetrain
            if trim_part == model_value:
                pattern = rf'^{base_model_pattern}\s+\d+DR\s+\w+\s*'
                trim_part = re.sub(pattern, '', model_value, flags=re.IGNORECASE).strip()

            # If still the same, try just the model name
            if trim_part == model_value:
                pattern = rf'^{base_model_pattern}\s*'
                trim_part = re.sub(pattern, '', model_value, flags=re.IGNORECASE).strip()

            if not trim_part:
                continue

            # Split grouped trims: "R/T / R/T CLASSIC" or "SXT/SXT PLUS"
            # Be careful with R/T which has a slash in the name
            # Strategy: temporarily protect R/T, split, then restore
            protected = trim_part.replace('R/T', 'R__T__')

            # Now split on / or " / "
            if ' / ' in protected:
                raw_trims = protected.split(' / ')
            else:
                raw_trims = protected.split('/')

            # Restore R/T
            raw_trims = [t.replace('R__T__', 'R/T') for t in raw_trims]

            for raw_trim in raw_trims:
                trim_name = raw_trim.strip()

                # Skip if it's just a drivetrain
                if trim_name.upper() in ["RWD", "FWD", "AWD", "4WD", "2WD"]:
                    continue

                # Clean up any remaining drivetrain prefix
                trim_name = re.sub(r'^(RWD|FWD|AWD|4WD)\s+', '', trim_name, flags=re.IGNORECASE).strip()

                # Remove body style suffixes like "4DR SUV", "2DR COUPE", "4DR SEDAN"
                # Also handle variants like "4DR SEDAN RWD", "4DR SEDAN AWD"
                trim_name = re.sub(r'\s+\d+DR\s+\w+(\s+(RWD|FWD|AWD|4WD))?$', '', trim_name, flags=re.IGNORECASE).strip()

                # Remove trailing drivetrain
                trim_name = re.sub(r'\s+(RWD|FWD|AWD|4WD)$', '', trim_name, flags=re.IGNORECASE).strip()

                # Skip if it's just a body style
                if re.match(r'^\d+DR\s+\w+$', trim_name, flags=re.IGNORECASE):
                    continue

                if not trim_name or len(trim_name) < 2:
                    continue

                # Normalize for deduplication (case-insensitive but preserve original case)
                trim_lower = trim_name.lower()
                if trim_lower not in seen:
                    seen.add(trim_lower)
                    trims.append({"name": trim_name})

        print(f"[NHTSA] Extracted {len(trims)} trims: {[t['name'] for t in trims]}")

    except Exception as e:
        print(f"[NHTSA] Error fetching trims: {e}")

    # Cache results (even if empty)
    if "nhtsa" not in cache:
        cache["nhtsa"] = {}
    cache["nhtsa"][cache_key] = {
        "trims": trims,
        "cached_at": datetime.now().isoformat()
    }
    save_cache(cache)

    return trims


def generate_universal_trim_name(specs: str, drivetrain: str, index: int, total_count: int) -> str:
    """
    Generate a descriptive trim name based on engine characteristics.
    Works for ANY vehicle - no hardcoding.
    """
    # Extract engine info from specs
    disp_match = re.search(r'(\d+\.?\d*)\s*L', specs)
    displacement = float(disp_match.group(1)) if disp_match else 0
    
    cyl_match = re.search(r'(\d+)\s*cyl', specs)
    cylinders = int(cyl_match.group(1)) if cyl_match else 0
    
    is_supercharged = 'sup charg' in specs.lower() or 'supercharg' in specs.lower()
    is_turbo = 'turbo' in specs.lower()
    is_hybrid = 'hybrid' in specs.lower() or 'electric' in specs.lower()
    
    # Build descriptive name based on engine characteristics
    if is_hybrid:
        base = "Hybrid"
    elif is_supercharged:
        base = "Performance"  # Supercharged = top performance
    elif is_turbo:
        if displacement < 2.0:
            base = "Turbo"
        else:
            base = "Turbo Sport"
    elif cylinders >= 8:
        if displacement >= 6.0:
            base = "V8 Sport"  # Large V8
        else:
            base = "V8"  # Regular V8
    elif cylinders == 6:
        base = "V6"
    elif cylinders == 4:
        if displacement >= 2.5:
            base = "Sport"
        else:
            base = "Base"
    else:
        # Fallback based on displacement alone
        if displacement >= 5.0:
            base = "Sport"
        elif displacement >= 3.0:
            base = "Premium"
        else:
            base = "Base"
    
    # Add drivetrain if AWD/4WD
    if drivetrain in ["AWD", "4WD"]:
        return f"{base} {drivetrain}"
    
    return base


async def match_specs_to_trims_ollama(year: str, make: str, model: str, specs_list: list, drivetrains: list, known_trims: list) -> list:
    """Use Ollama to match FuelEconomy specs to correct trim names. Returns a LIST."""

    if not specs_list:
        return []

    trim_names = [t["name"] for t in known_trims] if known_trims else []

    lines = []
    for i, (specs, drivetrain) in enumerate(zip(specs_list, drivetrains)):
        dt_info = f", {drivetrain}" if drivetrain else ""
        clean = re.sub(r'Auto \d+-spd,?\s*', '', specs)
        clean = re.sub(r'Man \d+-spd,?\s*', '', clean)
        clean = re.sub(r',?\s*FFV', '', clean).strip().strip(',')
        lines.append(f"{i+1}. {clean}{dt_info}")

    specs_text = "\n".join(lines)

    if trim_names:
        trim_list = ", ".join(trim_names[:20])
        prompt = f"""For a {year} {make} {model}, match each engine configuration to its correct trim level.

Known {year} {make} {model} trims: {trim_list}

Engine configurations:
{specs_text}

RULES:
1. Each configuration MUST get a UNIQUE trim name - NO DUPLICATES
2. Match smaller/base engines to entry-level trims from the list
3. Match larger/performance engines to higher trims from the list
4. Match supercharged/turbocharged engines to top performance trims
5. If same engine has RWD and AWD variants, add "AWD" to the AWD trim name
6. Use ONLY trims from the known trims list above

Reply with ONLY a numbered list matching the configurations above:
1. [trim name]
2. [trim name]
..."""
    else:
        prompt = f"""For a {year} {make} {model}, identify the trim level for each engine configuration.

Engine configurations:
{specs_text}

RULES:
1. Each configuration MUST get a UNIQUE trim name - NO DUPLICATES ALLOWED
2. Use real {make} {model} trim names for that year
3. Match smaller engines to base/entry trims
4. Match larger engines to performance/premium trims
5. Match supercharged/turbocharged engines to top performance trims
6. If AWD/4WD is listed, include it in the trim name

Reply with ONLY a numbered list:
1. [trim name]
2. [trim name]
..."""

    try:
        print(f"[Ollama] Matching {len(specs_list)} specs to trims...")
        if trim_names:
            print(f"[Ollama] NHTSA trims: {', '.join(trim_names[:10])}{'...' if len(trim_names) > 10 else ''}")
        
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                OLLAMA_URL,
                json={
                    "model": "llama3:8b",
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 500}
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                text = data.get("response", "").strip()
                
                print(f"[Ollama] Response:\n{text}\n")
                
                # Parse into a LIST to preserve order
                results = [None] * len(specs_list)
                
                for line in text.split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    
                    match = re.match(r'^(\d+)[.\:\)\-]\s*(.+)$', line)
                    if match:
                        idx = int(match.group(1)) - 1
                        trim = match.group(2).strip().strip('"\'.,')
                        # Clean up trim name - get LAST part after " - " (the actual trim)
                        if ' - ' in trim:
                            trim = trim.split(' - ')[-1].strip()
                        trim = trim.split(' (')[0].strip()
                        
                        if 0 <= idx < len(specs_list) and 1 < len(trim) < 40:
                            results[idx] = trim
                
                # Check if we got good results
                valid_count = sum(1 for r in results if r)
                print(f"[Ollama] Parsed {valid_count}/{len(specs_list)} trims")
                
                if valid_count >= len(specs_list) // 2:  # At least half valid
                    return results
                else:
                    print("[Ollama] Not enough valid trims, using fallback")
            else:
                print(f"[Ollama] HTTP error: {response.status_code}")
                    
    except httpx.TimeoutException:
        print(f"[Ollama] Timeout - Ollama took too long to respond")
    except httpx.ConnectError:
        print(f"[Ollama] Connection error - is Ollama running?")
    except Exception as e:
        print(f"[Ollama] Error: {type(e).__name__}: {e}")
    
    # Fallback: use universal trim name generation
    print("[Ollama] Using universal trim name generation...")
    results = []
    
    for i, (specs, drivetrain) in enumerate(zip(specs_list, drivetrains)):
        trim = generate_universal_trim_name(specs, drivetrain, i, len(specs_list))
        results.append(trim)
    
    return results


async def get_models(year: str, make: str) -> list:
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


def normalize_model_name(name: str) -> str:
    """Normalize model name for matching: lowercase, remove hyphens/punctuation."""
    if not name:
        return ""
    # Lowercase and remove common separators
    normalized = name.lower().strip()
    normalized = normalized.replace("-", "").replace("_", "").replace(" ", "")
    return normalized


def expand_series_to_pattern(make: str, model: str) -> str:
    """Convert series names to regex patterns for matching.

    Examples:
    - BMW "3 series" -> matches 328i, 330i, 340i, M3, M340i, etc.
    - BMW "5 series" -> matches 528i, 530i, 540i, M5, etc.
    - Mercedes "C class" -> matches C300, C350, C43, C63, etc.
    - Audi "A4" -> matches A4, S4, RS4

    Specific model searches (330i, C300) still work as exact matches.
    """
    make_lower = make.lower()
    model_lower = model.lower().strip()

    # BMW series patterns
    if make_lower == "bmw":
        # "3 series", "3-series", "3series" -> match 3\d{2}i?, M3, M3\d{2}
        series_match = re.match(r'^(\d)\s*[-]?\s*series$', model_lower)
        if series_match:
            series_num = series_match.group(1)
            # Pattern: starts with series number followed by 2 digits, or M + series number
            return f"^({series_num}\\d{{2}}|M{series_num})"

        # "X3", "X5" series - just match X followed by the number and optional variants
        x_match = re.match(r'^x(\d)$', model_lower)
        if x_match:
            x_num = x_match.group(1)
            return f"^X{x_num}"

    # Mercedes-Benz class patterns
    elif make_lower in ["mercedes-benz", "mercedes"]:
        # "C class", "C-class", "cclass" -> match C followed by numbers
        class_match = re.match(r'^([a-z])\s*[-]?\s*class$', model_lower)
        if class_match:
            class_letter = class_match.group(1).upper()
            # Pattern: class letter followed by digits (C300, C43, C63, etc.)
            return f"^{class_letter}\\d"

        # GLC, GLE, GLS SUV classes
        suv_match = re.match(r'^(gl[cesa])\s*[-]?\s*class$', model_lower)
        if suv_match:
            suv_class = suv_match.group(1).upper()
            return f"^{suv_class}"

    # Audi patterns
    elif make_lower == "audi":
        # "A4", "A6" etc - also match S4, RS4
        a_match = re.match(r'^a(\d)$', model_lower)
        if a_match:
            a_num = a_match.group(1)
            return f"^(A{a_num}|S{a_num}|RS{a_num})"

        # "Q5", "Q7" SUVs - match SQ variants too
        q_match = re.match(r'^q(\d)$', model_lower)
        if q_match:
            q_num = q_match.group(1)
            return f"^(Q{q_num}|SQ{q_num}|RSQ{q_num})"

    # No expansion needed
    return None


async def find_matching_models(year: str, make: str, model: str) -> list:
    """Find all model variants that match the user's input.
    Handles variations like F150/F-150, case differences, and series names.

    Examples:
    - "F150" or "F-150" -> matches "F-150"
    - "charger" -> matches "Charger"
    - "3 series" (BMW) -> matches "328i", "330i", "340i", "M3", "M340i", etc.
    - "330i" (BMW) -> matches just "330i" and variants (not M340i)
    - "C300" (Mercedes) -> matches "C300" variants (not GLC300, SLC300)
    """
    models = await get_models(year, make)

    if not models:
        return []

    # Normalize user input for matching
    model_normalized = normalize_model_name(model)
    model_lower = model.lower().strip()

    # Check if this is a series/class search that needs expansion
    series_pattern = expand_series_to_pattern(make, model)

    matches = []
    for m in models:
        m_normalized = normalize_model_name(m)
        m_lower = m.lower()

        # If we have a series pattern, try regex matching first
        if series_pattern:
            if re.match(series_pattern, m, re.IGNORECASE):
                matches.append(m)
                continue

        # For specific model searches, be more precise:
        # Match if the model name starts with the search term (word boundary)
        # This prevents "C300" from matching "GLC300" but allows "330i" to match "330i xDrive"

        # Check if model starts with search term (handles "330i" -> "330i xDrive")
        if m_lower.startswith(model_lower):
            matches.append(m)
            continue

        # Check with normalized forms for hyphen/case variations (handles "F150" -> "F-150")
        if m_normalized.startswith(model_normalized):
            matches.append(m)
            continue

        # Exact normalized match
        if m_normalized == model_normalized:
            matches.append(m)
            continue

    return matches


async def get_vehicle_options(year: str, make: str, model: str) -> list:
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
    specs = full_name
    specs = specs.replace(year, "", 1).strip()
    specs = re.sub(re.escape(make), "", specs, count=1, flags=re.IGNORECASE).strip()
    specs = re.sub(re.escape(model_variant), "", specs, count=1, flags=re.IGNORECASE).strip()
    specs = " ".join(specs.split())
    return specs


def get_drivetrain_from_variant(variant: str, model: str) -> str:
    suffix = re.sub(r'^' + re.escape(model) + r'\s*', "", variant, flags=re.IGNORECASE).strip().lower()

    # Check for AWD indicators (including brand-specific terms)
    if "awd" in suffix or "xdrive" in suffix or "quattro" in suffix or "4matic" in suffix:
        return "AWD"
    elif "4wd" in suffix:
        return "4WD"
    elif "fwd" in suffix:
        return "FWD"
    elif "rwd" in suffix:
        return "RWD"

    return ""


def get_trim_from_variant(variant: str, model: str) -> str:
    suffix = re.sub(r'^' + re.escape(model) + r'\s*', "", variant, flags=re.IGNORECASE).strip()
    suffix = re.sub(r'\b(AWD|4WD|FWD|RWD|2WD)\b', '', suffix, flags=re.IGNORECASE).strip()
    return suffix


# Common body styles that should be treated as options, not trim names
BODY_STYLES = ['coupe', 'convertible', 'sedan', 'hatchback', 'wagon', 'roadster', 'cabriolet', 'spyder', 'spider']

# American muscle car models - these should use marketing trim names, not engine specs
AMERICAN_MUSCLE_MODELS = ['challenger', 'charger', 'mustang', 'camaro', 'corvette']

# Engine-to-trim mappings for American muscle cars
# Format: (make_pattern, displacement, engine_type, is_supercharged) -> trim_name
# make_pattern is a substring to match (e.g., 'dodge' matches 'Dodge')
MUSCLE_CAR_ENGINE_TRIMS_BY_MAKE = {
    # Dodge
    ('dodge', 3.6, 'v6', False): 'SXT',
    ('dodge', 5.7, 'v8', False): 'R/T',
    ('dodge', 6.1, 'v8', False): 'SRT8',
    ('dodge', 6.4, 'v8', False): 'Scat Pack',
    ('dodge', 6.2, 'v8', True): 'Hellcat',
    # Ford
    ('ford', 2.3, 'i4', True): 'EcoBoost',  # Turbo I4
    ('ford', 3.7, 'v6', False): 'V6',
    ('ford', 5.0, 'v8', False): 'GT',
    ('ford', 5.2, 'v8', True): 'GT500',
    # Chevrolet
    ('chevrolet', 2.0, 'i4', True): 'Turbo',
    ('chevrolet', 3.6, 'v6', False): 'LT',  # Camaro LT is the V6
    ('chevy', 3.6, 'v6', False): 'LT',
    ('chevrolet', 6.2, 'v8', False): 'SS',
    ('chevy', 6.2, 'v8', False): 'SS',
    ('chevrolet', 6.2, 'v8', True): 'ZL1',
    ('chevy', 6.2, 'v8', True): 'ZL1',
}

# Fallback generic mappings (when make-specific not found)
MUSCLE_CAR_ENGINE_TRIMS = {
    (3.6, 'v6', False): 'V6',
    (5.0, 'v8', False): 'GT',
    (5.7, 'v8', False): 'R/T',
    (6.2, 'v8', False): 'SS',
    (6.4, 'v8', False): 'Scat Pack',
    (6.2, 'v8', True): 'Supercharged',
}


def get_muscle_car_trim(make: str, displacement: float, engine_type: str, is_supercharged: bool) -> str:
    """Look up marketing trim name for American muscle cars."""
    make_lower = make.lower()

    # Try make-specific mapping first
    for (make_pattern, disp, etype, is_super), trim_name in MUSCLE_CAR_ENGINE_TRIMS_BY_MAKE.items():
        if make_pattern in make_lower and abs(disp - displacement) < 0.2 and etype == engine_type and is_super == is_supercharged:
            return trim_name

    # Fallback to generic mapping
    for (disp, etype, is_super), trim_name in MUSCLE_CAR_ENGINE_TRIMS.items():
        if abs(disp - displacement) < 0.2 and etype == engine_type and is_super == is_supercharged:
            return trim_name

    return None

# Common trim/package keywords found in variant names (universal across brands)
# These are extracted from variant names to create user-friendly trim names
# Order matters - more specific patterns should come first
TRIM_KEYWORDS = [
    # Performance tiers (most specific first)
    ('srt demon', 'SRT Demon'),
    ('srt hellcat', 'SRT Hellcat'),
    ('srt 392', 'Scat Pack'),  # SRT 392 is marketed as Scat Pack
    ('scatpack', 'Scat Pack'),
    ('scat pack', 'Scat Pack'),
    ('srt', 'SRT'),
    ('amg', 'AMG'),
    ('m sport', 'M Sport'),
    ('type r', 'Type R'),
    ('type-r', 'Type R'),
    ('type s', 'Type S'),
    ('type-s', 'Type S'),
    ('nismo', 'NISMO'),
    ('trd pro', 'TRD Pro'),
    ('trd', 'TRD'),
    ('sti', 'STI'),
    ('wrx', 'WRX'),
    ('rs', 'RS'),
    ('ss', 'SS'),
    ('gt-r', 'GT-R'),
    ('gtr', 'GTR'),
    ('gt500', 'GT500'),
    ('gt350', 'GT350'),
    ('gt', 'GT'),
    ('zl1', 'ZL1'),
    ('z06', 'Z06'),
    ('z07', 'Z07'),
    ('zr1', 'ZR1'),
    # Luxury/trim levels
    ('denali', 'Denali'),
    ('platinum', 'Platinum'),
    ('king ranch', 'King Ranch'),
    ('limited', 'Limited'),
    ('premier', 'Premier'),
    ('high country', 'High Country'),
    ('lariat', 'Lariat'),
    ('longhorn', 'Longhorn'),
    ('laramie', 'Laramie'),
    ('overland', 'Overland'),
    ('rubicon', 'Rubicon'),
    ('sahara', 'Sahara'),
    ('sport', 'Sport'),
    ('touring', 'Touring'),
    ('signature', 'Signature'),
    # Common package names
    ('widebody', 'Widebody'),
    ('wide body', 'Widebody'),
    ('track pack', 'Track Pack'),
    ('performance', 'Performance'),
    ('premium', 'Premium'),
    # Common base/mid trims
    ('raptor', 'Raptor'),
    ('tremor', 'Tremor'),
    ('stx', 'STX'),
    ('xlt', 'XLT'),
    ('sxt', 'SXT'),
    ('sel', 'SEL'),
    ('sle', 'SLE'),
    ('slt', 'SLT'),
    ('ltz', 'LTZ'),
    ('lt', 'LT'),
    ('ls', 'LS'),
    ('le', 'LE'),
    ('se', 'SE'),
    ('ex-l', 'EX-L'),
    ('ex', 'EX'),
    ('lx', 'LX'),
    ('dx', 'DX'),
    ('sr5', 'SR5'),
    ('sr', 'SR'),
    ('sv', 'SV'),
    ('s', 'S'),
]

# Extended body styles with display names (pattern -> display name)
BODY_STYLE_PATTERNS = [
    ('sports wagon', 'Sports Wagon'),
    ('gran turismo', 'Gran Turismo'),
    ('grand tourer', 'Grand Tourer'),
    ('shooting brake', 'Shooting Brake'),
    ('cabriolet', 'Cabriolet'),
    ('convertible', 'Convertible'),
    ('roadster', 'Roadster'),
    ('spyder', 'Spyder'),
    ('spider', 'Spider'),
    ('coupe', 'Coupe'),
    ('sedan', 'Sedan'),
    ('hatchback', 'Hatchback'),
    ('wagon', 'Wagon'),
]


def extract_body_style(variant: str) -> tuple:
    """
    Extract body style from variant name if present.
    Returns (body_style, remaining_variant) tuple.

    Examples:
        "Viper Convertible" -> ("Convertible", "Viper")
        "328i xDrive Sports Wagon" -> ("Sports Wagon", "328i xDrive")
        "328i xDrive Gran Turismo" -> ("Gran Turismo", "328i xDrive")
        "Challenger" -> (None, "Challenger")
    """
    variant_lower = variant.lower()
    for pattern, display_name in BODY_STYLE_PATTERNS:
        if pattern in variant_lower:
            # Extract the body style and remove it from variant
            regex_pattern = rf'\s*{re.escape(pattern)}\s*'
            remaining = re.sub(regex_pattern, ' ', variant, flags=re.IGNORECASE).strip()
            return (display_name, remaining)
    return (None, variant)


async def get_available_trims(year: str, make: str, model: str) -> list:
    cache = load_cache()
    cache_key = f"trims_{year}_{make}_{model}".lower().replace(" ", "_")
    
    if cache_key in cache.get("trims", {}):
        cached = cache["trims"][cache_key]
        cached_time = datetime.fromisoformat(cached.get("cached_at", "2000-01-01"))
        if (datetime.now() - cached_time).days < 7:
            print(f"[VehicleData] Using cached trims")
            return cached.get("options", [])
    
    print(f"[VehicleData] Fetching trims for {year} {make} {model}...")

    # Step 1: Get NHTSA trims (official US government data)
    nhtsa_trims = await get_nhtsa_trims(year, make, model)
    
    # Step 2: Get FuelEconomy.gov data
    model_variants = await find_matching_models(year, make, model)
    
    if not model_variants:
        print(f"[VehicleData] No matching models found")
        return []
    
    print(f"[VehicleData] Found model variants: {model_variants}")
    
    all_raw_options = []
    seen = set()
    
    for variant in model_variants:
        options = await get_vehicle_options(year, make, variant)
        drivetrain = get_drivetrain_from_variant(variant, model)
        variant_trim = get_trim_from_variant(variant, model)

        # Extract body style from variant (e.g., "Viper Convertible" -> "Convertible")
        body_style, base_variant = extract_body_style(variant)

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
                "specs": specs,
                "body_style": body_style  # Track body style separately
            })
    
    # Step 3: Group options by ENGINE (what matters mechanically)
    # Cosmetic trims (R/T vs R/T Classic) are redundant - same engine = same diagnostics
    # Key: (displacement, cylinders, forced_induction, transmission_type)

    nhtsa_trim_names = [t["name"] for t in nhtsa_trims] if nhtsa_trims else []
    print(f"[VehicleData] Available NHTSA trims: {nhtsa_trim_names}")

    # Parse each option and extract engine signature
    def parse_engine_signature(specs: str, variant: str) -> tuple:
        """Extract (displacement, cylinders, forced_induction, trans_code, is_hybrid) from specs."""
        # Displacement and cylinders
        engine_match = re.search(r'(\d+)\s*cyl,?\s*(\d+\.?\d*)\s*L', specs)
        if engine_match:
            cylinders = int(engine_match.group(1))
            displacement = float(engine_match.group(2))
        else:
            cylinders = 0
            displacement = 0.0

        # Forced induction
        if 'sup charg' in specs.lower() or 'supercharg' in specs.lower():
            forced_induction = "supercharged"
        elif 'turbo' in specs.lower():
            forced_induction = "turbo"
        else:
            forced_induction = "na"

        # Transmission - keep more detail for hybrids/CVTs
        trans_match = re.match(r'(Auto|Man)\s*\(?([A-Za-z0-9\-]+)\)?', specs)
        if trans_match:
            trans_code = trans_match.group(2).upper()  # e.g., "S8", "AV-S6", "8-spd"
        else:
            trans_code = "auto" if not specs.lower().startswith('man') else "manual"

        # Detect hybrid from variant name or specs
        is_hybrid = 'hybrid' in variant.lower() or 'hybrid' in specs.lower()

        return (displacement, cylinders, forced_induction, trans_code, is_hybrid)

    def format_engine_display(specs: str, variant: str = "") -> tuple:
        """Return (engine_str, trans_str) for display."""
        # Transmission
        trans_match = re.match(r'(Auto|Man)\s*\(?([A-Za-z0-9\-]+)\)?', specs)
        if trans_match:
            trans_type = "Automatic" if trans_match.group(1) == "Auto" else "Manual"
            trans_detail = trans_match.group(2).replace('-spd', ' speed')
            transmission = f"{trans_detail} {trans_type}"
        else:
            transmission = ""

        # Engine
        engine_match = re.search(r'(\d+)\s*cyl,?\s*(\d+\.?\d*)\s*L', specs)
        if engine_match:
            cylinders = engine_match.group(1)
            displacement = engine_match.group(2)

            # Use I4/I6 notation for inline engines, V for V engines
            if int(cylinders) >= 6:
                # Check if it's inline 6 (BMW, etc.) vs V6
                # BMW 6-cylinders are typically inline
                cyl_type = "I6" if 'bmw' in make.lower() else f"V{cylinders}"
            else:
                cyl_type = f"I{cylinders}" if int(cylinders) in [4, 6] else f"{cylinders}-cyl"

            engine = f"{displacement}L {cyl_type}"

            # Check for diesel (variant ends with 'd' like 328d, or has diesel in specs)
            is_diesel = 'diesel' in specs.lower() or re.search(r'\d+d\b', variant.lower())

            if is_diesel:
                engine += " Turbo Diesel"
            elif 'turbo' in specs.lower():
                engine += " Turbo"
            elif 'sup charg' in specs.lower() or 'supercharg' in specs.lower():
                engine += " Supercharged"
        else:
            engine = specs

        return (engine, transmission)

    # Check if this is a European luxury brand where each model variant is distinct
    european_brands = ["bmw", "mercedes-benz", "mercedes", "audi", "porsche", "volkswagen", "volvo", "jaguar", "land rover", "mini"]
    is_european = make.lower() in european_brands

    # Group by engine signature, keep first option per group (for ID)
    engine_groups = {}
    for opt in all_raw_options:
        specs = opt["specs"]
        drivetrain = opt["drivetrain"]
        variant = opt["model_variant"]
        sig = parse_engine_signature(specs, variant)

        # Include drivetrain in signature for AWD/4WD variants
        full_sig = sig + (drivetrain,)

        # For European brands, also include the base model number to keep 320i/328i/335i separate
        # even if they share the same engine displacement (different tune levels)
        # But DON'T include body style - that should be a popup option
        if is_european:
            base_model = variant.split()[0] if variant else ""
            # Include base model but NOT body style in signature
            # Body styles will be collected and shown as popup options
            full_sig = full_sig + (base_model,)
        else:
            # For American/Japanese brands, keep distinct model variants separate
            # e.g., "Challenger" vs "Challenger GT" should not merge
            # BUT don't separate by body style alone (Coupe vs Convertible with same engine)
            variant_suffix = get_trim_from_variant(variant, model) if variant else ""
            if variant_suffix:
                # Check if variant_suffix is ONLY a body style
                suffix_lower = variant_suffix.lower()
                is_only_body_style = suffix_lower in BODY_STYLES
                if not is_only_body_style:
                    full_sig = full_sig + (variant_suffix,)

        if full_sig not in engine_groups:
            engine_groups[full_sig] = []
        engine_groups[full_sig].append(opt)

    print(f"[VehicleData] Grouped into {len(engine_groups)} unique engine configurations")

    # Build final options - one per unique engine config
    all_options = []
    for opts_list in engine_groups.values():
        # Use first option as representative for engine info
        opt = opts_list[0]
        specs = opt["specs"]
        drivetrain = opt["drivetrain"]
        variant = opt["model_variant"]

        engine_str, trans_str = format_engine_display(specs, variant)

        # Get engine characteristics for trim matching
        disp_match = re.search(r'(\d+\.?\d*)\s*L', specs)
        displacement = float(disp_match.group(1)) if disp_match else 0
        is_supercharged = 'sup charg' in specs.lower() or 'supercharg' in specs.lower()
        is_turbo = 'turbo' in specs.lower()
        is_hybrid = 'hybrid' in variant.lower() or 'hybrid' in specs.lower()

        # Collect body styles from all options in this group
        body_styles_in_group = {}
        for o in opts_list:
            bs = o.get("body_style")
            if bs:
                body_styles_in_group[bs] = o

        # Determine trim name strategy based on brand
        # European brands (BMW, Mercedes, Audi, etc.) use model numbers as trims (320i, 328i, C300, A4)
        # American/Japanese brands use separate trim names (SXT, R/T, LX, EX)
        trim_name = ""
        variant_trim = opt["variant_trim"]

        # Check if this is a European luxury brand where model variant IS the trim
        european_brands = ["bmw", "mercedes-benz", "mercedes", "audi", "porsche", "volkswagen", "volvo", "jaguar", "land rover", "mini"]
        is_european = make.lower() in european_brands

        if is_european:
            # For European brands, extract the base model number from variant
            # "328i xDrive" -> "328i", "C300 4matic" -> "C300", "A4 quattro" -> "A4"
            base_variant = variant.split()[0] if variant else ""

            # Verify against NHTSA trims if available
            if nhtsa_trim_names:
                # Find matching NHTSA trim (case-insensitive prefix match)
                for t in nhtsa_trim_names:
                    if t.upper().startswith(base_variant.upper()):
                        trim_name = base_variant
                        break
                    # Also check if variant matches exactly
                    if normalize_model_name(t) == normalize_model_name(base_variant):
                        trim_name = base_variant
                        break

            # If no NHTSA match, use the base variant directly
            if not trim_name:
                trim_name = base_variant

            # Add xDrive/quattro/4matic suffix if present (these are drivetrain, not body style)
            variant_lower = variant.lower()
            if 'xdrive' in variant_lower and 'xdrive' not in trim_name.lower():
                trim_name = f"{trim_name} xDrive"
            elif 'quattro' in variant_lower and 'quattro' not in trim_name.lower():
                trim_name = f"{trim_name} quattro"
            elif '4matic' in variant_lower and '4matic' not in trim_name.lower():
                trim_name = f"{trim_name} 4matic"

            # DON'T add body style to trim name - it will be a popup option
            # Body styles are collected in body_styles_in_group

        else:
            # American/Japanese brands - use engine-based NHTSA trim matching
            # Special case: If we have multiple body styles with same engine,
            # try to match each body style to a specific NHTSA trim
            if len(body_styles_in_group) > 1 and nhtsa_trim_names and len(nhtsa_trim_names) == len(body_styles_in_group):
                # We have matching counts - try to create separate trims for each body style
                # This handles cases like Viper where RT-10=Convertible, GTS=Coupe
                for bs, bs_opt in body_styles_in_group.items():
                    bs_trim_name = ""
                    # Try to find NHTSA trim that might correspond to this body style
                    # Common patterns: convertible/roadster trims often have different names
                    for t in nhtsa_trim_names:
                        # Just use NHTSA trims in order for now - first for first body style
                        if not bs_trim_name:
                            bs_trim_name = t
                            nhtsa_trim_names = [x for x in nhtsa_trim_names if x != t]  # Remove used trim
                            break

                    bs_engine_str, bs_trans_str = format_engine_display(bs_opt["specs"], bs_opt["model_variant"])

                    if bs_engine_str and bs_trans_str:
                        bs_clean_specs = f"{bs_engine_str}, {bs_trans_str}"
                    elif bs_engine_str:
                        bs_clean_specs = bs_engine_str
                    else:
                        bs_clean_specs = bs_opt["specs"]

                    bs_display_name = f"{bs_trim_name} ({bs_clean_specs})" if bs_trim_name else bs_clean_specs

                    all_options.append({
                        "id": bs_opt["id"],
                        "name": bs_display_name,
                        "full_name": bs_opt["full_name"],
                        "model_variant": bs_opt["model_variant"],
                        "trim": bs_trim_name,
                        "specs": bs_opt["specs"],
                        "engine": bs_engine_str,
                        "transmission": bs_trans_str,
                        "drivetrain": bs_opt["drivetrain"],
                        "body_style": bs,
                        "nhtsa_trims": nhtsa_trim_names
                    })
                continue  # Skip the normal processing for this group

            if nhtsa_trim_names:
                # Match based on common engine-to-trim patterns
                if is_hybrid:
                    for t in nhtsa_trim_names:
                        if 'HYBRID' in t.upper():
                            trim_name = t
                            break
                elif is_supercharged:
                    for t in nhtsa_trim_names:
                        if any(x in t.upper() for x in ['HELLCAT', 'DEMON', 'REDEYE', 'SUPERCHARGED']):
                            trim_name = t
                            break
                elif displacement >= 6.0 and not is_supercharged:
                    for t in nhtsa_trim_names:
                        if any(x in t.upper() for x in ['SRT', 'SCAT', '392']):
                            trim_name = t
                            break
                elif displacement >= 5.0 and displacement < 6.0:
                    # 5.0-5.9L V8 engines - typically mid-performance trims
                    # Common trim names for this engine class across brands:
                    # Dodge: R/T (5.7L HEMI), Ford: GT (5.0L Coyote), Chevy: SS/LT1
                    mid_perf_trims = ['R/T', 'RT', 'GT', 'SS', 'LT', 'SPORT']
                    for t in nhtsa_trim_names:
                        # Use word boundary matching to avoid "SRT" matching "RT"
                        t_upper = t.upper()
                        for trim_pattern in mid_perf_trims:
                            if re.search(rf'\b{re.escape(trim_pattern)}\b', t_upper):
                                trim_name = t
                                break
                        if trim_name:
                            break
                    # Fallback: For muscle cars, use known engine-to-trim mappings
                    # For others, use engine displacement
                    if not trim_name:
                        is_muscle_car = model.lower() in AMERICAN_MUSCLE_MODELS
                        if is_muscle_car:
                            trim_name = get_muscle_car_trim(make, displacement, 'v8', False)
                        # Non-muscle cars: use engine displacement
                        if not trim_name:
                            has_generic_v8 = any('V8' in t.upper() and len(t) <= 4 for t in nhtsa_trim_names)
                            if has_generic_v8:
                                trim_name = f"{displacement}L V8"
                elif is_turbo and displacement >= 2.0:
                    priority_trims = ['TYPE R', 'TYPE-R', 'TYPER', 'GTI', 'RS', 'ST', 'SI', 'SPORT']
                    for priority in priority_trims:
                        for t in nhtsa_trim_names:
                            if priority in t.upper().replace(' ', ''):
                                trim_name = t
                                break
                        if trim_name:
                            break
                elif is_turbo:
                    for t in nhtsa_trim_names:
                        if any(x in t.upper() for x in ['SPORT', 'EX', 'TOURING', 'SI']):
                            trim_name = t
                            break
                elif displacement < 4.0:
                    for t in nhtsa_trim_names:
                        if any(x in t.upper() for x in ['SXT', 'SE', 'LX', 'LE', 'DX', 'BASE']):
                            trim_name = t
                            break
                    # Fallback for muscle cars V6
                    if not trim_name:
                        is_muscle_car = model.lower() in AMERICAN_MUSCLE_MODELS
                        if is_muscle_car:
                            trim_name = get_muscle_car_trim(make, displacement, 'v6', False)

            # Fallback to FuelEconomy variant_trim (but not if it's just a body style)
            if not trim_name:
                if variant_trim and variant_trim.lower() not in BODY_STYLES:
                    trim_name = variant_trim

        # Build display: "Trim (Engine, Transmission)" or just "(Engine, Transmission)"
        # Don't add drivetrain if trim already indicates it (xDrive, quattro, 4matic already mean AWD)
        trim_has_awd = any(x in (trim_name or "").lower() for x in ['xdrive', 'quattro', '4matic', 'awd', '4wd'])
        if drivetrain and not trim_has_awd:
            full_trim = f"{trim_name} {drivetrain}".strip() if trim_name else drivetrain
        else:
            full_trim = trim_name or ""

        if engine_str and trans_str:
            clean_specs = f"{engine_str}, {trans_str}"
        elif engine_str:
            clean_specs = engine_str
        else:
            clean_specs = specs

        if full_trim:
            display_name = f"{full_trim} ({clean_specs})"
        else:
            display_name = clean_specs

        # Add ALL options from this group (to preserve body styles, transmissions, etc.)
        for group_opt in opts_list:
            opt_specs = group_opt["specs"]
            opt_engine_str, opt_trans_str = format_engine_display(opt_specs, group_opt["model_variant"])

            if opt_engine_str and opt_trans_str:
                opt_clean_specs = f"{opt_engine_str}, {opt_trans_str}"
            elif opt_engine_str:
                opt_clean_specs = opt_engine_str
            else:
                opt_clean_specs = opt_specs

            if full_trim:
                opt_display_name = f"{full_trim} ({opt_clean_specs})"
            else:
                opt_display_name = opt_clean_specs

            all_options.append({
                "id": group_opt["id"],
                "name": opt_display_name,
                "full_name": group_opt["full_name"],
                "model_variant": group_opt["model_variant"],
                "trim": full_trim,
                "specs": opt_specs,
                "engine": opt_engine_str,
                "transmission": opt_trans_str,
                "drivetrain": group_opt["drivetrain"],
                "body_style": group_opt.get("body_style"),
                "nhtsa_trims": nhtsa_trim_names
            })

    # Sort by displacement, then transmission
    def sort_key(x):
        specs = x.get("specs", "")
        match = re.search(r'(\d+\.?\d*)\s*L', specs)
        disp = float(match.group(1)) if match else 0
        trans = 0 if "auto" in x.get("transmission", "").lower() else 1
        return (disp, trans)

    all_options.sort(key=sort_key)

    # Clean up messy trim names (especially for trucks)
    def clean_trim_name(trim: str, variant: str, engine: str) -> str:
        """Clean up trim names to be user-friendly."""
        # Combine variant and trim info for searching
        variant_lower = variant.lower() if variant else ""
        trim_lower = trim.lower() if trim else ""
        combined = f"{variant_lower} {trim_lower}"
        engine_lower = engine.lower() if engine else ""

        # First, check for known trim keywords in the combined text
        # This extracts meaningful marketing names from variant info
        found_trims = []
        for pattern, display_name in TRIM_KEYWORDS:
            # Use word boundaries to avoid partial matches (e.g., 'sport' in 'transport')
            if re.search(rf'\b{re.escape(pattern)}\b', combined):
                found_trims.append((pattern, display_name))

        # If we found trim keywords, prioritize performance trims over body modifiers
        if found_trims:
            # Separate performance trims from body modifiers
            BODY_MODIFIERS = ['Widebody', 'Track Pack', 'Performance']
            performance_trims = [(p, d) for p, d in found_trims if d not in BODY_MODIFIERS]
            body_modifiers = [d for _, d in found_trims if d in BODY_MODIFIERS]

            # Use the most specific performance trim, or fall back to body modifier
            if performance_trims:
                # Sort by pattern length descending to get most specific match
                performance_trims.sort(key=lambda x: len(x[0]), reverse=True)
                best_trim = performance_trims[0][1]
            elif body_modifiers:
                best_trim = body_modifiers[0]
                body_modifiers = body_modifiers[1:]  # Don't duplicate
            else:
                best_trim = found_trims[0][1]
                body_modifiers = []

            # For generic trims that could have multiple engine variants, add engine context
            # This ensures "SRT" with supercharged stays separate from "SRT" without
            if best_trim in ['SRT', 'Sport', 'GT', 'RS'] and not body_modifiers:
                if 'supercharged' in engine_lower:
                    best_trim = f"{best_trim} Supercharged"
                elif 'turbo' in engine_lower:
                    best_trim = f"{best_trim} Turbo"

            if body_modifiers:
                return f"{best_trim} {' '.join(body_modifiers)}"
            return best_trim

        # If trim is already clean (from European brands, etc.), use it
        if trim and trim not in ['', 'Base'] and not any(x in trim.upper() for x in ['FFV', 'PICKUP', 'CAB', 'BOX', 'PAYLOAD']):
            # Clean minor stuff
            clean = trim
            clean = re.sub(r'\s*(2WD|4WD|4X4|RWD|FWD|AWD)$', '', clean, flags=re.IGNORECASE).strip()
            if clean:
                return clean

        # Fallback: name by engine size (for vehicles without clear trim names)
        if engine:
            engine_match = re.search(r'(\d+\.?\d*)L', engine)
            if engine_match:
                disp = float(engine_match.group(1))

                # For American muscle cars, use marketing trim names instead of engine specs
                is_muscle_car = model.lower() in AMERICAN_MUSCLE_MODELS
                if is_muscle_car:
                    is_supercharged = 'supercharged' in engine_lower
                    is_turbo_engine = 'turbo' in engine_lower
                    if 'v8' in engine_lower:
                        engine_type = 'v8'
                    elif 'v6' in engine_lower:
                        engine_type = 'v6'
                    elif 'i4' in engine_lower or '4-cyl' in engine_lower or '4 cyl' in engine_lower:
                        engine_type = 'i4'
                    else:
                        engine_type = None

                    if engine_type:
                        muscle_trim = get_muscle_car_trim(make, disp, engine_type, is_supercharged or is_turbo_engine)
                        if muscle_trim:
                            return muscle_trim

                # Default: use engine specs
                disp_str = engine_match.group(1)
                if 'turbo' in engine_lower:
                    return f"{disp_str}L Turbo"
                elif 'diesel' in engine_lower:
                    return f"{disp_str}L Diesel"
                elif 'supercharged' in engine_lower:
                    return f"{disp_str}L Supercharged"
                elif 'v8' in engine_lower:
                    return f"{disp_str}L V8"
                elif 'v6' in engine_lower:
                    return f"{disp_str}L V6"
                elif 'i4' in engine_lower or '4-cyl' in engine_lower:
                    return f"{disp_str}L I4"
                else:
                    return f"{disp_str}L"

        return "Base"

    # Group by trim name (combine manual/auto options)
    trim_groups = {}
    for opt in all_options:
        # Clean up the trim name
        raw_trim = opt.get("trim", "")
        engine = opt.get("engine", "")
        clean_name = clean_trim_name(raw_trim, opt.get("model_variant", ""), engine)

        # For named trims (Raptor, XLT, etc), group by just trim name
        # For engine-based names (3.3L V6), keep engine in key
        # This way Raptor doesn't get split by engine, but generic trims do
        is_engine_based_name = re.match(r'^\d+\.?\d*L', clean_name)
        if is_engine_based_name:
            # Engine-based: include drivetrain to distinguish 2WD vs 4WD
            drivetrain = opt.get("drivetrain", "")
            group_key = f"{clean_name}|{drivetrain}"
        else:
            # Named trim: just use the trim name (Raptor, XLT, etc.)
            group_key = clean_name

        if group_key not in trim_groups:
            trim_groups[group_key] = {
                "display_name": clean_name,
                "engine": opt.get("engine", ""),
                "drivetrain": opt.get("drivetrain", ""),
                "options": [],
                "body_styles": {}  # Track body style options
            }

        # Add this transmission option
        trans = opt.get("transmission", "")
        is_manual = "manual" in trans.lower()
        body_style = opt.get("body_style")

        trim_groups[group_key]["options"].append({
            "id": opt.get("id"),
            "transmission": trans,
            "is_manual": is_manual,
            "full_name": opt.get("name", ""),
            "specs": opt.get("specs", ""),
            "body_style": body_style
        })

        # Track body styles
        if body_style and body_style not in trim_groups[group_key]["body_styles"]:
            trim_groups[group_key]["body_styles"][body_style] = opt.get("id")

    # Build final simplified output
    simplified_options = []
    for group_key, group in trim_groups.items():
        has_manual = any(o["is_manual"] for o in group["options"])
        has_auto = any(not o["is_manual"] for o in group["options"])

        # Check for body style options
        body_styles = group.get("body_styles", {})
        has_body_style_choice = len(body_styles) > 1

        # If only one transmission type, use that ID directly
        # If both, we'll need a popup - use auto as default but include both
        if len(group["options"]) == 1:
            primary_id = group["options"][0]["id"]
            transmission_options = None
        else:
            # Prefer automatic as default
            auto_opt = next((o for o in group["options"] if not o["is_manual"]), group["options"][0])
            primary_id = auto_opt["id"]
            # Only create transmission_options if there's actually a choice
            if has_manual and has_auto:
                transmission_options = [
                    {"id": o["id"], "label": "Automatic" if not o["is_manual"] else "Manual", "transmission": o["transmission"]}
                    for o in group["options"]
                ]
            else:
                transmission_options = None

        # Build body style options if multiple exist
        body_style_options = None
        if has_body_style_choice:
            body_style_options = [
                {"id": vid, "label": style}
                for style, vid in body_styles.items()
            ]
            # Use first body style's ID as primary if not already set reasonably
            if body_style_options:
                # Prefer "Sedan" as default if available, otherwise first option
                sedan_opt = next((o for o in body_style_options if o["label"] == "Sedan"), None)
                if sedan_opt:
                    primary_id = sedan_opt["id"]
                else:
                    primary_id = body_style_options[0]["id"]

        simplified_options.append({
            "id": primary_id,
            "name": group["display_name"],
            "engine": group["engine"],
            "drivetrain": group["drivetrain"],
            "has_transmission_choice": has_manual and has_auto,
            "transmission_options": transmission_options,
            "has_body_style_choice": has_body_style_choice,
            "body_style_options": body_style_options,
            # Keep original detailed options for reference
            "all_options": group["options"]
        })

    # Sort by engine size
    def final_sort_key(x):
        engine = x.get("engine", "")
        match = re.search(r'(\d+\.?\d*)L', engine)
        return float(match.group(1)) if match else 0

    simplified_options.sort(key=final_sort_key)

    print(f"[VehicleData] Found {len(all_options)} raw options, grouped into {len(simplified_options)} user-facing trims")

    if "trims" not in cache:
        cache["trims"] = {}
    cache["trims"][cache_key] = {
        "options": simplified_options,
        "cached_at": datetime.now().isoformat()
    }
    save_cache(cache)

    return simplified_options


async def get_vehicle_details(vehicle_id: str) -> dict:
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


def format_vehicle_context(vehicle_data: dict, trim: str = "") -> str:
    """Format detailed vehicle context for AI responses."""
    if not vehicle_data:
        return ""
    
    parts = []
    
    parts.append(f"YEAR: {vehicle_data.get('year', 'Unknown')}")
    parts.append(f"MAKE: {vehicle_data.get('make', 'Unknown')}")
    parts.append(f"MODEL: {vehicle_data.get('model', 'Unknown')}")
    
    if trim:
        parts.append(f"TRIM: {trim}")
    
    if vehicle_data.get("engine"):
        parts.append(f"ENGINE: {vehicle_data['engine']}")
    
    if vehicle_data.get("displacement"):
        parts.append(f"DISPLACEMENT: {vehicle_data['displacement']}L")
    
    if vehicle_data.get("cylinders"):
        parts.append(f"CYLINDERS: {vehicle_data['cylinders']}")
    
    if vehicle_data.get("supercharged"):
        parts.append("FORCED INDUCTION: Supercharged")
    elif vehicle_data.get("turbocharged"):
        parts.append("FORCED INDUCTION: Turbocharged")
    
    if vehicle_data.get("drive"):
        parts.append(f"DRIVETRAIN: {vehicle_data['drive']}")
    
    if vehicle_data.get("transmission"):
        parts.append(f"TRANSMISSION: {vehicle_data['transmission']}")
    
    if vehicle_data.get("fuel_type"):
        parts.append(f"FUEL TYPE: {vehicle_data['fuel_type']}")
    
    if vehicle_data.get("vehicle_class"):
        parts.append(f"VEHICLE CLASS: {vehicle_data['vehicle_class']}")
    
    return "\n".join(parts)


if __name__ == "__main__":
    import sys
    import asyncio
    
    async def test():
        if len(sys.argv) < 4:
            print("Usage: python vehicle_data.py <year> <make> <model>")
            return
        
        year = sys.argv[1]
        make = sys.argv[2]
        model = " ".join(sys.argv[3:])
        
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
