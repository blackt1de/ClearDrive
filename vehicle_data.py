"""
Vehicle Data Lookup
Uses FuelEconomy.gov for specs + Wikipedia for trim names + Ollama for matching.
"""

import httpx
import json
import re
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

CACHE_FILE = Path(__file__).parent / "vehicle_cache.json"
FUELECONOMY_URL = "https://www.fueleconomy.gov/ws/rest"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
OLLAMA_URL = "http://localhost:11434/api/generate"

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "ClearDrive/1.0"
}

# Wikipedia requires a descriptive User-Agent per their policy
WIKI_HEADERS = {
    "User-Agent": "ClearDrive/1.0 (https://github.com/cleardrive; vehicle diagnostics app) Python/httpx"
}




def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {"vehicles": {}, "trims": {}, "wikipedia": {}, "last_updated": None}


def save_cache(data: dict):
    data["last_updated"] = datetime.now().isoformat()
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)


async def search_wikipedia(year: str, make: str, model: str) -> str:
    """Search Wikipedia and return the best matching page title for the specific generation."""
    year_int = int(year)
    
    try:
        async with httpx.AsyncClient(headers=WIKI_HEADERS, timeout=15) as client:
            # Try multiple searches including platform codes
            searches = [
                f"{make} {model} LX LD",  # Charger platform code
                f"{make} {model} LC LA",  # Challenger platform code
                f"{make} {model} {year}",
                f"{make} {model} seventh generation",
                f"{make} {model}",
            ]
            
            all_results = []
            
            for search_query in searches:
                response = await client.get(WIKIPEDIA_API, params={
                    "action": "query",
                    "list": "search",
                    "srsearch": search_query,
                    "format": "json",
                    "srlimit": 10
                })
                
                if response.status_code == 200:
                    data = response.json()
                    results = data.get("query", {}).get("search", [])
                    all_results.extend(results)
            
            # Remove duplicates
            seen_titles = set()
            unique_results = []
            for r in all_results:
                title = r.get("title", "")
                if title not in seen_titles:
                    seen_titles.add(title)
                    unique_results.append(r)
            
            print(f"[Wikipedia] Search results:")
            for r in unique_results[:8]:
                print(f"  - {r.get('title', '')}")
            
            make_lower = make.lower()
            model_lower = model.lower()
            
            # Score each result to find best match for this generation
            best_match = None
            best_score = -999
            
            for result in unique_results:
                title = result.get("title", "")
                title_lower = title.lower()
                score = 0
                
                # Must contain make and model
                if make_lower not in title_lower or model_lower not in title_lower:
                    continue
                
                # Skip other models that might be in results
                other_models = ['challenger', 'magnum', 'dart', 'neon', 'avenger', 
                               'journey', 'durango', 'ram', 'viper', 'mustang', 'camaro']
                skip = False
                for other in other_models:
                    if other in title_lower and other != model_lower:
                        skip = True
                        break
                if skip:
                    continue
                
                # Check for year ranges like "(2006-2010)" or "(2011-present)"
                year_range_match = re.search(r'\((\d{4})[–\-](\d{4}|present)\)', title)
                if year_range_match:
                    start_year = int(year_range_match.group(1))
                    end_str = year_range_match.group(2)
                    end_year = 2026 if end_str.lower() == "present" else int(end_str)
                    
                    if start_year <= year_int <= end_year:
                        score += 100  # Strong match - year is in range
                    else:
                        score -= 200  # Wrong generation
                
                # Check for single year like "(2006)" - assume longer generation
                single_year_match = re.search(r'\((\d{4})\)$', title)
                if single_year_match and not year_range_match:
                    page_year = int(single_year_match.group(1))
                    # Assume generation lasts ~20 years (safer for muscle cars)
                    if page_year <= year_int <= page_year + 20:
                        score += 70
                    else:
                        score -= 100
                
                # Check for platform codes like "(LX/LD)", "(XV40)"
                if re.search(r'\([A-Z]{2,}[/\-]?[A-Z]*\d*\)', title):
                    score += 60  # Generation-specific page with platform code
                
                # PENALTY: Generic page without any year/generation indicator
                if not year_range_match and not single_year_match and not re.search(r'\([A-Z]{2,}', title):
                    score -= 50  # Penalize generic pages
                
                # Prefer "generation" in title
                if "generation" in title_lower:
                    score += 30
                
                if "list of" in title_lower:
                    score -= 100
                
                if "concept" in title_lower:
                    score -= 80
                
                if f"{make_lower} {model_lower}" in title_lower:
                    score += 10
                
                print(f"[Wikipedia] Scoring '{title}': {score}")
                
                if score > best_score:
                    best_score = score
                    best_match = title
            
            # Only use if score is reasonable
            if best_match and best_score > -50:
                return best_match
            
            # Fallback: first result with make and model that has a year
            for result in unique_results:
                title = result.get("title", "")
                title_lower = title.lower()
                if make_lower in title_lower and model_lower in title_lower:
                    if re.search(r'\(\d{4}', title):  # Has a year
                        return title
            
            # Last resort: first result with make and model
            for result in unique_results:
                title = result.get("title", "").lower()
                if make_lower in title and model_lower in title:
                    return result.get("title", "")
                
    except Exception as e:
        print(f"[Wikipedia] Search error: {e}")
    
    return ""


async def get_wikipedia_page(title: str) -> str:
    """Get Wikipedia page HTML content."""
    try:
        async with httpx.AsyncClient(headers=WIKI_HEADERS, timeout=15) as client:
            response = await client.get(WIKIPEDIA_API, params={
                "action": "parse",
                "page": title,
                "format": "json",
                "prop": "text|sections"
            })
            
            if response.status_code == 200:
                data = response.json()
                html = data.get("parse", {}).get("text", {}).get("*", "")
                print(f"[Wikipedia] Got page: {len(html)} chars")
                return html
    except Exception as e:
        print(f"[Wikipedia] Page fetch error: {e}")
    
    return ""


def extract_trims_from_wikipedia(html: str, year: str, make: str, model: str) -> list:
    """Extract trim names from Wikipedia page for the specific year."""
    if not html:
        return []
    
    soup = BeautifulSoup(html, 'html.parser')
    trims = []
    seen = set()
    year_int = int(year)
    make_lower = make.lower()
    model_lower = model.lower()
    
    full_text = soup.get_text()
    
    # Method 1: Look in wikitables
    tables = soup.find_all('table', class_='wikitable')
    print(f"[Wikipedia] Found {len(tables)} wikitables")
    
    for table in tables:
        rows = table.find_all('tr')
        if not rows:
            continue
        
        table_text = table.get_text().lower()
        
        if any(x in table_text for x in ['predecessor', 'successor', 'assembly', 'designer', 'body style']):
            if not any(x in table_text for x in ['trim', 'engine', 'power', 'torque', 'displacement']):
                continue
        
        headers = []
        header_row = rows[0]
        for th in header_row.find_all(['th', 'td']):
            headers.append(th.get_text(strip=True).lower())
        
        trim_col = -1
        year_col = -1
        engine_col = -1
        
        for i, h in enumerate(headers):
            h_lower = h.lower()
            if any(x in h_lower for x in ['trim', 'model', 'variant', 'version', 'name', 'grade', 'level']):
                if trim_col == -1:
                    trim_col = i
            if any(x in h_lower for x in ['year', 'production', 'sold', 'available']):
                year_col = i
            if any(x in h_lower for x in ['engine', 'power', 'motor', 'displacement']):
                engine_col = i
        
        for row in rows[1:]:
            cells = row.find_all(['td', 'th'])
            if not cells:
                continue
            
            year_ok = True
            if year_col >= 0 and year_col < len(cells):
                year_text = cells[year_col].get_text(strip=True)
                year_nums = re.findall(r'\d{4}', year_text)
                if year_nums:
                    start = int(year_nums[0])
                    end = int(year_nums[-1]) if len(year_nums) > 1 else 2026
                    if "present" in year_text.lower():
                        end = 2026
                    if not (start <= year_int <= end):
                        year_ok = False
            
            if not year_ok:
                continue
            
            if trim_col >= 0 and trim_col < len(cells):
                trim_text = cells[trim_col].get_text(strip=True)
            else:
                trim_text = cells[0].get_text(strip=True)
            
            trim_text = re.sub(r'\[.*?\]', '', trim_text).strip()
            trim_text = re.sub(r'\(.*?\)', '', trim_text).strip()
            
            engine = ""
            if engine_col >= 0 and engine_col < len(cells):
                engine = cells[engine_col].get_text(strip=True)
                engine = re.sub(r'\[.*?\]', '', engine).strip()
            
            if not trim_text or len(trim_text) < 2 or len(trim_text) > 35:
                continue
            
            trim_lower = trim_text.lower()
            
            skip_words = ['engine', 'transmission', 'wheelbase', 'length', 'width', 
                          'height', 'weight', 'capacity', 'standard', 'optional',
                          'assembly', 'platform', 'related', 'predecessor', 'successor',
                          'body', 'door', 'seat', 'fuel', 'class', 'segment',
                          'available', 'dropped', 'the rwd', 'awd v8', 'rwd v6']
            if any(x in trim_lower for x in skip_words):
                continue
            
            other_models = ['challenger', 'mustang', 'camaro', 'corvette', 'ram', 
                           'durango', 'journey', 'dart', 'avenger', 'magnum', 'neon',
                           'civic', 'accord', 'camry', 'corolla', 'f-150', 'silverado']
            if any(x in trim_lower for x in other_models) and model_lower not in trim_lower:
                continue
            
            if re.match(r'^[\d\.\s]+$', trim_text):
                continue
            
            if trim_lower not in seen:
                seen.add(trim_lower)
                trims.append({"name": trim_text, "engine": engine})
    
    # Method 2: Look for trim patterns in text
    trim_section_patterns = [
        r'(?:trim levels?|trims|variants?|models?)\s+(?:include|are|were|offered|available)[:\s]+([^\.]+)',
        r'(?:available|offered)\s+(?:in|as)\s+([A-Z][A-Za-z0-9/\-\s,]+)\s+(?:trim|model)',
    ]
    
    for pattern in trim_section_patterns:
        matches = re.findall(pattern, full_text, re.IGNORECASE)
        for match in matches:
            parts = re.split(r',\s*|\s+and\s+', match)
            for part in parts:
                trim = part.strip()
                trim = re.sub(r'\[.*?\]', '', trim).strip()
                if trim and 2 < len(trim) < 25 and trim.lower() not in seen:
                    skip_words = ['engine', 'transmission', 'wheelbase', 'length', 'width', 
                                  'height', 'weight', 'capacity', 'standard', 'optional',
                                  'available', 'dropped', 'the rwd', 'awd v']
                    if not any(x in trim.lower() for x in skip_words):
                        seen.add(trim.lower())
                        trims.append({"name": trim, "engine": ""})
    
    print(f"[Wikipedia] Extracted {len(trims)} trims: {[t['name'] for t in trims[:15]]}")
    return trims


async def get_wikipedia_trims(year: str, make: str, model: str) -> list:
    """Get trim information from Wikipedia."""
    cache = load_cache()
    cache_key = f"wiki_{year}_{make}_{model}".lower().replace(" ", "_")
    
    if cache_key in cache.get("wikipedia", {}):
        cached = cache["wikipedia"][cache_key]
        cached_time = datetime.fromisoformat(cached.get("cached_at", "2000-01-01"))
        if (datetime.now() - cached_time).days < 30:
            print(f"[Wikipedia] Using cached data")
            return cached.get("trims", [])
    
    print(f"[Wikipedia] Searching for {year} {make} {model}...")
    
    title = await search_wikipedia(year, make, model)
    
    wiki_trims = []
    if title:
        print(f"[Wikipedia] Using page: {title}")
        html = await get_wikipedia_page(title)
        wiki_trims = extract_trims_from_wikipedia(html, year, make, model)
    
    # If Wikipedia fails, that's okay - Ollama can still identify trims
    # and we have universal fallback if Ollama also fails
    if not wiki_trims:
        print(f"[Wikipedia] No trims extracted - will rely on Ollama")
    
    if "wikipedia" not in cache:
        cache["wikipedia"] = {}
    cache["wikipedia"][cache_key] = {
        "trims": wiki_trims,
        "cached_at": datetime.now().isoformat()
    }
    save_cache(cache)
    
    return wiki_trims


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


async def match_specs_to_trims_ollama(year: str, make: str, model: str, specs_list: list, drivetrains: list, wiki_trims: list) -> list:
    """Use Ollama to match FuelEconomy specs to correct trim names. Returns a LIST."""
    
    if not specs_list:
        return []
    
    trim_names = [t["name"] for t in wiki_trims] if wiki_trims else []
    
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

IMPORTANT RULES:
1. Each configuration MUST get a UNIQUE trim name - NO DUPLICATES
2. For V6 engines (3.6L, etc): use base trims like SE, SXT, GT
3. For 5.7L V8: use R/T
4. For 6.4L V8: use R/T Scat Pack or SRT 392
5. For supercharged engines: use SRT Hellcat or Hellcat Redeye
6. If same engine has RWD and AWD variants, add "AWD" to the AWD trim name
7. Do NOT repeat trim names - if SXT is used, the next V6 should be GT or SE

Reply with ONLY a numbered list matching the configurations above:
1. [trim name]
2. [trim name]
..."""
    else:
        prompt = f"""For a {year} {make} {model}, identify the trim level for each engine configuration.

Engine configurations:
{specs_text}

IMPORTANT RULES:
1. Each configuration MUST get a UNIQUE trim name - NO DUPLICATES ALLOWED
2. Use real {make} {model} trim names
3. For smaller engines, use base/entry trims (SE, SXT, LX, Base, Sport)
4. For larger engines, use performance trims (R/T, GT, SRT, Limited)
5. For supercharged/turbo high-performance, use top trims (Hellcat, Type R, etc.)
6. If AWD/4WD is listed, include it in the trim name (e.g., "SXT AWD")

Reply with ONLY a numbered list:
1. [trim name]
2. [trim name]
..."""

    try:
        print(f"[Ollama] Matching {len(specs_list)} specs to trims...")
        if trim_names:
            print(f"[Ollama] Wikipedia trims: {', '.join(trim_names[:10])}{'...' if len(trim_names) > 10 else ''}")
        
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


async def find_matching_models(year: str, make: str, model: str) -> list:
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
    suffix = re.sub(r'^' + re.escape(model) + r'\s*', "", variant, flags=re.IGNORECASE).strip()
    suffix = re.sub(r'\b(AWD|4WD|FWD|RWD|2WD)\b', '', suffix, flags=re.IGNORECASE).strip()
    return suffix


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
    
    # Step 1: Get Wikipedia trims
    wiki_trims = await get_wikipedia_trims(year, make, model)
    
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
    
    # Step 3: Use Ollama to match ALL specs to trims - returns LIST
    all_specs = [opt["specs"] for opt in all_raw_options]
    all_drivetrains = [opt["drivetrain"] for opt in all_raw_options]
    
    trim_list = []
    if all_specs:
        trim_list = await match_specs_to_trims_ollama(
            year, make, model,
            all_specs,
            all_drivetrains,
            wiki_trims
        )
    
    # Build final options - use INDEX to get trim
    seen_combos = set()
    all_options = []
    
    for i, opt in enumerate(all_raw_options):
        specs = opt["specs"]
        drivetrain = opt["drivetrain"]
        
        # Get trim from list by INDEX
        trim_name = ""
        if i < len(trim_list) and trim_list[i]:
            trim_name = trim_list[i]
        if not trim_name:
            trim_name = opt["variant_trim"]
        
        # Build full trim with drivetrain
        if trim_name and drivetrain:
            if drivetrain.lower() not in trim_name.lower():
                full_trim = f"{trim_name} {drivetrain}"
            else:
                full_trim = trim_name
        elif trim_name:
            full_trim = trim_name
        elif drivetrain:
            full_trim = drivetrain
        else:
            full_trim = ""
        
        # Dedup by full_trim + specs
        core_specs = re.sub(r',?\s*FFV', '', specs).strip()
        dedup_key = f"{full_trim}|{core_specs}"
        
        if dedup_key in seen_combos:
            continue
        seen_combos.add(dedup_key)
        
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
    
    # Sort by displacement, then trim name
    def sort_key(x):
        specs = x.get("specs", "")
        match = re.search(r'(\d+\.?\d*)\s*L', specs)
        disp = float(match.group(1)) if match else 0
        return (disp, x.get("trim", "") or "zzz")
    
    all_options.sort(key=sort_key)
    
    print(f"[VehicleData] Found {len(all_options)} total trim options")
    
    if "trims" not in cache:
        cache["trims"] = {}
    cache["trims"][cache_key] = {
        "options": all_options,
        "cached_at": datetime.now().isoformat()
    }
    save_cache(cache)
    
    return all_options


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
