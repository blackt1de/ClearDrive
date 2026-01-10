"""
Code Scraper for ClearDrive
Scrapes reliable automotive sources for OBD code information.
Now with TRIM-SPECIFIC searching for personalized diagnostics.
"""

import httpx
import json
import re
import time
import asyncio
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

CACHE_FILE = Path(__file__).parent / "code_cache.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def load_cache() -> dict:
    """Load code cache."""
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {"codes": {}, "vehicles": {}, "last_updated": None}


def save_cache(data: dict):
    """Save code cache."""
    data["last_updated"] = datetime.now().isoformat()
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def clean_text(text: str) -> str:
    """Clean scraped text."""
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def extract_base_model(model: str) -> str:
    """
    Extract the base model name, stripping trim/variant suffixes.
    CarComplaints and RepairPal organize by base model, not trim variants.

    Examples:
        "Challenger SRT8" -> "Challenger"
        "Charger AWD" -> "Charger"
        "RAV4 Hybrid" -> "RAV4"
        "Civic Type R" -> "Civic"
        "F-150 Raptor" -> "F-150"
    """
    if not model:
        return model

    # Common trim/variant suffixes to strip (case-insensitive)
    # These are universal patterns, not brand-specific
    suffixes_to_strip = [
        # Drivetrain variants
        r'\s+(AWD|4WD|FWD|RWD|2WD|4x4|4X4)$',
        # Common performance/trim indicators
        r'\s+(SRT\d*|GT\d*|RS|SS|RT|R/T|Type\s*R|Si|Sport|Limited|Platinum|Premium)',
        r'\s+(Touring|Base|SE|SXT|LX|EX|XLE|XSE|LE|DX|LT|LS|SL|SV|SR|TRD)',
        r'\s+(Hellcat|Redeye|Demon|Raptor|Tremor|Lightning|Nismo|TRD\s*Pro)',
        r'\s+(Hybrid|Electric|EV|PHEV|Plug-in)',
        # Body style indicators that might be appended
        r'\s+(Sedan|Coupe|Hatchback|Wagon|Convertible|Cab)$',
    ]

    base = model.strip()

    for pattern in suffixes_to_strip:
        base = re.sub(pattern, '', base, flags=re.IGNORECASE).strip()

    # If we stripped everything, return original
    if not base:
        return model.strip()

    return base


def extract_engine_keywords(trim: str, engine: str) -> list:
    """
    Extract searchable keywords from trim/engine info.
    Used to find trim-specific issues.
    """
    keywords = []
    
    if not trim and not engine:
        return keywords
    
    trim_lower = (trim or "").lower()
    engine_lower = (engine or "").lower()
    
    # Extract displacement
    disp_match = re.search(r'(\d+\.?\d*)\s*l', engine_lower)
    if disp_match:
        disp = disp_match.group(1)
        keywords.append(f"{disp}L")
        keywords.append(f"{disp} liter")
    
    # Check for forced induction
    if "supercharg" in engine_lower or "supercharg" in trim_lower:
        keywords.append("supercharger")
        keywords.append("supercharged")
    if "turbo" in engine_lower or "turbo" in trim_lower:
        keywords.append("turbo")
        keywords.append("turbocharged")
    
    # Check for V8/V6
    if "v8" in engine_lower:
        keywords.append("V8")
    if "v6" in engine_lower:
        keywords.append("V6")
    
    # Common performance trim indicators
    performance_trims = ["srt", "hellcat", "gt", "r/t", "rt", "ss", "type r", "si", 
                        "sport", "turbo", "awd", "4wd", "limited", "platinum"]
    for pt in performance_trims:
        if pt in trim_lower:
            keywords.append(pt.upper() if len(pt) <= 3 else pt.title())
    
    return keywords


async def scrape_obd_codes(code: str) -> dict:
    """
    Scrape OBD-Codes.com for code information.
    Returns: definition, possible causes, symptoms
    """
    print(f"[CodeScraper] Checking OBD-Codes.com for {code}...")

    code_lower = code.lower()
    url = f"https://www.obd-codes.com/{code_lower}"

    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
            response = await client.get(url)

            if response.status_code != 200:
                print(f"[CodeScraper] OBD-Codes.com returned {response.status_code}")
                return {}

            soup = BeautifulSoup(response.text, 'html.parser')

            result = {
                "source": "OBD-Codes.com",
                "url": url,
                "code": code.upper(),
                "definition": "",
                "causes": [],
                "symptoms": [],
                "diagnostic_steps": []
            }

            # Get definition - look for "What does that mean?" section
            what_means = soup.find(['h2', 'h3'], string=re.compile(r'what does', re.I))
            if what_means:
                # Get all following paragraphs until next header
                for sibling in what_means.find_next_siblings():
                    if sibling.name in ['h2', 'h3', 'h4']:
                        break
                    if sibling.name == 'p':
                        text = clean_text(sibling.get_text())
                        if text and len(text) > 20:
                            result["definition"] = text
                            break

            # Fallback: try Technical Description or first paragraph
            if not result["definition"]:
                tech_desc = soup.find(['h2', 'h3'], string=re.compile(r'technical description', re.I))
                if tech_desc:
                    p = tech_desc.find_next('p')
                    if p:
                        result["definition"] = clean_text(p.get_text())

            # Get causes - look for "Causes" header
            causes_header = soup.find(['h2', 'h3'], string=re.compile(r'^causes$', re.I))
            if causes_header:
                causes_list = causes_header.find_next('ul')
                if causes_list:
                    for li in causes_list.find_all('li')[:8]:
                        cause = clean_text(li.get_text())
                        if cause and len(cause) > 10 and cause not in result["causes"]:
                            result["causes"].append(cause)

            # Get symptoms
            symptoms_header = soup.find(['h2', 'h3'], string=re.compile(r'^symptoms$', re.I))
            if symptoms_header:
                symptoms_list = symptoms_header.find_next('ul')
                if symptoms_list:
                    for li in symptoms_list.find_all('li')[:6]:
                        symptom = clean_text(li.get_text())
                        if symptom and len(symptom) > 10 and symptom not in result["symptoms"]:
                            result["symptoms"].append(symptom)

            # Get solutions/diagnostic steps
            solutions_header = soup.find(['h2', 'h3'], string=re.compile(r'possible solutions|how to fix', re.I))
            if solutions_header:
                solutions_list = solutions_header.find_next(['ul', 'ol'])
                if solutions_list:
                    for li in solutions_list.find_all('li')[:6]:
                        step = clean_text(li.get_text())
                        if step and len(step) > 10:
                            result["diagnostic_steps"].append(step)

            if result["definition"] or result["causes"]:
                print(f"[CodeScraper] Found OBD code data: {len(result['causes'])} causes, {len(result['symptoms'])} symptoms")
                return result

            return {}

    except Exception as e:
        print(f"[CodeScraper] Error scraping OBD-Codes.com: {e}")
        return {}


async def scrape_car_complaints(make: str, model: str, year: str, trim: str = "", engine: str = "") -> dict:
    """
    Scrape CarComplaints.com for vehicle-specific issues.
    Now filters for trim-relevant problems when possible.
    """
    # Extract base model - CarComplaints organizes by base model, not trim variants
    base_model = extract_base_model(model)
    print(f"[CodeScraper] Checking CarComplaints.com for {year} {make} {base_model}...")

    # CarComplaints uses Title Case for URLs
    make_slug = make.title().replace(" ", "_")
    model_slug = base_model.title().replace(" ", "_")
    url = f"https://www.carcomplaints.com/{make_slug}/{model_slug}/{year}/"
    print(f"[CodeScraper] URL: {url}")

    try:
        await asyncio.sleep(0.3)  # Rate limiting

        async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
            response = await client.get(url)

            if response.status_code != 200:
                print(f"[CodeScraper] CarComplaints.com returned {response.status_code} for {url}")
                return {}

            soup = BeautifulSoup(response.text, 'html.parser')

            result = {
                "source": "CarComplaints.com",
                "url": url,
                "problems": [],
                "worst_problems": [],
                "engine_problems": [],
                "recalls": 0,
                "tsbs": 0,
                "complaints_count": 0,
                "trim_relevant": []
            }

            # Get engine keywords for filtering
            engine_keywords = extract_engine_keywords(trim, engine)

            # Parse complaint/recall/TSB counts from links
            # Look for patterns like "Complaints 83", "Recalls 3", "TSBs 421"
            for a in soup.find_all('a', href=True):
                text = a.get_text().strip()
                href = a.get('href', '')

                # Count complaints
                if 'Complaints' in text:
                    match = re.search(r'(\d+)', text)
                    if match:
                        result["complaints_count"] = int(match.group(1))

                # Count recalls
                if '/recalls/' in href or 'Recalls' in text:
                    match = re.search(r'(\d+)', text)
                    if match:
                        result["recalls"] = int(match.group(1))

                # Count TSBs
                if '/tsbs/' in href or 'TSBs' in text:
                    match = re.search(r'(\d+)', text)
                    if match:
                        result["tsbs"] = int(match.group(1))

            # Find specific problem links (worst problems)
            # Pattern: links that go to .shtml pages with problem descriptions
            for a in soup.find_all('a', href=True):
                href = a.get('href', '')
                text = clean_text(a.get_text())

                # Problem pages end in .shtml and have descriptive names
                if '.shtml' in href and f'/{make_slug}/{model_slug}/{year}/' in href:
                    if text and len(text) > 5 and '#' not in text:
                        # Clean up the problem text
                        problem = text.replace('#1:', '').replace('#2:', '').replace('#3:', '').strip()
                        if problem and problem not in result["worst_problems"]:
                            result["worst_problems"].append(problem)

                            # Check if relevant to engine/trim
                            problem_lower = problem.lower()
                            for kw in engine_keywords:
                                if kw.lower() in problem_lower:
                                    result["trim_relevant"].append(problem)
                                    break

                            # Check for engine-related problems
                            if any(x in problem_lower for x in ['engine', 'motor', 'turbo', 'supercharg', 'misfire', 'stall']):
                                if problem not in result["engine_problems"]:
                                    result["engine_problems"].append(problem)

            # Also try to find problem category sections
            for cat_class in ['engine', 'brakes', 'drivetrain', 'electrical', 'transmission', 'suspension']:
                cat_elem = soup.find(['div', 'a'], class_=cat_class)
                if cat_elem:
                    # Find associated count
                    cnt = cat_elem.find(class_='cnt') or cat_elem.find(class_='count')
                    count = clean_text(cnt.get_text()) if cnt else ""
                    result["problems"].append({
                        "category": cat_class.title(),
                        "count": count
                    })

            if result["worst_problems"] or result["recalls"] or result["tsbs"]:
                print(f"[CodeScraper] Found CarComplaints data: {len(result['worst_problems'])} problems, {result['recalls']} recalls, {result['tsbs']} TSBs")
                return result

            return {}

    except Exception as e:
        print(f"[CodeScraper] Error scraping CarComplaints.com: {e}")
        return {}


async def scrape_repairpal(make: str, model: str, year: str, trim: str = "", engine: str = "") -> dict:
    """
    Scrape RepairPal.com for repair cost estimates.
    Returns: estimated cost range for common repairs
    """
    # Extract base model - RepairPal organizes by base model, not trim variants
    base_model = extract_base_model(model)
    print(f"[CodeScraper] Checking RepairPal.com for {year} {make} {base_model}...")

    # RepairPal uses lowercase with hyphens, and /cars/ path
    make_slug = make.lower().replace(" ", "-")
    model_slug = base_model.lower().replace(" ", "-")
    url = f"https://repairpal.com/cars/{make_slug}/{model_slug}/{year}"
    print(f"[CodeScraper] URL: {url}")

    try:
        await asyncio.sleep(0.3)  # Rate limiting

        async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
            response = await client.get(url)

            if response.status_code != 200:
                print(f"[CodeScraper] RepairPal.com returned {response.status_code} for {url}")
                return {}

            soup = BeautifulSoup(response.text, 'html.parser')

            result = {
                "source": "RepairPal.com",
                "url": url,
                "common_repairs": [],
                "common_problems": [],
                "reliability_rating": "",
                "annual_cost": "",
                "engine_specific_repairs": []
            }

            # Get engine keywords for filtering
            engine_keywords = extract_engine_keywords(trim, engine)

            # Look for repair-estimates section
            estimates_section = soup.find(class_='repair-estimates')
            if estimates_section:
                for a in estimates_section.find_all('a')[:15]:
                    text = a.get_text().strip()
                    if text and len(text) > 10:
                        # Parse repair name and cost from text like "Dodge ChallengerCrankshaft Position Sensor Replacement$127 - $158"
                        # Remove the make/model prefix
                        text = text.replace(f"{make.title()} {model_slug.title()}", "").strip()
                        text = text.replace(f"{make.title()}{model_slug.title()}", "").strip()

                        # Try to extract cost
                        cost_match = re.search(r'(\$[\d,]+ *- *\$[\d,]+|\$[\d,]+)', text)
                        cost = cost_match.group(1) if cost_match else ""

                        # Get repair name (everything before the $)
                        if '$' in text:
                            repair_name = text.split('$')[0].strip()
                        else:
                            repair_name = text

                        if repair_name and len(repair_name) > 5:
                            repair_info = {"repair": repair_name, "cost": cost}
                            result["common_repairs"].append(repair_info)

                            # Check if relevant to engine
                            repair_lower = repair_name.lower()
                            for kw in engine_keywords:
                                if kw.lower() in repair_lower:
                                    result["engine_specific_repairs"].append(repair_info)
                                    break

            # Also look for most common problems
            problems_header = soup.find('h2', string=re.compile(r'most common.*problems', re.I))
            if problems_header:
                for sibling in problems_header.find_next_siblings()[:5]:
                    for a in sibling.find_all('a')[:8]:
                        text = clean_text(a.get_text())
                        if text and len(text) > 10 and text not in result["common_problems"]:
                            result["common_problems"].append(text)

            # Get reliability rating - look for it in various places
            for text in soup.find_all(string=re.compile(r'reliability.*rating|rating.*\d+\.?\d*/5', re.I)):
                rating_text = clean_text(text)
                if rating_text:
                    result["reliability_rating"] = rating_text[:100]
                    break

            # Get annual cost estimate
            annual_elem = soup.find(string=re.compile(r'annual|yearly|per year', re.I))
            if annual_elem:
                parent = annual_elem.parent
                if parent:
                    cost_match = re.search(r'\$[\d,]+', parent.get_text())
                    if cost_match:
                        result["annual_cost"] = cost_match.group()

            if result["common_repairs"] or result["common_problems"]:
                print(f"[CodeScraper] Found RepairPal data: {len(result['common_repairs'])} repairs, {len(result['common_problems'])} problems")
                return result

            return {}

    except Exception as e:
        print(f"[CodeScraper] Error scraping RepairPal.com: {e}")
        return {}


async def scrape_engine_specific_issues(make: str, model: str, year: str, trim: str, engine: str) -> dict:
    """
    Search for engine/trim-specific issues using a general search approach.
    Targets forums and discussion boards for real owner experiences.
    """
    if not trim and not engine:
        return {}
    
    print(f"[CodeScraper] Searching for {trim or engine} specific issues...")
    
    result = {
        "source": "Web Search",
        "engine_issues": [],
        "trim_issues": []
    }
    
    # Build search terms
    search_terms = []
    if trim:
        search_terms.append(f"{year} {make} {model} {trim} problems")
    if engine:
        # Extract key engine info
        if "supercharg" in engine.lower():
            search_terms.append(f"{year} {make} {model} supercharger problems")
        if "turbo" in engine.lower():
            search_terms.append(f"{year} {make} {model} turbo problems")
        
        disp_match = re.search(r'(\d+\.?\d*)\s*L', engine)
        if disp_match:
            disp = disp_match.group(1)
            search_terms.append(f"{year} {make} {model} {disp}L engine problems")
    
    # For now, just store the search terms - actual web search would require API
    # This data structure is ready for future integration with search APIs
    result["search_terms"] = search_terms
    
    return result


async def get_code_info(code: str, make: str = None, model: str = None, year: str = None, 
                        trim: str = None, engine: str = None) -> dict:
    """
    Get comprehensive code information from all sources.
    Now accepts trim and engine for personalized results.
    Caches results for 7 days.
    """
    cache = load_cache()
    
    # Include trim/engine in cache key for personalized caching
    cache_key = f"{code}_{make or 'generic'}_{model or ''}_{year or ''}_{trim or ''}".lower().replace(" ", "_")
    
    # Check cache
    if cache_key in cache.get("codes", {}):
        cached = cache["codes"][cache_key]
        cached_time = datetime.fromisoformat(cached.get("cached_at", "2000-01-01"))
        if (datetime.now() - cached_time).days < 7:
            print(f"[CodeScraper] Using cached data for {cache_key}")
            return cached
    
    result = {
        "code": code.upper(),
        "trim": trim or "",
        "engine": engine or "",
        "obd_codes": {},
        "car_complaints": {},
        "repairpal": {},
        "engine_specific": {},
        "cached_at": datetime.now().isoformat()
    }
    
    # Get code definition (generic)
    result["obd_codes"] = await scrape_obd_codes(code)
    
    # Get vehicle-specific data if provided - now with trim/engine
    if make and model and year:
        result["car_complaints"] = await scrape_car_complaints(make, model, year, trim, engine)
        result["repairpal"] = await scrape_repairpal(make, model, year, trim, engine)
        
        # Get engine-specific issues
        if trim or engine:
            result["engine_specific"] = await scrape_engine_specific_issues(make, model, year, trim, engine)
    
    # Cache result
    if "codes" not in cache:
        cache["codes"] = {}
    cache["codes"][cache_key] = result
    save_cache(cache)
    
    return result


def format_code_context(code_info: dict, vehicle_str: str = "", trim: str = "", engine: str = "") -> str:
    """
    Format code info into a context string for the SLM.
    Now highlights trim-specific information.
    """
    parts = []
    
    # OBD-Codes.com data
    obd = code_info.get("obd_codes", {})
    if obd:
        if obd.get("definition"):
            parts.append(f"CODE DEFINITION ({obd.get('code', 'Unknown')}): {obd['definition']}")
        
        if obd.get("causes"):
            parts.append("\nKNOWN CAUSES (from OBD-Codes.com):")
            for i, cause in enumerate(obd["causes"][:6], 1):
                parts.append(f"  {i}. {cause}")
        
        if obd.get("symptoms"):
            parts.append("\nTYPICAL SYMPTOMS:")
            for symptom in obd["symptoms"][:5]:
                parts.append(f"  • {symptom}")
        
        if obd.get("diagnostic_steps"):
            parts.append("\nDIAGNOSTIC STEPS:")
            for i, step in enumerate(obd["diagnostic_steps"][:5], 1):
                parts.append(f"  {i}. {step}")
    
    # CarComplaints.com data
    complaints = code_info.get("car_complaints", {})
    if complaints:
        # Highlight trim-specific issues first
        if complaints.get("trim_relevant"):
            parts.append(f"\n⚠️ ISSUES SPECIFIC TO THIS TRIM/ENGINE (from CarComplaints.com):")
            for problem in complaints["trim_relevant"][:4]:
                parts.append(f"  • {problem}")
        
        if complaints.get("engine_problems"):
            parts.append(f"\nENGINE-RELATED COMPLAINTS:")
            for problem in complaints["engine_problems"][:3]:
                parts.append(f"  • {problem}")
        
        if complaints.get("worst_problems"):
            parts.append(f"\nMOST COMMON ISSUES FOR THIS VEHICLE:")
            for problem in complaints["worst_problems"][:4]:
                parts.append(f"  • {problem}")
        
        if complaints.get("recalls"):
            parts.append(f"\nRECALLS: {complaints['recalls']} recalls on file")
        
        if complaints.get("tsbs"):
            parts.append(f"TECHNICAL SERVICE BULLETINS: {complaints['tsbs']} TSBs on file")
    
    # RepairPal.com data
    repairpal = code_info.get("repairpal", {})
    if repairpal:
        # Show engine-specific repairs first
        if repairpal.get("engine_specific_repairs"):
            parts.append("\n💰 REPAIR COSTS FOR THIS ENGINE TYPE (from RepairPal.com):")
            for repair in repairpal["engine_specific_repairs"][:4]:
                cost = repair.get("cost", "varies")
                parts.append(f"  • {repair['repair']}: {cost}")
        
        if repairpal.get("common_repairs"):
            parts.append("\nTYPICAL REPAIR COSTS:")
            for repair in repairpal["common_repairs"][:5]:
                cost = repair.get("cost", "varies")
                parts.append(f"  • {repair['repair']}: {cost}")
        
        if repairpal.get("reliability_rating"):
            parts.append(f"\nRELIABILITY RATING: {repairpal['reliability_rating']}")
        
        if repairpal.get("annual_cost"):
            parts.append(f"ESTIMATED ANNUAL REPAIR COST: {repairpal['annual_cost']}")
    
    if not parts:
        return ""
    
    return "\n".join(parts)


# CLI for testing
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python code_scraper.py <code> [make] [model] [year] [trim] [engine]")
        print("Example: python code_scraper.py P0420 Dodge Charger 2018 \"SRT Hellcat\" \"6.2L Supercharged V8\"")
        sys.exit(1)
    
    code = sys.argv[1]
    make = sys.argv[2] if len(sys.argv) > 2 else None
    model = sys.argv[3] if len(sys.argv) > 3 else None
    year = sys.argv[4] if len(sys.argv) > 4 else None
    trim = sys.argv[5] if len(sys.argv) > 5 else None
    engine = sys.argv[6] if len(sys.argv) > 6 else None
    
    result = asyncio.run(get_code_info(code, make, model, year, trim, engine))
    
    print("\n" + "="*60)
    print(f"CODE INFO FOR {code.upper()}:")
    if trim:
        print(f"TRIM: {trim}")
    if engine:
        print(f"ENGINE: {engine}")
    print("="*60)
    
    vehicle_str = f"{year} {make} {model}" if all([year, make, model]) else ""
    context = format_code_context(result, vehicle_str, trim, engine)
    print(context if context else "No data found")
