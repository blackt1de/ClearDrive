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
            
            # Get definition from multiple possible locations
            definition_div = soup.find('div', class_='definition')
            if definition_div:
                result["definition"] = clean_text(definition_div.get_text())
            else:
                # Try article or main content
                article = soup.find('article') or soup.find('div', class_='entry-content')
                if article:
                    first_p = article.find('p')
                    if first_p:
                        result["definition"] = clean_text(first_p.get_text())
                else:
                    # Try h1 followed by p
                    h1 = soup.find('h1')
                    if h1:
                        next_p = h1.find_next('p')
                        if next_p:
                            result["definition"] = clean_text(next_p.get_text())
            
            # Get causes - look for various header patterns
            causes_headers = soup.find_all(['h2', 'h3', 'h4'], string=re.compile(r'cause|reason|why', re.I))
            for causes_section in causes_headers:
                causes_list = causes_section.find_next('ul')
                if causes_list:
                    for li in causes_list.find_all('li')[:8]:
                        cause = clean_text(li.get_text())
                        if cause and len(cause) > 10 and cause not in result["causes"]:
                            result["causes"].append(cause)
                    if result["causes"]:
                        break
            
            # Get symptoms
            symptoms_headers = soup.find_all(['h2', 'h3', 'h4'], string=re.compile(r'symptom|sign|notice', re.I))
            for symptoms_section in symptoms_headers:
                symptoms_list = symptoms_section.find_next('ul')
                if symptoms_list:
                    for li in symptoms_list.find_all('li')[:6]:
                        symptom = clean_text(li.get_text())
                        if symptom and len(symptom) > 10 and symptom not in result["symptoms"]:
                            result["symptoms"].append(symptom)
                    if result["symptoms"]:
                        break
            
            # Get diagnostic steps if available
            diag_headers = soup.find_all(['h2', 'h3', 'h4'], string=re.compile(r'diagnos|repair|fix|how to', re.I))
            for diag_section in diag_headers:
                diag_list = diag_section.find_next(['ul', 'ol'])
                if diag_list:
                    for li in diag_list.find_all('li')[:6]:
                        step = clean_text(li.get_text())
                        if step and len(step) > 10:
                            result["diagnostic_steps"].append(step)
                    if result["diagnostic_steps"]:
                        break
            
            if result["definition"] or result["causes"]:
                print(f"[CodeScraper] ✓ Found data on OBD-Codes.com")
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
    print(f"[CodeScraper] Checking CarComplaints.com for {year} {make} {model}...")
    
    # CarComplaints uses Title Case for URLs
    make_slug = make.title().replace(" ", "_")
    model_slug = model.title().replace(" ", "_")
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
                "engine_problems": [],  # NEW: trim-specific
                "recalls": 0,
                "tsbs": 0,
                "trim_relevant": []  # NEW: problems mentioning this trim/engine
            }
            
            # Get engine keywords for filtering
            engine_keywords = extract_engine_keywords(trim, engine)
            
            # Get problem categories
            problem_links = soup.find_all('a', class_='problem-area')
            for link in problem_links[:10]:
                problem_text = clean_text(link.get_text())
                count_span = link.find('span', class_='count')
                count = clean_text(count_span.get_text()) if count_span else ""
                if problem_text:
                    result["problems"].append({
                        "category": problem_text,
                        "count": count
                    })
            
            # Get worst problems - and check if any mention our trim/engine
            worst_section = soup.find('div', class_='worst-problems')
            if worst_section:
                for item in worst_section.find_all(['div', 'li'], class_=re.compile(r'problem|complaint'))[:8]:
                    title_elem = item.find('a') or item.find(['h3', 'h4', 'span'])
                    if title_elem:
                        problem_text = clean_text(title_elem.get_text())
                        result["worst_problems"].append(problem_text)
                        
                        # Check if this problem is relevant to our trim/engine
                        problem_lower = problem_text.lower()
                        for kw in engine_keywords:
                            if kw.lower() in problem_lower:
                                result["trim_relevant"].append(problem_text)
                                break
            
            # Also search all complaint text for engine-specific issues
            all_complaints = soup.find_all(['div', 'p'], class_=re.compile(r'complaint|problem|issue'))
            for complaint in all_complaints[:20]:
                text = clean_text(complaint.get_text())
                text_lower = text.lower()
                
                # Check for engine-related keywords
                if any(kw.lower() in text_lower for kw in engine_keywords):
                    if text not in result["engine_problems"] and len(text) > 20:
                        result["engine_problems"].append(text[:200])
            
            # Get recall/TSB counts
            recall_link = soup.find('a', href=re.compile(r'recalls'))
            if recall_link:
                count_match = re.search(r'\d+', recall_link.get_text())
                if count_match:
                    result["recalls"] = int(count_match.group())
            
            tsb_link = soup.find('a', href=re.compile(r'tsbs'))
            if tsb_link:
                count_match = re.search(r'\d+', tsb_link.get_text())
                if count_match:
                    result["tsbs"] = int(count_match.group())
            
            if result["problems"] or result["worst_problems"]:
                print(f"[CodeScraper] ✓ Found {len(result['problems'])} problem areas on CarComplaints.com")
                if result["trim_relevant"]:
                    print(f"[CodeScraper] ✓ Found {len(result['trim_relevant'])} trim-specific issues")
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
    print(f"[CodeScraper] Checking RepairPal.com for {year} {make} {model}...")
    
    # RepairPal uses lowercase with hyphens, and /cars/ path
    make_slug = make.lower().replace(" ", "-")
    model_slug = model.lower().replace(" ", "-")
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
                "reliability_rating": "",
                "annual_cost": "",
                "engine_specific_repairs": []  # NEW: for trim-relevant repairs
            }
            
            # Get engine keywords for filtering
            engine_keywords = extract_engine_keywords(trim, engine)
            
            # Get common repairs with costs - try multiple selectors
            repair_selectors = [
                ('div', 'repair-item'),
                ('div', 'estimate-item'),
                ('a', 'estimate-card'),
                ('div', 'common-repair'),
                ('tr', 'repair-row'),
            ]
            
            for tag, class_name in repair_selectors:
                repair_items = soup.find_all(tag, class_=re.compile(class_name, re.I))
                for item in repair_items[:12]:
                    # Try to find repair name
                    name_elem = item.find(['span', 'a', 'h3', 'h4', 'td'], class_=re.compile(r'name|title|repair', re.I))
                    if not name_elem:
                        name_elem = item.find(['a', 'h3', 'h4'])
                    
                    # Try to find cost
                    cost_elem = item.find(['span', 'td', 'div'], class_=re.compile(r'cost|price|range', re.I))
                    
                    if name_elem:
                        repair_name = clean_text(name_elem.get_text())
                        repair_info = {"repair": repair_name}
                        
                        if cost_elem:
                            repair_info["cost"] = clean_text(cost_elem.get_text())
                        
                        if repair_name and len(repair_name) > 3:
                            result["common_repairs"].append(repair_info)
                            
                            # Check if relevant to our engine
                            repair_lower = repair_name.lower()
                            for kw in engine_keywords:
                                if kw.lower() in repair_lower:
                                    result["engine_specific_repairs"].append(repair_info)
                                    break
                
                if result["common_repairs"]:
                    break
            
            # Get reliability rating
            rating_selectors = [
                ('div', 'reliability'),
                ('span', 'rating'),
                ('div', 'score'),
            ]
            for tag, class_name in rating_selectors:
                rating_elem = soup.find(tag, class_=re.compile(class_name, re.I))
                if rating_elem:
                    result["reliability_rating"] = clean_text(rating_elem.get_text())
                    break
            
            # Get annual cost estimate
            annual_elem = soup.find(string=re.compile(r'annual|yearly|per year', re.I))
            if annual_elem:
                parent = annual_elem.parent
                if parent:
                    cost_match = re.search(r'\$[\d,]+', parent.get_text())
                    if cost_match:
                        result["annual_cost"] = cost_match.group()
            
            if result["common_repairs"]:
                print(f"[CodeScraper] ✓ Found {len(result['common_repairs'])} repair estimates on RepairPal.com")
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
