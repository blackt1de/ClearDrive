"""
Vehicle Data Lookup using CarsXE API
Clean, accurate vehicle data including trims, specs, and images.
"""

import httpx
import json
import re
from pathlib import Path
from datetime import datetime

CACHE_FILE = Path(__file__).parent / "vehicle_cache.json"
CARSXE_API_KEY = "xnoqhahmv_2d8p0i63e_e4wbsi4po"
CARSXE_BASE = "https://api.carsxe.com"

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "ClearDrive/1.2"
}


def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {"vehicles": {}, "trims": {}, "images": {}, "last_updated": None}


def save_cache(data: dict):
    data["last_updated"] = datetime.now().isoformat()
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)


async def get_vehicle_trims(year: str, make: str, model: str) -> list:
    """
    Get all available trims for a vehicle using CarsXE API.
    Returns a list of trim dicts with detailed specs.
    """
    cache = load_cache()
    cache_key = f"trims_{year}_{make}_{model}".lower().replace(" ", "_")

    # Check cache (7-day expiry)
    if cache_key in cache.get("trims", {}):
        cached = cache["trims"][cache_key]
        cached_time = datetime.fromisoformat(cached.get("cached_at", "2000-01-01"))
        if (datetime.now() - cached_time).days < 7:
            print(f"[CarsXE] Using cached trims for {year} {make} {model}")
            return cached.get("options", [])

    print(f"[CarsXE] Fetching trims for {year} {make} {model}...")

    try:
        url = f"{CARSXE_BASE}/v1/ymm"
        params = {
            "key": CARSXE_API_KEY,
            "year": year,
            "make": make,
            "model": model,
            "allTrimOptions": "1"
        }

        async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
            response = await client.get(url, params=params)

            if response.status_code == 429:
                print(f"[CarsXE] RATE LIMITED - API quota exceeded!")
                return [{"id": "quota_exceeded", "name": "API Limit Reached", "display_name": "API Limit Reached - Try again next month", "error": True}]

            if response.status_code == 403:
                print(f"[CarsXE] FORBIDDEN - Check API key or quota")
                return [{"id": "api_error", "name": "API Error", "display_name": "API Error - Contact support", "error": True}]

            if response.status_code != 200:
                print(f"[CarsXE] HTTP error: {response.status_code}")
                return []

            data = response.json()

            if not data.get("success", True):
                error_msg = data.get("error", "Unknown error")
                print(f"[CarsXE] API error: {error_msg}")
                if "limit" in error_msg.lower() or "quota" in error_msg.lower():
                    return [{"id": "quota_exceeded", "name": "API Limit Reached", "display_name": "API Limit Reached - Try again next month", "error": True}]
                return []

            # Extract trim options
            trim_options = data.get("trimOptions", [])
            if not trim_options:
                print(f"[CarsXE] No trims found for {year} {make} {model}")
                return []

            print(f"[CarsXE] Found {len(trim_options)} trims")

            # Process and format trims
            processed_trims = []
            seen_trims = set()

            for trim_data in trim_options:
                trim_name = trim_data.get("name", "")

                # Skip duplicates
                if trim_name in seen_trims:
                    continue
                seen_trims.add(trim_name)

                # Extract engine info
                engine_size = trim_data.get("engine_size", "")
                cylinders = trim_data.get("cylinders", "")
                horsepower = trim_data.get("horsepower", "")

                # Build engine string
                engine_str = ""
                if engine_size:
                    engine_str = f"{engine_size}L"
                if cylinders:
                    cyl = str(cylinders)
                    if int(cyl) >= 6:
                        engine_str += f" V{cyl}"
                    elif int(cyl) == 4:
                        engine_str += " I4"
                    else:
                        engine_str += f" {cyl}-cyl"

                # Check for forced induction from the name
                name_lower = trim_name.lower()
                if "supercharg" in name_lower or "s/c" in name_lower:
                    engine_str += " Supercharged"
                elif "turbo" in name_lower:
                    engine_str += " Turbo"

                if horsepower:
                    engine_str += f" ({horsepower} hp)"

                engine_str = engine_str.strip()

                # Extract transmission
                transmission = trim_data.get("transmission", "")
                trans_str = ""
                if transmission:
                    if "automatic" in transmission.lower():
                        # Extract speed if present
                        speed_match = re.search(r'(\d+)[\s-]?speed', transmission, re.IGNORECASE)
                        if speed_match:
                            trans_str = f"{speed_match.group(1)}-speed Automatic"
                        else:
                            trans_str = "Automatic"
                    elif "manual" in transmission.lower():
                        speed_match = re.search(r'(\d+)[\s-]?speed', transmission, re.IGNORECASE)
                        if speed_match:
                            trans_str = f"{speed_match.group(1)}-speed Manual"
                        else:
                            trans_str = "Manual"
                    else:
                        trans_str = transmission

                # Extract drivetrain
                drivetrain = trim_data.get("drivetrain", "")
                drive_str = ""
                if drivetrain:
                    dt_lower = drivetrain.lower()
                    if "all-wheel" in dt_lower or "awd" in dt_lower:
                        drive_str = "AWD"
                    elif "four-wheel" in dt_lower or "4wd" in dt_lower or "4x4" in dt_lower:
                        drive_str = "4WD"
                    elif "front-wheel" in dt_lower or "fwd" in dt_lower:
                        drive_str = "FWD"
                    elif "rear-wheel" in dt_lower or "rwd" in dt_lower:
                        drive_str = "RWD"

                # Clean up trim name - extract just the trim level
                # Format is usually "TrimName 2dr Coupe (engine specs)"
                display_name = trim_name

                # Remove body style from name for cleaner display
                # Pattern: "GT 2dr Coupe (3.6L 6cyl 8A)"
                clean_name_match = re.match(r'^(.+?)\s+\d+dr\s+\w+', trim_name)
                if clean_name_match:
                    display_name = clean_name_match.group(1).strip()

                # Build final display with engine
                if engine_str:
                    full_display = f"{display_name} ({engine_str})"
                else:
                    full_display = display_name

                processed_trims.append({
                    "id": trim_name,  # Use full name as ID for lookups
                    "name": display_name,
                    "full_name": trim_name,
                    "display_name": full_display,
                    "engine": engine_str,
                    "transmission": trans_str,
                    "drivetrain": drive_str,
                    "msrp": trim_data.get("base_msrp", ""),
                    "body_style": trim_data.get("body_type", ""),
                    "fuel_type": trim_data.get("fuel_type", ""),
                    "mpg_city": trim_data.get("city_mpg", ""),
                    "mpg_highway": trim_data.get("highway_mpg", ""),
                    "horsepower": horsepower,
                    "raw_data": trim_data  # Keep full data for reference
                })

            # Sort by MSRP (base models first) or by engine size
            def sort_key(t):
                msrp = t.get("msrp", "")
                if msrp:
                    try:
                        return float(msrp.replace(",", "").replace("$", ""))
                    except:
                        pass
                # Fallback: sort by engine size
                engine = t.get("engine", "")
                match = re.search(r'(\d+\.?\d*)L', engine)
                return float(match.group(1)) if match else 0

            processed_trims.sort(key=sort_key)

            # Cache results
            if "trims" not in cache:
                cache["trims"] = {}
            cache["trims"][cache_key] = {
                "options": processed_trims,
                "cached_at": datetime.now().isoformat()
            }
            save_cache(cache)

            return processed_trims

    except httpx.TimeoutException:
        print(f"[CarsXE] Request timed out")
        return []
    except Exception as e:
        print(f"[CarsXE] Error: {type(e).__name__}: {e}")
        return []


async def get_vehicle_image(year: str, make: str, model: str) -> dict:
    """
    Get a vehicle image using CarsXE Images API.
    Returns dict with image URL and metadata.
    """
    cache = load_cache()
    cache_key = f"image_{year}_{make}_{model}".lower().replace(" ", "_")

    # Check cache (30-day expiry for images)
    if cache_key in cache.get("images", {}):
        cached = cache["images"][cache_key]
        cached_time = datetime.fromisoformat(cached.get("cached_at", "2000-01-01"))
        if (datetime.now() - cached_time).days < 30:
            print(f"[CarsXE] Using cached image for {year} {make} {model}")
            return cached

    print(f"[CarsXE] Fetching image for {year} {make} {model}...")

    try:
        # Note: Images API doesn't use /v1/ prefix
        url = f"{CARSXE_BASE}/images"
        params = {
            "key": CARSXE_API_KEY,
            "year": year,
            "make": make,
            "model": model
        }

        async with httpx.AsyncClient(headers=HEADERS, timeout=15) as client:
            response = await client.get(url, params=params)

            if response.status_code != 200:
                print(f"[CarsXE] Image API error: {response.status_code}")
                return {}

            data = response.json()

            if not data.get("success", True):
                print(f"[CarsXE] Image API error: {data.get('error', 'Unknown')}")
                return {}

            images = data.get("images", [])
            if not images:
                print(f"[CarsXE] No images found for {year} {make} {model}")
                return {}

            # Find the best image - prefer larger, PNG images
            best_image = None
            best_score = 0

            for img in images:
                score = 0
                width = img.get("width", 0)
                height = img.get("height", 0)

                # Prefer larger images
                score += (width * height) / 10000

                # Prefer PNGs (usually cleaner stock photos)
                if img.get("mime") == "image/png":
                    score += 100

                # Prefer images from known good sources
                link = img.get("link", "").lower()
                if "evox" in link or "chrome" in link or "kelley" in link:
                    score += 200

                # Avoid thumbnails
                if "thumbnail" in link.lower():
                    score -= 500

                if score > best_score:
                    best_score = score
                    best_image = img

            if not best_image:
                best_image = images[0]  # Fallback to first

            result = {
                "url": best_image.get("link", ""),
                "width": best_image.get("width", 0),
                "height": best_image.get("height", 0),
                "thumbnail": best_image.get("thumbnailLink", ""),
                "cached_at": datetime.now().isoformat()
            }

            # Cache result
            if "images" not in cache:
                cache["images"] = {}
            cache["images"][cache_key] = result
            save_cache(cache)

            print(f"[CarsXE] Found image: {result['url'][:50]}...")
            return result

    except Exception as e:
        print(f"[CarsXE] Image error: {type(e).__name__}: {e}")
        return {}


# Alias for backwards compatibility with existing code
async def get_available_trims(year: str, make: str, model: str) -> list:
    """Backwards-compatible wrapper for get_vehicle_trims."""
    return await get_vehicle_trims(year, make, model)


async def get_vehicle_by_id(vehicle_id: str) -> dict:
    """
    Get vehicle details by ID (which is the trim's full name).
    Parses from cached trim data.
    """
    cache = load_cache()

    # Search through cached trims to find this vehicle
    for cache_key, cached_data in cache.get("trims", {}).items():
        for trim in cached_data.get("options", []):
            if trim.get("id") == vehicle_id or trim.get("full_name") == vehicle_id:
                # Extract year/make/model from cache key
                # Format: trims_2023_dodge_challenger
                parts = cache_key.split("_")
                if len(parts) >= 4:
                    year = parts[1]
                    make = parts[2].title()
                    model = " ".join(parts[3:]).title()

                    return {
                        "vehicle_id": vehicle_id,
                        "year": year,
                        "make": make,
                        "model": model,
                        "trim": trim.get("name", ""),
                        "full_name": f"{year} {make} {model} {trim.get('name', '')}",
                        "engine": trim.get("engine", ""),
                        "transmission": trim.get("transmission", ""),
                        "drive": trim.get("drivetrain", ""),
                        "fuel_type": trim.get("fuel_type", ""),
                        "mpg_city": trim.get("mpg_city", ""),
                        "mpg_highway": trim.get("mpg_highway", ""),
                        "msrp": trim.get("msrp", ""),
                        "raw_data": trim.get("raw_data", {})
                    }

    return {}


def format_vehicle_string(vehicle_data: dict, include_engine: bool = True) -> str:
    """Format vehicle data as a display string."""
    if not vehicle_data:
        return ""

    name = vehicle_data.get("full_name", "")
    if not name:
        parts = [
            vehicle_data.get("year", ""),
            vehicle_data.get("make", ""),
            vehicle_data.get("model", "")
        ]
        name = " ".join(p for p in parts if p)

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

    if trim or vehicle_data.get("trim"):
        parts.append(f"TRIM: {trim or vehicle_data.get('trim', '')}")

    if vehicle_data.get("engine"):
        parts.append(f"ENGINE: {vehicle_data['engine']}")

    if vehicle_data.get("drive"):
        parts.append(f"DRIVETRAIN: {vehicle_data['drive']}")

    if vehicle_data.get("transmission"):
        parts.append(f"TRANSMISSION: {vehicle_data['transmission']}")

    if vehicle_data.get("fuel_type"):
        parts.append(f"FUEL TYPE: {vehicle_data['fuel_type']}")

    if vehicle_data.get("msrp"):
        parts.append(f"MSRP: ${vehicle_data['msrp']}")

    return "\n".join(parts)


if __name__ == "__main__":
    import sys
    import asyncio

    async def test():
        if len(sys.argv) < 4:
            # Default test
            year, make, model = "2023", "Dodge", "Challenger"
        else:
            year = sys.argv[1]
            make = sys.argv[2]
            model = " ".join(sys.argv[3:])

        print(f"\n{'='*60}")
        print(f"Testing CarsXE API for {year} {make} {model}")
        print('='*60)

        # Test trims
        print("\n--- TRIMS ---")
        trims = await get_vehicle_trims(year, make, model)

        if trims:
            print(f"\nFound {len(trims)} trims:")
            for t in trims:
                print(f"  - {t['display_name']}")
                if t.get('drivetrain'):
                    print(f"      Drivetrain: {t['drivetrain']}")
                if t.get('transmission'):
                    print(f"      Transmission: {t['transmission']}")
                if t.get('msrp'):
                    print(f"      MSRP: ${t['msrp']}")
        else:
            print("No trims found")

        # Test images
        print("\n--- IMAGE ---")
        image = await get_vehicle_image(year, make, model)
        if image:
            print(f"Image URL: {image.get('url', 'None')}")
            print(f"Size: {image.get('width', 0)}x{image.get('height', 0)}")
        else:
            print("No image found")

    asyncio.run(test())
