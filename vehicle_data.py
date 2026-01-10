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
            # First pass: group by brand trim name to collect body styles
            trim_groups = {}  # brand_trim_name -> list of variants

            for trim_data in trim_options:
                trim_name = trim_data.get("name", "")

                # Extract body style from the name (e.g., "2dr Coupe" -> "Coupe")
                body_style_from_name = ""
                body_match = re.search(r'\d+dr\s+(\w+)', trim_name)
                if body_match:
                    body_style_from_name = body_match.group(1)  # Coupe, Convertible, Sedan, etc.

                # Extract the brand trim name (everything BEFORE "2dr" or "4dr")
                brand_trim_match = re.match(r'^(.+?)\s+\d+dr\s+', trim_name)
                if brand_trim_match:
                    extracted_name = brand_trim_match.group(1).strip()
                    if extracted_name and not extracted_name.isdigit():
                        brand_trim_name = extracted_name
                    else:
                        brand_trim_name = "Base"
                elif trim_name.startswith("2dr ") or trim_name.startswith("4dr "):
                    brand_trim_name = "Base"
                else:
                    brand_trim_name = trim_name.split()[0] if trim_name else "Base"

                # Add to group
                if brand_trim_name not in trim_groups:
                    trim_groups[brand_trim_name] = []
                trim_groups[brand_trim_name].append({
                    "full_name": trim_name,
                    "body_style": body_style_from_name,
                    "raw_data": trim_data
                })

            # Second pass: build processed trims with body style options
            processed_trims = []

            for brand_trim_name, variants in trim_groups.items():
                # Use first variant as the representative
                first_variant = variants[0]
                trim_data = first_variant["raw_data"]
                trim_name = first_variant["full_name"]

                # Extract engine info - try API fields first, then features, then parse from name
                engine_size = trim_data.get("engine_size", "")
                cylinders = trim_data.get("cylinders", "")
                horsepower = trim_data.get("horsepower", "")
                fuel_type_raw = trim_data.get("fuel_type", "")
                drivetrain_raw = trim_data.get("drivetrain", "")
                engine_type_raw = ""  # For hybrid/electric detection

                # Check features.standard for Engine, Fuel, and Drive Train info
                features = trim_data.get("features", {}).get("standard", [])
                for category in features:
                    cat_name = category.get("category", "")
                    for feature in category.get("features", []):
                        fname = feature.get("name", "").lower()
                        fvalue = feature.get("value", "") or ""

                        if cat_name == "Engine":
                            if "engine size" in fname and not engine_size:
                                # Extract number from "8.0 L"
                                match = re.search(r'(\d+\.?\d*)', fvalue)
                                if match:
                                    engine_size = match.group(1)
                            elif fname == "cylinders" and not cylinders:
                                # Extract from "V10" or "V8"
                                match = re.search(r'V?(\d+)', fvalue)
                                if match:
                                    cylinders = match.group(1)
                            elif "horsepower" in fname and not horsepower:
                                # Extract from "450 hp @ 5200 rpm"
                                match = re.search(r'(\d+)\s*hp', fvalue)
                                if match:
                                    horsepower = match.group(1)
                            elif "engine type" in fname and not engine_type_raw:
                                # Capture engine type (e.g., "hybrid", "electric")
                                engine_type_raw = fvalue.lower()

                        elif cat_name == "Fuel":
                            if "fuel type" in fname and not fuel_type_raw:
                                fuel_type_raw = fvalue

                        elif cat_name == "Drive Train":
                            if "drive type" in fname and not drivetrain_raw:
                                drivetrain_raw = fvalue

                # If still not found, parse from name like "(7.0L 8cyl 6M)"
                if not engine_size:
                    size_match = re.search(r'(\d+\.?\d*)L', trim_name)
                    if size_match:
                        engine_size = size_match.group(1)
                if not cylinders:
                    cyl_match = re.search(r'(\d+)cyl', trim_name)
                    if cyl_match:
                        cylinders = cyl_match.group(1)

                # Build engine string
                engine_str = ""
                if engine_size:
                    engine_str = f"{engine_size}L"
                if cylinders:
                    cyl = str(cylinders)
                    try:
                        if int(cyl) >= 6:
                            engine_str += f" V{cyl}"
                        elif int(cyl) == 4:
                            engine_str += " I4"
                        else:
                            engine_str += f" {cyl}-cyl"
                    except ValueError:
                        pass

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

                # Extract drivetrain (use drivetrain_raw which may come from features)
                drive_str = ""
                if drivetrain_raw:
                    dt_lower = drivetrain_raw.lower()
                    if "all-wheel" in dt_lower or "all wheel" in dt_lower or "awd" in dt_lower:
                        drive_str = "AWD"
                    elif "four-wheel" in dt_lower or "four wheel" in dt_lower or "4wd" in dt_lower or "4x4" in dt_lower:
                        drive_str = "4WD"
                    elif "front-wheel" in dt_lower or "front wheel" in dt_lower or "fwd" in dt_lower:
                        drive_str = "FWD"
                    elif "rear-wheel" in dt_lower or "rear wheel" in dt_lower or "rwd" in dt_lower:
                        drive_str = "RWD"

                # Clean up fuel type - handle all common fuel types
                fuel_type_str = ""
                if fuel_type_raw:
                    ft_lower = fuel_type_raw.lower()
                    # Check for specific fuel types in order of specificity
                    if "diesel" in ft_lower:
                        fuel_type_str = "Diesel"
                    elif "electric" in ft_lower and "hybrid" not in ft_lower:
                        fuel_type_str = "Electric"
                    elif "plug-in hybrid" in ft_lower or "phev" in ft_lower:
                        fuel_type_str = "Plug-in Hybrid"
                    elif "hybrid" in ft_lower:
                        fuel_type_str = "Hybrid"
                    elif "e85" in ft_lower or "flex" in ft_lower:
                        fuel_type_str = "Flex Fuel (E85)"
                    elif "hydrogen" in ft_lower or "fuel cell" in ft_lower:
                        fuel_type_str = "Hydrogen"
                    elif "natural gas" in ft_lower or "cng" in ft_lower:
                        fuel_type_str = "Natural Gas"
                    elif "premium" in ft_lower:
                        fuel_type_str = "Premium"
                    elif "regular" in ft_lower:
                        fuel_type_str = "Regular"
                    elif "unleaded" in ft_lower:
                        # Generic unleaded - default to Regular unless high-performance
                        fuel_type_str = "Regular"
                    else:
                        # Unknown type - clean it up and use as-is
                        fuel_type_str = fuel_type_raw.split("(")[0].strip().title()

                # Also check engine type and engine string for electric/hybrid indicators
                # This catches cases where fuel type says "regular" but engine type says "hybrid"
                if engine_type_raw:
                    if "plug-in" in engine_type_raw or "phev" in engine_type_raw:
                        fuel_type_str = "Plug-in Hybrid"
                    elif "hybrid" in engine_type_raw and fuel_type_str not in ["Plug-in Hybrid"]:
                        fuel_type_str = "Hybrid"
                    elif "electric" in engine_type_raw and "hybrid" not in engine_type_raw:
                        fuel_type_str = "Electric"

                # Also check engine string as fallback
                if not fuel_type_str or fuel_type_str == "Regular":
                    engine_lower = engine_str.lower() if engine_str else ""
                    name_lower_check = trim_name.lower()
                    if "electric" in engine_lower or "electric" in name_lower_check:
                        if "hybrid" not in engine_lower and "hybrid" not in name_lower_check:
                            fuel_type_str = "Electric"
                    elif "hybrid" in engine_lower or "hybrid" in name_lower_check:
                        fuel_type_str = "Hybrid"

                # Override fuel type for high-performance engines that obviously need premium
                # API data is sometimes wrong (e.g., says Viper V10 uses regular)
                try:
                    cyl_int = int(cylinders) if cylinders else 0
                    disp_float = float(engine_size) if engine_size else 0
                    hp_int = int(horsepower) if horsepower else 0
                except (ValueError, TypeError):
                    cyl_int, disp_float, hp_int = 0, 0, 0

                # High-performance indicators that require premium:
                # - V10 or V12 engines
                # - Large displacement V8s (5.7L+) with high HP (300+)
                # - Supercharged or turbocharged engines
                # - Any engine with 400+ HP
                is_forced_induction = "supercharg" in name_lower or "turbo" in name_lower
                needs_premium = (
                    cyl_int >= 10 or  # V10, V12
                    is_forced_induction or  # Supercharged/Turbo
                    hp_int >= 400 or  # High HP
                    (cyl_int == 8 and disp_float >= 5.7 and hp_int >= 300) or  # Performance V8
                    (cyl_int == 8 and disp_float >= 6.0)  # Big V8s (6.0L+)
                )

                if needs_premium and fuel_type_str == "Regular":
                    fuel_type_str = "Premium"

                # Build final display with engine - this is what shows in the list
                display_name = brand_trim_name
                if engine_str:
                    full_display = f"{display_name} ({engine_str})"
                else:
                    full_display = display_name

                # Collect unique body styles for this trim
                body_style_options = []
                seen_body_styles = set()
                for variant in variants:
                    bs = variant["body_style"]
                    if bs and bs not in seen_body_styles:
                        seen_body_styles.add(bs)
                        body_style_options.append({
                            "name": bs,
                            "full_name": variant["full_name"]
                        })

                processed_trims.append({
                    "id": trim_name,  # Use first variant's full name as default ID
                    "name": display_name,
                    "full_name": trim_name,
                    "display_name": full_display,
                    "engine": engine_str,
                    "transmission": trans_str,
                    "drivetrain": drive_str,
                    "msrp": trim_data.get("base_msrp", ""),
                    "body_style": first_variant["body_style"],  # Default body style
                    "body_style_options": body_style_options,  # All available body styles
                    "has_body_style_choice": len(body_style_options) > 1,
                    "fuel_type": fuel_type_str,  # Use parsed fuel type
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

            # Find the best image - prefer official stock photos
            best_image = None
            best_score = -9999

            for img in images:
                score = 0
                width = img.get("width", 0)
                height = img.get("height", 0)

                # Prefer larger images
                score += (width * height) / 10000

                # Prefer PNGs (usually cleaner stock photos)
                if img.get("mime") == "image/png":
                    score += 50

                link = img.get("link", "").lower()

                # Prefer images from known good automotive sources
                if "kelley" in link or "kbb" in link:
                    score += 500
                elif "evox" in link:
                    score += 400
                elif "chrome" in link or "cstatic" in link:
                    score += 300
                elif "autobytel" in link:
                    score += 200

                # Avoid bad sources (game screenshots, user uploads, etc.)
                if "wikia" in link or "fandom" in link:
                    score -= 1000  # Game wiki/Forza screenshots
                if "redd.it" in link or "reddit" in link:
                    score -= 500   # User uploads
                if "ebay" in link:
                    score -= 300   # eBay listings
                if "forza" in link:
                    score -= 1000  # Game screenshots

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
            # Check main trim ID
            matched = trim.get("id") == vehicle_id or trim.get("full_name") == vehicle_id

            # Also check body_style_options for matching full_name
            if not matched and trim.get("body_style_options"):
                for body_opt in trim["body_style_options"]:
                    if body_opt.get("full_name") == vehicle_id:
                        matched = True
                        break

            if matched:
                # Extract year/make/model from cache key
                # Format: trims_2023_dodge_challenger
                parts = cache_key.split("_")
                if len(parts) >= 4:
                    year = parts[1]
                    make = parts[2].title()
                    model = " ".join(parts[3:]).title()

                    engine_str = trim.get("engine", "")

                    # Parse displacement from engine string like "8.0L V10"
                    displacement = 0
                    disp_match = re.search(r'(\d+\.?\d*)L', engine_str)
                    if disp_match:
                        try:
                            displacement = float(disp_match.group(1))
                        except:
                            pass

                    # Parse cylinders from engine string
                    cylinders = 0
                    cyl_match = re.search(r'V(\d+)|I(\d+)|(\d+)-cyl', engine_str)
                    if cyl_match:
                        try:
                            cylinders = int(cyl_match.group(1) or cyl_match.group(2) or cyl_match.group(3))
                        except:
                            pass

                    # Check for forced induction
                    engine_lower = engine_str.lower()
                    is_supercharged = "supercharged" in engine_lower or "supercharger" in engine_lower
                    is_turbocharged = "turbo" in engine_lower

                    return {
                        "vehicle_id": vehicle_id,
                        "year": year,
                        "make": make,
                        "model": model,
                        "trim": trim.get("name", ""),
                        "full_name": f"{year} {make} {model} {trim.get('name', '')}",
                        "engine": engine_str,
                        "displacement": displacement,
                        "cylinders": cylinders,
                        "supercharged": is_supercharged,
                        "turbocharged": is_turbocharged,
                        "transmission": trim.get("transmission", ""),
                        "drive": trim.get("drivetrain", ""),
                        "fuel_type": trim.get("fuel_type", ""),
                        "mpg_city": trim.get("mpg_city", ""),
                        "mpg_highway": trim.get("mpg_highway", ""),
                        "msrp": trim.get("msrp", ""),
                        "horsepower": trim.get("horsepower", ""),
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


async def decode_obd_code(code: str) -> dict:
    """
    Decode an OBD-II trouble code using CarsXE OBD Codes Decoder API.
    Returns official diagnosis information for the code.

    Args:
        code: OBD-II code like "P0420", "P0300", etc.

    Returns:
        dict with 'code', 'diagnosis', 'success' fields
    """
    cache = load_cache()
    cache_key = f"obd_{code.upper()}"

    # Check cache (codes don't change, cache indefinitely)
    if "obd_codes" not in cache:
        cache["obd_codes"] = {}

    if cache_key in cache["obd_codes"]:
        print(f"[CarsXE] Using cached OBD decode for {code}")
        return cache["obd_codes"][cache_key]

    print(f"[CarsXE] Decoding OBD code {code}...")

    try:
        url = f"{CARSXE_BASE}/obdcodesdecoder"
        params = {
            "key": CARSXE_API_KEY,
            "code": code.upper()
        }

        async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
            response = await client.get(url, params=params)

            if response.status_code != 200:
                print(f"[CarsXE] OBD API error: {response.status_code}")
                return {"success": False, "code": code, "diagnosis": ""}

            data = response.json()

            result = {
                "success": data.get("success", False),
                "code": data.get("code", code),
                "diagnosis": data.get("diagnosis", ""),
                "cached_at": datetime.now().isoformat()
            }

            # Cache successful results
            if result["success"] and result["diagnosis"]:
                cache["obd_codes"][cache_key] = result
                save_cache(cache)
                print(f"[CarsXE] Decoded {code}: {result['diagnosis'][:60]}...")

            return result

    except Exception as e:
        print(f"[CarsXE] OBD decode error: {type(e).__name__}: {e}")
        return {"success": False, "code": code, "diagnosis": ""}


async def decode_obd_codes_batch(codes: list) -> dict:
    """
    Decode multiple OBD-II codes efficiently.
    Returns dict mapping code -> diagnosis info.

    Args:
        codes: List of OBD-II codes like ["P0420", "P0300"]

    Returns:
        dict mapping each code to its decode result
    """
    import asyncio

    results = {}

    # Decode all codes concurrently
    tasks = [decode_obd_code(code) for code in codes]
    decoded = await asyncio.gather(*tasks)

    for code, result in zip(codes, decoded):
        results[code.upper()] = result

    return results


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
