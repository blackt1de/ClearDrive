"""
Code Scraper for ClearDrive
Scrapes reliable automotive sources for OBD code information.
Priority: OBD-Codes.com > CarComplaints.com > RepairPal.com
"""

import httpx
import json
import re
import time
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
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
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
                "code": code.upper(),
                "definition": "",
                "causes": [],
                "symptoms": [],
                "diagnostic_steps": []
            }
            
            # Get definition
            definition_div = soup.find('div', class_='definition')
            if definition_div:
                result["definition"] = clean_text(definition_div.get_text())
            else:
                # Try alternate structure
                h1 = soup.find('h1')
                if h1:
                    next_p = h1.find_next('p')
                    if next_p:
                        result["definition"] = clean_text(next_p.get_text())
            
            # Get causes
            causes_section = soup.find(['h2', 'h3'], string=re.compile(r'cause', re.I))
            if causes_section:
                causes_list = causes_section.find_next('ul')
                if causes_list:
                    for li in causes_list.find_all('li')[:6]:
                        cause = clean_text(li.get_text())
                        if cause and len(cause) > 10:
                            result["causes"].append(cause)
            
            # Get symptoms
            symptoms_section = soup.find(['h2', 'h3'], string=re.compile(r'symptom', re.I))
            if symptoms_section:
                symptoms_list = symptoms_section.find_next('ul')
                if symptoms_list:
                    for li in symptoms_list.find_all('li')[:5]:
                        symptom = clean_text(li.get_text())
                        if symptom and len(symptom) > 10:
                            result["symptoms"].append(symptom)
            
            if result["definition"] or result["causes"]:
                print(f"[CodeScraper] ✓ Found data on OBD-Codes.com")
                return result
            
            return {}
            
    except Exception as e:
        print(f"[CodeScraper] Error scraping OBD-Codes.com: {e}")
        return {}


async def scrape_car_complaints(make: str, model: str, year: str) -> dict:
    """
    Scrape CarComplaints.com for vehicle-specific issues.
    Returns: common problems, TSBs, recalls
    """
    print(f"[CodeScraper] Checking CarComplaints.com for {year} {make} {model}...")
    
    make_slug = make.lower().replace(" ", "_")
    model_slug = model.lower().replace(" ", "_")
    url = f"https://www.carcomplaints.com/{make_slug}/{model_slug}/{year}/"
    
    try:
        time.sleep(0.5)  # Rate limiting
        
        async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
            response = await client.get(url)
            
            if response.status_code != 200:
                print(f"[CodeScraper] CarComplaints.com returned {response.status_code}")
                return {}
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            result = {
                "source": "CarComplaints.com",
                "problems": [],
                "worst_problems": [],
                "recalls": 0,
                "tsbs": 0
            }
            
            # Get problem categories
            problem_links = soup.find_all('a', class_='problem-area')
            for link in problem_links[:8]:
                problem_text = clean_text(link.get_text())
                count_span = link.find('span', class_='count')
                count = clean_text(count_span.get_text()) if count_span else ""
                if problem_text:
                    result["problems"].append({
                        "category": problem_text,
                        "count": count
                    })
            
            # Get worst problems
            worst_section = soup.find('div', class_='worst-problems')
            if worst_section:
                for item in worst_section.find_all('div', class_='problem')[:5]:
                    title = item.find('a')
                    if title:
                        result["worst_problems"].append(clean_text(title.get_text()))
            
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
                return result
            
            return {}
            
    except Exception as e:
        print(f"[CodeScraper] Error scraping CarComplaints.com: {e}")
        return {}


async def scrape_repairpal(make: str, model: str, year: str, code: str = None) -> dict:
    """
    Scrape RepairPal.com for repair cost estimates.
    Returns: estimated cost range for common repairs
    """
    print(f"[CodeScraper] Checking RepairPal.com for {year} {make} {model}...")
    
    make_slug = make.lower().replace(" ", "-")
    model_slug = model.lower().replace(" ", "-")
    url = f"https://repairpal.com/estimator/{make_slug}/{model_slug}/{year}"
    
    try:
        time.sleep(0.5)  # Rate limiting
        
        async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
            response = await client.get(url)
            
            if response.status_code != 200:
                print(f"[CodeScraper] RepairPal.com returned {response.status_code}")
                return {}
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            result = {
                "source": "RepairPal.com",
                "common_repairs": [],
                "reliability_rating": "",
                "annual_cost": ""
            }
            
            # Get common repairs with costs
            repair_items = soup.find_all('div', class_='repair-item')
            for item in repair_items[:10]:
                name_elem = item.find('span', class_='repair-name')
                cost_elem = item.find('span', class_='cost-range')
                if name_elem and cost_elem:
                    result["common_repairs"].append({
                        "repair": clean_text(name_elem.get_text()),
                        "cost": clean_text(cost_elem.get_text())
                    })
            
            # Try alternate structure for costs
            if not result["common_repairs"]:
                estimate_cards = soup.find_all('a', class_='estimate-card')
                for card in estimate_cards[:10]:
                    title = card.find(['h3', 'h4', 'span'])
                    cost = card.find(class_=re.compile(r'price|cost'))
                    if title:
                        repair_info = {"repair": clean_text(title.get_text())}
                        if cost:
                            repair_info["cost"] = clean_text(cost.get_text())
                        result["common_repairs"].append(repair_info)
            
            # Get reliability rating
            rating_elem = soup.find(class_=re.compile(r'reliability'))
            if rating_elem:
                result["reliability_rating"] = clean_text(rating_elem.get_text())
            
            if result["common_repairs"]:
                print(f"[CodeScraper] ✓ Found {len(result['common_repairs'])} repair estimates on RepairPal.com")
                return result
            
            return {}
            
    except Exception as e:
        print(f"[CodeScraper] Error scraping RepairPal.com: {e}")
        return {}


async def get_code_info(code: str, make: str = None, model: str = None, year: str = None) -> dict:
    """
    Get comprehensive code information from all sources.
    Caches results for 7 days.
    """
    cache = load_cache()
    cache_key = f"{code}_{make or 'generic'}_{model or ''}_{year or ''}".lower().replace(" ", "_")
    
    # Check cache
    if cache_key in cache.get("codes", {}):
        cached = cache["codes"][cache_key]
        cached_time = datetime.fromisoformat(cached.get("cached_at", "2000-01-01"))
        if (datetime.now() - cached_time).days < 7:
            print(f"[CodeScraper] Using cached data for {cache_key}")
            return cached
    
    result = {
        "code": code.upper(),
        "obd_codes": {},
        "car_complaints": {},
        "repairpal": {},
        "cached_at": datetime.now().isoformat()
    }
    
    # Get code definition (generic)
    result["obd_codes"] = await scrape_obd_codes(code)
    
    # Get vehicle-specific data if provided
    if make and model and year:
        result["car_complaints"] = await scrape_car_complaints(make, model, year)
        result["repairpal"] = await scrape_repairpal(make, model, year, code)
    
    # Cache result
    if "codes" not in cache:
        cache["codes"] = {}
    cache["codes"][cache_key] = result
    save_cache(cache)
    
    return result


def format_code_context(code_info: dict, vehicle_str: str = "") -> str:
    """Format code info into a context string for the SLM."""
    parts = []
    
    # OBD-Codes.com data
    obd = code_info.get("obd_codes", {})
    if obd:
        if obd.get("definition"):
            parts.append(f"CODE DEFINITION: {obd['definition']}")
        
        if obd.get("causes"):
            parts.append("KNOWN CAUSES (from OBD-Codes.com):")
            for i, cause in enumerate(obd["causes"][:5], 1):
                parts.append(f"  {i}. {cause}")
        
        if obd.get("symptoms"):
            parts.append("TYPICAL SYMPTOMS:")
            for symptom in obd["symptoms"][:4]:
                parts.append(f"  - {symptom}")
    
    # CarComplaints.com data
    complaints = code_info.get("car_complaints", {})
    if complaints:
        if complaints.get("worst_problems"):
            parts.append(f"KNOWN ISSUES FOR THIS VEHICLE (from CarComplaints.com):")
            for problem in complaints["worst_problems"][:4]:
                parts.append(f"  - {problem}")
        
        if complaints.get("recalls"):
            parts.append(f"RECALLS: {complaints['recalls']} recalls on file")
        
        if complaints.get("tsbs"):
            parts.append(f"TECHNICAL SERVICE BULLETINS: {complaints['tsbs']} TSBs on file")
    
    # RepairPal.com data
    repairpal = code_info.get("repairpal", {})
    if repairpal and repairpal.get("common_repairs"):
        parts.append("TYPICAL REPAIR COSTS (from RepairPal.com):")
        for repair in repairpal["common_repairs"][:5]:
            cost = repair.get("cost", "varies")
            parts.append(f"  - {repair['repair']}: {cost}")
    
    if not parts:
        return ""
    
    return "\n".join(parts)


# CLI for testing
if __name__ == "__main__":
    import sys
    import asyncio
    
    if len(sys.argv) < 2:
        print("Usage: python code_scraper.py <code> [make] [model] [year]")
        print("Example: python code_scraper.py P0420 Honda Accord 2018")
        sys.exit(1)
    
    code = sys.argv[1]
    make = sys.argv[2] if len(sys.argv) > 2 else None
    model = sys.argv[3] if len(sys.argv) > 3 else None
    year = sys.argv[4] if len(sys.argv) > 4 else None
    
    result = asyncio.run(get_code_info(code, make, model, year))
    
    print("\n" + "="*60)
    print(f"CODE INFO FOR {code.upper()}:")
    print("="*60)
    
    context = format_code_context(result, f"{year} {make} {model}" if all([year, make, model]) else "")
    print(context if context else "No data found")