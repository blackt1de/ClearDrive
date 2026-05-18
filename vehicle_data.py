"""
Vehicle Data Lookup using CarsXE API
Clean, accurate vehicle data including trims, specs, and images.
"""

import httpx
import json
import os
import re
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

CACHE_FILE = Path(__file__).parent / "vehicle_cache.json"
CARSXE_API_KEY = os.environ.get("CARSXE_API_KEY", "")
CARSXE_BASE = "https://api.carsxe.com"

# Auto.dev API for high-quality vehicle images
AUTODEV_API_KEY = os.environ.get("AUTODEV_API_KEY", "")
AUTODEV_BASE = "https://api.auto.dev"

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "ClearDrive/1.2"
}


IMAGE_CACHE_VERSION = 28  # Bump this to invalidate all cached images (v28: Mercedes-AMG normalization)
TRIMS_CACHE_VERSION = 9   # Bump this to invalidate all cached trims (v9: Mercedes-AMG normalization)
VIN_CACHE_VERSION = 3     # Bump this to invalidate all cached VIN decodes (v3: Mercedes-AMG normalization)

# Canonical SAE J2012 OBD-II code definitions are now loaded from
# ml/data/sae_j2012.json (built by ml/scripts/build_sae_j2012.py — ~418 entries).
# CarsXE's /obdcodesdecoder returns wrong descriptions for most codes
# (verification: 8/10 wrong, 6 of those exact -1 offsets — see
# notes/2026-05-18-carsxe-independent-verification.md). The JSON is consulted
# first; CarsXE is fallback only, with WARNING-level logging on each fallback.
#
# `_CANONICAL_OBD_CODES_FALLBACK` below is a tiny in-code subset, used only if
# the JSON file is missing or unreadable at import time. The full lookup is
# `_get_canonical_obd_lookup()`.
_CANONICAL_OBD_CODES_FALLBACK = {
    # VVT / Camshaft / Crankshaft timing
    "P0010": '"A" Camshaft Position Actuator Circuit (Bank 1)',
    "P0011": '"A" Camshaft Position - Timing Over-Advanced or System Performance (Bank 1)',
    "P0013": '"B" Camshaft Position - Actuator Circuit (Bank 1)',
    "P0014": '"B" Camshaft Position - Timing Over-Advanced or System Performance (Bank 1)',
    "P0015": '"B" Camshaft Position - Timing Over-Retarded (Bank 1)',
    "P0016": "Crankshaft Position - Camshaft Position Correlation (Bank 1 Sensor A)",
    # Mass Air Flow / Intake / Coolant temperature sensors
    "P0101": "Mass or Volume Air Flow Sensor 'A' Circuit Range/Performance",
    "P0102": "Mass or Volume Air Flow Sensor 'A' Circuit Low Input",
    "P0113": "Intake Air Temperature Sensor 1 Circuit High Input",
    "P0117": "Engine Coolant Temperature Sensor 1 Circuit Low Input",
    "P0128": "Coolant Thermostat (Coolant Temperature Below Thermostat Regulating Temperature)",
    # Oxygen sensors (heaters + voltage)
    "P0131": "O2 Sensor Circuit Low Voltage (Bank 1, Sensor 1)",
    "P0135": "O2 Sensor Heater Circuit Malfunction (Bank 1, Sensor 1)",
    "P0141": "O2 Sensor Heater Circuit Malfunction (Bank 1, Sensor 2)",
    # Fuel trim
    "P0171": "System Too Lean (Bank 1)",
    # Misfire family
    "P0300": "Random/Multiple Cylinder Misfire Detected",
    "P0301": "Cylinder 1 Misfire Detected",
    "P0302": "Cylinder 2 Misfire Detected",
    "P0303": "Cylinder 3 Misfire Detected",
    "P0304": "Cylinder 4 Misfire Detected",
    "P0305": "Cylinder 5 Misfire Detected",
    "P0306": "Cylinder 6 Misfire Detected",
    "P0307": "Cylinder 7 Misfire Detected",
    "P0308": "Cylinder 8 Misfire Detected",
    # Knock / Camshaft position sensors
    "P0325": "Knock Sensor 1 Circuit Malfunction (Bank 1 or Single Sensor)",
    "P0340": "Camshaft Position Sensor 'A' Circuit (Bank 1 or Single Sensor)",
    "P0345": "Camshaft Position Sensor 'A' Circuit (Bank 2)",
    # EGR / Secondary Air Injection
    "P0401": "Exhaust Gas Recirculation Flow Insufficient Detected",
    "P0411": "Secondary Air Injection System Incorrect Flow Detected",
    # Catalyst efficiency
    "P0420": "Catalyst System Efficiency Below Threshold (Bank 1)",
    "P0421": "Warm Up Catalyst Efficiency Below Threshold (Bank 1)",
    # Evaporative emissions
    "P0440": "Evaporative Emission Control System Malfunction",
    "P0441": "Evaporative Emission Control System Incorrect Purge Flow",
    "P0442": "Evaporative Emission Control System Leak Detected (Small Leak)",
    "P0446": "Evaporative Emission Control System Vent Control Circuit Malfunction",
    "P0455": "Evaporative Emission Control System Leak Detected (Large Leak)",
    "P0456": "Evaporative Emission Control System Leak Detected (Very Small Leak)",
    # Vehicle speed / idle / oil pressure
    "P0500": "Vehicle Speed Sensor 'A' Malfunction",
    "P0506": "Idle Air Control System RPM Lower Than Expected",
    "P0507": "Idle Air Control System RPM Higher Than Expected",
    "P0521": "Engine Oil Pressure Sensor/Switch Range/Performance",
    # Internal control module / processor
    "P0601": "Internal Control Module Memory Check Sum Error",
    "P0603": "Internal Control Module Keep Alive Memory (KAM) Error",
    "P0604": "Internal Control Module Random Access Memory (RAM) Error",
    "P0605": "Internal Control Module Read Only Memory (ROM) Error",
    "P0606": "ECM/PCM Processor",
    # Transmission
    "P0700": "Transmission Control System (MIL Request)",
    "P0715": "Input/Turbine Speed Sensor Circuit Malfunction",
    "P0730": "Incorrect Gear Ratio",
    "P0740": "Torque Converter Clutch Circuit Malfunction",
    "P0750": "Shift Solenoid 'A' Malfunction",
}

# --- Canonical DTC lookup (JSON-backed) + CarsXE fallback telemetry ----------

import logging
from collections import deque

_OBD_LOG = logging.getLogger("cleardrive.obd")

_SAE_J2012_PATH = Path(__file__).parent / "ml" / "data" / "sae_j2012.json"
_CANONICAL_OBD_LOOKUP: dict[str, str] | None = None
# Sliding-window log of CarsXE fallback events (timestamps + codes). Bounded
# by both maxlen and the 24h window enforced in get_dtc_stats().
_CARSXE_FALLBACKS: deque = deque(maxlen=10000)


def _get_canonical_obd_lookup() -> dict[str, str]:
    """Lazy load + cache the SAE J2012 canonical code dict from JSON.

    Falls back to the small in-code dict if the JSON is missing/unreadable
    (e.g., in an environment that hasn't run ml/scripts/build_sae_j2012.py).
    """
    global _CANONICAL_OBD_LOOKUP
    if _CANONICAL_OBD_LOOKUP is not None:
        return _CANONICAL_OBD_LOOKUP
    try:
        with open(_SAE_J2012_PATH, encoding="utf-8") as fh:
            records = json.load(fh)
        _CANONICAL_OBD_LOOKUP = {r["code"]: r["description"] for r in records}
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        _OBD_LOG.warning(
            "Failed to load %s (%r); falling back to in-code dict of %d entries.",
            _SAE_J2012_PATH, e, len(_CANONICAL_OBD_CODES_FALLBACK),
        )
        _CANONICAL_OBD_LOOKUP = dict(_CANONICAL_OBD_CODES_FALLBACK)
    return _CANONICAL_OBD_LOOKUP


def get_dtc_stats() -> dict:
    """Stats for /health/dtc — canonical-lookup size + CarsXE fallback count (24h)."""
    lookup = _get_canonical_obd_lookup()
    cutoff = datetime.now().timestamp() - 24 * 3600
    recent = [(ts, code) for ts, code in _CARSXE_FALLBACKS if ts >= cutoff]
    fallback_codes = sorted({code for _, code in recent})
    return {
        "canonical_entries": len(lookup),
        "canonical_source": str(_SAE_J2012_PATH) if _CANONICAL_OBD_LOOKUP is not None and _SAE_J2012_PATH.exists() else "in-code fallback dict",
        "carsxe_fallback_count_24h": len(recent),
        "carsxe_fallback_codes_24h": fallback_codes[:50],
    }


def _record_carsxe_fallback(code: str) -> None:
    _CARSXE_FALLBACKS.append((datetime.now().timestamp(), code.upper()))
    _OBD_LOG.warning(
        "decode_obd_code: %s not in canonical SAE J2012 lookup; falling back to CarsXE", code
    )


def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r") as f:
                cache = json.load(f)
                needs_save = False

                # Check if image cache needs to be invalidated due to version change
                if cache.get("image_cache_version", 1) < IMAGE_CACHE_VERSION:
                    print(f"[Cache] Clearing old image cache (version {cache.get('image_cache_version', 1)} -> {IMAGE_CACHE_VERSION})")
                    cache["images"] = {}
                    cache["image_cache_version"] = IMAGE_CACHE_VERSION
                    needs_save = True

                # Check if trims cache needs to be invalidated due to version change
                if cache.get("trims_cache_version", 1) < TRIMS_CACHE_VERSION:
                    print(f"[Cache] Clearing old trims cache (version {cache.get('trims_cache_version', 1)} -> {TRIMS_CACHE_VERSION})")
                    cache["trims"] = {}
                    cache["trims_cache_version"] = TRIMS_CACHE_VERSION
                    needs_save = True

                if needs_save:
                    save_cache(cache)
                return cache
        except:
            pass
    return {"vehicles": {}, "trims": {}, "images": {}, "image_cache_version": IMAGE_CACHE_VERSION, "trims_cache_version": TRIMS_CACHE_VERSION, "last_updated": None}


def save_cache(data: dict):
    data["last_updated"] = datetime.now().isoformat()
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)


async def get_vehicle_trims(year: str, make: str, model: str) -> list:
    """
    Get all available trims for a vehicle using CarsXE API.
    Returns a list of trim dicts with detailed specs.
    """
    # Normalize Mercedes-AMG make to Mercedes-Benz for API query
    original_make = make
    if make.lower() in ["mercedes-amg", "mercedesamg", "mercedes amg"]:
        make = "Mercedes-Benz"
        print(f"[CarsXE] Normalized Mercedes-AMG make for trims: {original_make} -> {make}")

    # Handle AMG in model name (e.g., "AMG E53" -> "E53")
    original_model = model
    if model.lower().startswith("amg "):
        model = model[4:].strip()
        print(f"[CarsXE] Normalized AMG model for trims: {original_model} -> {model}")

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
            # Log raw trim names for debugging
            for t in trim_options[:5]:
                print(f"[CarsXE] Raw trim: {t.get('name', '')}")

            # VALIDATION & FILTERING: Filter out trims that don't match the requested model
            # CarsXE sometimes returns mixed model data (e.g., GLE trims mixed with E-Class)
            model_lower = model.lower().replace("-", "").replace(" ", "")
            model_base = model_lower.replace("class", "").replace("series", "")  # "eclass" -> "e", "3series" -> "3"

            # Known model identifiers by brand that appear at start of trim names
            # These are models where CarsXE has been known to mix data
            known_model_prefixes = {
                # Mercedes models (most problematic - CarsXE mixes these frequently)
                "mercedes": ["gle", "glc", "gls", "glb", "gla", "cla", "cls", "slk", "slc", "amg", "eqe", "eqs", "eqb", "eqa",
                             "s", "c", "e", "a", "b", "g"],
                # BMW models
                "bmw": ["x1", "x2", "x3", "x4", "x5", "x6", "x7", "z4", "i3", "i4", "i5", "i7", "ix",
                        "m2", "m3", "m4", "m5", "m8", "228", "230", "320", "328", "330", "340", "430", "440",
                        "520", "530", "540", "740", "750", "840", "850"],
                # Audi models
                "audi": ["a3", "a4", "a5", "a6", "a7", "a8", "q3", "q4", "q5", "q7", "q8", "e-tron", "etron",
                         "rs3", "rs4", "rs5", "rs6", "rs7", "s3", "s4", "s5", "s6", "s7", "s8", "tt", "r8"],
                # Ford - Mustang vs Mach-E issue
                "ford": ["mustang", "mach-e", "mache", "f-150", "f150", "bronco", "explorer", "escape", "edge"],
            }

            # Determine which brand's model list to use
            make_lower = make.lower().replace("-", "").replace(" ", "")
            brand_models = []
            if "mercedes" in make_lower or "benz" in make_lower:
                brand_models = known_model_prefixes.get("mercedes", [])
            elif "bmw" in make_lower:
                brand_models = known_model_prefixes.get("bmw", [])
            elif "audi" in make_lower:
                brand_models = known_model_prefixes.get("audi", [])
            elif "ford" in make_lower:
                brand_models = known_model_prefixes.get("ford", [])

            def trim_matches_model(trim_name: str) -> bool:
                """Check if a trim name matches the requested model."""
                trim_lower = trim_name.lower()
                trim_words = trim_lower.split()
                if not trim_words:
                    return True  # Can't determine, keep it

                first_word = trim_words[0]
                trim_clean = trim_lower.replace("-", "").replace(" ", "")

                # === FORD SPECIAL CASE ===
                # Mustang vs Mach-E: Mach-E trims are "4dr Hatchback" with "electric"
                # Regular Mustang trims are "2dr Coupe/Convertible" with gas engines
                if "ford" in make_lower:
                    if "mustang" in model_lower and "mach" not in model_lower:
                        # Searching for regular Mustang - filter out Mach-E
                        if "electric" in trim_lower or "hatchback" in trim_lower:
                            return False
                    elif "mach" in model_lower:
                        # Searching for Mach-E - filter out regular Mustang
                        if "coupe" in trim_lower or "convertible" in trim_lower:
                            return False

                # === BMW SPECIAL CASE ===
                # BMW trims like "330i", "M340i" should match "3 Series"
                # Check if trim starts with the series number
                if "bmw" in make_lower:
                    # Extract series number from model (e.g., "3" from "3 Series")
                    series_match = re.match(r'^(\d+)', model_base)
                    if series_match:
                        series_num = series_match.group(1)
                        # Check if first word starts with this series number
                        # "330i" starts with "3", "m340i" -> check "340" which starts with "3"
                        if first_word.startswith(series_num):
                            return True
                        # Handle M-prefixed (e.g., "M340i" - the "340" part)
                        if first_word.startswith("m") and len(first_word) > 1:
                            rest = first_word[1:]
                            if rest.startswith(series_num):
                                return True
                        # If first word is a known BMW model that doesn't match our series, filter it
                        first_digit = re.match(r'^(\d)', first_word)
                        if first_digit and first_digit.group(1) != series_num:
                            return False

                # === MERCEDES SPECIAL CASE ===
                # For AMG models like "AMG E 53" - check second word
                if "mercedes" in make_lower or "benz" in make_lower:
                    if first_word == "amg" and len(trim_words) > 1:
                        second_word = trim_words[1]
                        # Check if second word exactly matches our model (e.g., "e" for E-Class)
                        return second_word == model_base

                    # If first word is a known Mercedes model prefix
                    if first_word in brand_models:
                        return first_word == model_base or first_word.startswith(model_base)

                # === AUDI SPECIAL CASE ===
                # Audi trims like "Premium", "Prestige" don't have model in name
                # Most Audi trim data from CarsXE is clean, so minimal filtering needed
                # Only filter if trim explicitly starts with a different model
                if "audi" in make_lower:
                    # Check if first word is a different Audi model
                    audi_models = ["a3", "a4", "a5", "a6", "a7", "a8", "q3", "q4", "q5", "q7", "q8", "rs3", "rs4", "rs5", "rs6", "rs7", "s3", "s4", "s5", "s6", "s7", "tt", "r8", "e-tron", "etron"]
                    if first_word in audi_models and first_word != model_base:
                        return False

                return True  # Unknown format, keep it

            # Filter trims to only those matching our model
            original_count = len(trim_options)
            trim_options = [t for t in trim_options if trim_matches_model(t.get("name", ""))]
            filtered_count = original_count - len(trim_options)

            if filtered_count > 0:
                print(f"[CarsXE] Filtered out {filtered_count} trims that didn't match model '{model}'")

            if not trim_options:
                print(f"[CarsXE] No matching trims after filtering for {year} {make} {model}")
                return []

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

                # Extract transmission from trim name (e.g., "6M" = 6-speed Manual, "6A" = 6-speed Auto)
                transmission_from_name = ""
                name_lower_trans = trim_name.lower()

                # Check for DCT/dual-clutch first (e.g., "7DCT", "7-speed DCT", "M DCT")
                dct_match = re.search(r'(\d+)[\s-]?(?:speed\s+)?(?:dct|dual[\s-]?clutch|m[\s-]?dct|s[\s-]?tronic|pdk)', name_lower_trans)
                if dct_match:
                    transmission_from_name = f"{dct_match.group(1)}-Speed DCT"
                elif "dct" in name_lower_trans or "dual clutch" in name_lower_trans or "dual-clutch" in name_lower_trans:
                    transmission_from_name = "DCT (Dual-Clutch)"
                elif "pdk" in name_lower_trans:
                    transmission_from_name = "PDK (Dual-Clutch)"
                elif "s-tronic" in name_lower_trans or "s tronic" in name_lower_trans:
                    transmission_from_name = "S-Tronic (Dual-Clutch)"
                elif "smg" in name_lower_trans:
                    # BMW Sequential Manual Gearbox
                    smg_match = re.search(r'(\d+)[\s-]?(?:speed\s+)?smg', name_lower_trans)
                    if smg_match:
                        transmission_from_name = f"{smg_match.group(1)}-Speed SMG"
                    else:
                        transmission_from_name = "SMG (Sequential)"
                # Check for CVT/eCVT (common in hybrids like Prius)
                elif "ecvt" in name_lower_trans or "e-cvt" in name_lower_trans:
                    transmission_from_name = "eCVT (Electronic CVT)"
                elif "cvt" in name_lower_trans:
                    transmission_from_name = "CVT"
                else:
                    # Standard patterns from trim names like "(3.0L 6cyl Turbo 8AM)"
                    # - "6M" = 6-speed Manual
                    # - "6A" = 6-speed Automatic
                    # - "8AM" = 8-speed Automated Manual (DCT/PDK)

                    # Check for Automated Manual first (e.g., "8AM" = DCT/PDK)
                    am_match = re.search(r'(\d+)AM\b', trim_name)
                    if am_match:
                        transmission_from_name = f"{am_match.group(1)}-Speed DCT"
                    else:
                        # Check for plain Manual (e.g., "7M") - must NOT be followed by another letter
                        manual_match = re.search(r'(\d+)M\b(?!T)', trim_name)  # M but not MT (manual transmission)
                        if manual_match:
                            transmission_from_name = f"{manual_match.group(1)}-Speed Manual"
                        else:
                            # Check for Automatic (e.g., "8A")
                            auto_match = re.search(r'(\d+)A\b(?!M)', trim_name)  # A but not AM
                            if auto_match:
                                transmission_from_name = f"{auto_match.group(1)}-Speed Automatic"
                            else:
                                # Try alternate patterns like "6-spd man" or "auto"
                                if re.search(r'\bmanual\b', trim_name, re.I):
                                    transmission_from_name = "Manual"
                                elif re.search(r'\bauto\b|\bautomatic\b', trim_name, re.I):
                                    transmission_from_name = "Automatic"

                # Add to group
                if brand_trim_name not in trim_groups:
                    trim_groups[brand_trim_name] = []
                trim_groups[brand_trim_name].append({
                    "full_name": trim_name,
                    "body_style": body_style_from_name,
                    "transmission": transmission_from_name,
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
                torque = ""
                fuel_type_raw = trim_data.get("fuel_type", "")
                drivetrain_raw = trim_data.get("drivetrain", "")
                engine_type_raw = ""  # For hybrid/electric detection

                # MPG and fuel info
                mpg_city = ""
                mpg_highway = ""
                mpg_combined = ""
                tank_capacity = ""

                # Colors
                colors_exterior = []
                colors_interior = []
                color_data = trim_data.get("color", {})
                if color_data:
                    for color in color_data.get("exterior", []):
                        colors_exterior.append({
                            "name": color.get("name", ""),
                            "rgb": color.get("rgb", "")
                        })
                    for color in color_data.get("interior", []):
                        colors_interior.append({
                            "name": color.get("name", ""),
                            "rgb": color.get("rgb", "")
                        })

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
                            elif "torque" in fname and not torque:
                                # Extract from "420 lb-ft @ 4600 rpm"
                                match = re.search(r'(\d+)\s*lb', fvalue)
                                if match:
                                    torque = match.group(1)
                            elif "engine type" in fname and not engine_type_raw:
                                # Capture engine type (e.g., "hybrid", "electric")
                                engine_type_raw = fvalue.lower()

                        elif cat_name == "Fuel":
                            if "fuel type" in fname and not fuel_type_raw:
                                fuel_type_raw = fvalue
                            elif "city/highway mpg" in fname or "epa city/highway" in fname:
                                # Parse "15/24 MPG" -> city=15, highway=24
                                match = re.search(r'(\d+)/(\d+)', fvalue)
                                if match:
                                    mpg_city = match.group(1)
                                    mpg_highway = match.group(2)
                            elif "combined mpg" in fname or "epa combined" in fname:
                                # Parse "18 MPG"
                                match = re.search(r'(\d+)', fvalue)
                                if match:
                                    mpg_combined = match.group(1)
                            elif "tank capacity" in fname or "fuel tank" in fname:
                                # Parse "16.0 gal."
                                match = re.search(r'(\d+\.?\d*)', fvalue)
                                if match:
                                    tank_capacity = match.group(1)

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
                elif "turbo" in name_lower or re.search(r'\d+\.?\d*t\b', name_lower):
                    # Detect "turbo" keyword or "2.0T", "3.0T" patterns
                    engine_str += " Turbo"

                if horsepower:
                    engine_str += f" ({horsepower} hp)"

                engine_str = engine_str.strip()

                # Extract transmission - check API field and features
                transmission = trim_data.get("transmission", "")
                transmission_from_features = ""

                # Check features.standard for transmission info
                for category in features:
                    cat_name = category.get("category", "")
                    if cat_name == "Drive Train":
                        for feature in category.get("features", []):
                            fname = feature.get("name", "").lower()
                            fvalue = feature.get("value", "") or ""
                            if "transmission" in fname and fvalue:
                                transmission_from_features = fvalue
                                break

                # Use features transmission if API field is empty
                if not transmission and transmission_from_features:
                    transmission = transmission_from_features

                trans_str = ""
                if transmission:
                    trans_lower = transmission.lower()
                    speed_match = re.search(r'(\d+)[\s-]?speed', transmission, re.IGNORECASE)
                    speed_prefix = f"{speed_match.group(1)}-Speed " if speed_match else ""

                    # Check for DCT/dual-clutch variants first
                    if "dct" in trans_lower or "dual clutch" in trans_lower or "dual-clutch" in trans_lower:
                        trans_str = f"{speed_prefix}DCT (Dual-Clutch)" if speed_prefix else "DCT (Dual-Clutch)"
                    elif "pdk" in trans_lower:
                        trans_str = f"{speed_prefix}PDK (Dual-Clutch)" if speed_prefix else "PDK (Dual-Clutch)"
                    elif "s-tronic" in trans_lower or "s tronic" in trans_lower:
                        trans_str = f"{speed_prefix}S-Tronic (Dual-Clutch)" if speed_prefix else "S-Tronic (Dual-Clutch)"
                    elif "smg" in trans_lower:
                        trans_str = f"{speed_prefix}SMG (Sequential)" if speed_prefix else "SMG (Sequential)"
                    # Check for CVT/eCVT (common in hybrids)
                    elif "ecvt" in trans_lower or "e-cvt" in trans_lower:
                        trans_str = "eCVT (Electronic CVT)"
                    elif "cvt" in trans_lower:
                        trans_str = "CVT"
                    # Standard automatic/manual
                    elif "automatic" in trans_lower:
                        trans_str = f"{speed_prefix}Automatic" if speed_prefix else "Automatic"
                    elif "manual" in trans_lower:
                        trans_str = f"{speed_prefix}Manual" if speed_prefix else "Manual"
                    else:
                        # Unknown type - clean it up
                        trans_str = transmission.strip()

                # Infer transmission for hybrids/electrics if still blank
                if not trans_str:
                    # Check if this is a hybrid - they typically use eCVT
                    fuel_lower = fuel_type_raw.lower() if fuel_type_raw else ""
                    engine_type_lower = engine_type_raw.lower() if engine_type_raw else ""
                    name_check = trim_name.lower()

                    if "hybrid" in fuel_lower or "hybrid" in engine_type_lower or "hybrid" in name_check:
                        trans_str = "eCVT (Electronic CVT)"
                    elif "electric" in fuel_lower or "electric" in engine_type_lower or "ev" in name_check:
                        trans_str = "Single-Speed (Electric)"
                    elif "prius" in name_check:
                        # Prius always uses eCVT
                        trans_str = "eCVT (Electronic CVT)"

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

                # Collect unique transmissions for this trim
                transmission_options = []
                seen_transmissions = set()

                # First, collect from name-parsed variants
                for variant in variants:
                    trans = variant.get("transmission", "")
                    if trans and trans not in seen_transmissions:
                        seen_transmissions.add(trans)
                        # Build label based on transmission type
                        trans_lower = trans.lower()
                        if "dct" in trans_lower or "dual" in trans_lower or "pdk" in trans_lower or "s-tronic" in trans_lower:
                            label = "DCT (Automatic)"
                        elif "cvt" in trans_lower:
                            label = "CVT"
                        elif "auto" in trans_lower:
                            label = "Automatic"
                        elif "manual" in trans_lower:
                            label = "Manual"
                        else:
                            label = trans
                        transmission_options.append({
                            "name": trans,
                            "label": label
                        })

                # If no transmissions found from name parsing, use the API's transmission field
                if not transmission_options and trans_str:
                    trans_lower = trans_str.lower()
                    if "dct" in trans_lower or "dual" in trans_lower or "pdk" in trans_lower or "s-tronic" in trans_lower:
                        label = "DCT (Automatic)"
                    elif "cvt" in trans_lower:
                        label = "CVT"
                    elif "auto" in trans_lower:
                        label = "Automatic"
                    elif "manual" in trans_lower:
                        label = "Manual"
                    else:
                        label = trans_str
                    transmission_options.append({
                        "name": trans_str,
                        "label": label
                    })
                    seen_transmissions.add(trans_str)

                # Check features.optional for additional transmission options
                # CarsXE lists alternative transmissions as optional mechanical features
                optional_features = trim_data.get("features", {}).get("optional", [])
                for category in optional_features:
                    cat_name = category.get("category", "").lower()
                    if "mechanical" in cat_name or "drivetrain" in cat_name or "powertrain" in cat_name:
                        for feature in category.get("features", []):
                            fname = feature.get("name", "")
                            fname_lower = fname.lower()
                            # Look for transmission options - check for "transmission" or known trans types
                            is_transmission = (
                                "transmission" in fname_lower or
                                "pdk" in fname_lower or  # Porsche PDK
                                "doppelkupplung" in fname_lower or  # Porsche PDK German name
                                "s-tronic" in fname_lower or  # Audi DCT
                                "dct" in fname_lower or  # Generic DCT
                                "smg" in fname_lower or  # BMW SMG
                                "dual clutch" in fname_lower or
                                "dual-clutch" in fname_lower
                            )
                            if is_transmission:
                                # Parse the transmission name
                                opt_trans = ""
                                opt_label = ""

                                # Extract speed if present (e.g., "10-Speed")
                                speed_match = re.search(r'(\d+)[\s-]?speed', fname_lower)
                                speed_prefix = f"{speed_match.group(1)}-Speed " if speed_match else ""

                                if "dct" in fname_lower or "dual" in fname_lower or "clutch" in fname_lower:
                                    opt_trans = f"{speed_prefix}DCT"
                                    opt_label = "DCT (Automatic)"
                                elif "pdk" in fname_lower:
                                    opt_trans = f"{speed_prefix}PDK"
                                    opt_label = "PDK (Automatic)"
                                elif "cvt" in fname_lower:
                                    opt_trans = "CVT"
                                    opt_label = "CVT"
                                elif "automatic" in fname_lower or "auto" in fname_lower:
                                    opt_trans = f"{speed_prefix}Automatic"
                                    opt_label = "Automatic"
                                elif "manual" in fname_lower:
                                    opt_trans = f"{speed_prefix}Manual"
                                    opt_label = "Manual"
                                else:
                                    # Use the feature name as-is but clean it up
                                    opt_trans = fname.replace("Transmission", "").strip()
                                    opt_label = "Automatic" if "select" in fname_lower else opt_trans

                                # Add if not already seen
                                if opt_trans and opt_trans not in seen_transmissions:
                                    seen_transmissions.add(opt_trans)
                                    transmission_options.append({
                                        "name": opt_trans,
                                        "label": opt_label
                                    })
                                    print(f"[CarsXE] Found optional transmission: {opt_trans} (from '{fname}')")

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
                    "transmission_options": transmission_options,  # All available transmissions
                    "has_transmission_choice": len(transmission_options) > 1,
                    "fuel_type": fuel_type_str,  # Use parsed fuel type
                    "mpg_city": mpg_city,
                    "mpg_highway": mpg_highway,
                    "mpg_combined": mpg_combined,
                    "tank_capacity": tank_capacity,
                    "horsepower": horsepower,
                    "torque": torque,
                    "colors_exterior": colors_exterior,
                    "colors_interior": colors_interior,
                    "is_truck": trim_data.get("is_truck", False),
                    "is_electric": trim_data.get("is_electric", False),
                    "is_plugin_hybrid": trim_data.get("is_plugin_electric", False),
                    "raw_data": trim_data  # Keep full data for reference
                })
                # Log transmission options for debugging
                print(f"[CarsXE] Trim '{trim_name}': {len(transmission_options)} trans options: {[t['label'] for t in transmission_options]}")

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


async def get_autodev_image(year: str, make: str, model: str, trim: str = "") -> dict:
    """
    Get vehicle images using Auto.dev API.
    1. Search listings by year/make/model to find VINs
    2. Use VIN to get high-quality photos

    Returns dict with image URL and metadata, or empty dict if not found.
    """
    if not AUTODEV_API_KEY:
        print("[Auto.dev] No API key configured, skipping")
        return {}

    print(f"[Auto.dev] Fetching image for {year} {make} {model} {trim}...")

    try:
        # Step 1: Search vehicle listings to find a VIN
        # Note: Using auto.dev/api/listings (not api.auto.dev) and simple param names
        # Don't pass trim as a filter - it's too restrictive. We'll score by trim instead.
        search_url = "https://auto.dev/api/listings"
        search_params = {
            "apiKey": AUTODEV_API_KEY,
            "year": year,
            "make": make,
            "model": model,
        }

        print(f"[Auto.dev] Searching listings: {year} {make} {model} {trim}")

        async with httpx.AsyncClient(headers=HEADERS, timeout=20) as client:
            response = await client.get(search_url, params=search_params)

            if response.status_code != 200:
                print(f"[Auto.dev] Listings search error: {response.status_code}")
                # Try to read error message
                try:
                    error_data = response.json()
                    print(f"[Auto.dev] Error details: {error_data}")
                except:
                    pass
                return {}

            data = response.json()
            records = data.get("records", [])

            if not records:
                print(f"[Auto.dev] No listings found for {year} {make} {model}")
                return {}

            print(f"[Auto.dev] Found {len(records)} listings")

            # Find a listing with photos, prefer one matching year/make/model/trim
            best_listing = None
            best_score = -1

            for listing in records:
                vin = listing.get("vin", "")
                photo_urls = listing.get("photoUrls", [])
                primary_photo = listing.get("primaryPhotoUrl", "")
                listing_trim = listing.get("trim", "")
                listing_year = str(listing.get("year", ""))
                listing_make = listing.get("make", "").lower()
                listing_model = listing.get("model", "").lower()

                # Skip listings without images
                if not primary_photo and not photo_urls:
                    continue

                # CRITICAL: Skip if year doesn't match (API sometimes returns wrong vehicles)
                if listing_year != year:
                    print(f"[Auto.dev] Skipping wrong year ({listing_year} vs {year}): {listing_make} {listing_model}")
                    continue

                # Skip if make doesn't match
                if listing_make != make.lower():
                    print(f"[Auto.dev] Skipping wrong make ({listing_make} vs {make})")
                    continue

                # Skip if model doesn't match
                if listing_model != model.lower():
                    print(f"[Auto.dev] Skipping wrong model ({listing_model} vs {model})")
                    continue

                # Base score on number of photos
                score = len(photo_urls) if photo_urls else (1 if primary_photo else 0)

                # Bonus for matching trim
                if trim and listing_trim and trim.lower() in listing_trim.lower():
                    score += 100

                if score > best_score:
                    best_score = score
                    best_listing = listing

                print(f"[Auto.dev] Listing: VIN={vin[:8]}... trim={listing_trim} photos={len(photo_urls)}")

            if not best_listing:
                print("[Auto.dev] No listings with images found")
                return {}

            vin = best_listing.get("vin", "")
            primary_photo = best_listing.get("primaryPhotoUrl", "")
            photo_urls = best_listing.get("photoUrls", [])

            # Use the best available photo URL
            # photoUrls contains high-res versions, primaryPhotoUrl is also good
            if photo_urls:
                # Get full-size version (remove width param to get original)
                image_url = photo_urls[0]
                # Try to get full resolution by removing size params
                if "?io=true" in image_url:
                    # Get base URL without resize params
                    base_url = image_url.split("?")[0]
                    image_url = base_url
                print(f"[Auto.dev] Got {len(photo_urls)} photos, using first")
                print(f"[Auto.dev] Selected: {image_url[:80]}...")
                return {
                    "url": image_url,
                    "width": 1024,  # These are typically 1024x768
                    "height": 768,
                    "thumbnail": primary_photo,
                    "source": "auto.dev",
                    "vin": vin,
                    "cached_at": datetime.now().isoformat()
                }

            # Fallback: use primaryPhotoUrl from listing
            if primary_photo:
                print(f"[Auto.dev] Using primary photo from listing: {primary_photo[:80]}...")
                return {
                    "url": primary_photo,
                    "width": 1024,
                    "height": 768,
                    "thumbnail": "",
                    "source": "auto.dev",
                    "vin": vin,
                    "cached_at": datetime.now().isoformat()
                }

            return {}

    except httpx.TimeoutException:
        print("[Auto.dev] Request timed out")
        return {}
    except Exception as e:
        print(f"[Auto.dev] Error: {type(e).__name__}: {e}")
        return {}


async def get_vehicle_image(year: str, make: str, model: str, trim: str = "", color: str = None) -> dict:
    """
    Get a vehicle image - tries Auto.dev first, falls back to CarsXE.
    Returns dict with image URL and metadata.

    Args:
        year: Vehicle year
        make: Vehicle make (e.g., "Dodge")
        model: Vehicle model (e.g., "Charger")
        trim: Optional trim level (e.g., "SE", "Scat Pack") for more accurate images
        color: Optional color name (e.g., "blue", "Glacier White") for color-specific images
    """
    # Normalize Mercedes-AMG make to Mercedes-Benz for image search
    if make.lower() in ["mercedes-amg", "mercedesamg", "mercedes amg"]:
        make = "Mercedes-Benz"
        # Add AMG to trim if not already there
        if "amg" not in (trim or "").lower() and "amg" not in (model or "").lower():
            trim = f"AMG {trim}".strip() if trim else "AMG"
        print(f"[Image] Normalized Mercedes-AMG for search: {make} {model} {trim}")

    # Handle AMG in model name (e.g., "AMG E53" -> "E53")
    if model.lower().startswith("amg "):
        model = model[4:].strip()
        if "amg" not in (trim or "").lower():
            trim = f"AMG {trim}".strip()
        print(f"[Image] Normalized AMG model for search: {model} trim={trim}")

    cache = load_cache()
    # Include color in cache key if provided
    cache_key = f"image_{year}_{make}_{model}_{trim}_{color or ''}".lower().replace(" ", "_")

    # Check cache (30-day expiry for images)
    if cache_key in cache.get("images", {}):
        cached = cache["images"][cache_key]
        cached_time = datetime.fromisoformat(cached.get("cached_at", "2000-01-01"))
        if (datetime.now() - cached_time).days < 30:
            source = cached.get("source", "carsxe")
            print(f"[{source}] Using cached image for {year} {make} {model} {trim}")
            return cached

    # Use CarsXE for stock images (Auto.dev has dealer photos which look unprofessional)
    print(f"[CarsXE] Fetching stock image for {year} {make} {model} {trim} color={color or 'none'}...")

    try:
        # Note: Images API doesn't use /v1/ prefix
        url = f"{CARSXE_BASE}/images"
        # First try: request transparent images only
        params = {
            "key": CARSXE_API_KEY,
            "year": year,
            "make": make,
            "model": model,
            "transparent": "true"       # Only transparent background images
        }

        # Add trim if provided for more accurate image matching
        if trim:
            params["trim"] = trim

        # Add color if provided for color-specific images
        if color:
            params["color"] = color

        print(f"[CarsXE] Image API params: {params}")

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
            print(f"[CarsXE] API returned {len(images)} images")

            # Log all images for debugging
            for i, img in enumerate(images[:10]):  # Log first 10
                w, h = img.get("width", 0), img.get("height", 0)
                link = img.get("link", "")[:80]
                thumb = img.get("thumbnailLink", "")[:80]
                source = img.get("source", "")
                print(f"[CarsXE] Image {i+1}: {w}x{h} source={source}")
                print(f"[CarsXE]   Link: {link}...")
                print(f"[CarsXE]   Thumb: {thumb}...")

            if not images:
                print(f"[CarsXE] No images found for {year} {make} {model}")
                return {}

            # Find the best image - prefer official stock photos that match year/trim
            best_image = None
            best_score = -9999

            for img in images:
                score = 0
                width = img.get("width", 0)
                height = img.get("height", 0)

                # CRITICAL: Require minimum resolution - skip tiny images entirely
                if width < 600 or height < 300:
                    print(f"[CarsXE] Skipping small image ({width}x{height}): {img.get('link', '')[:50]}...")
                    continue

                # Heavily prefer larger images - resolution is critical
                score += (width * height) / 5000  # Double the weight for size

                # Bonus for high-res images (800+ width)
                if width >= 800:
                    score += 500
                if width >= 1000:
                    score += 300  # Additional bonus for very high res

                # Prefer PNGs (usually cleaner stock photos with transparency)
                if img.get("mime") == "image/png":
                    score += 100

                link = img.get("link", "").lower()

                # CRITICAL: Check if image matches the requested year
                # This is the MOST important factor - wrong year = wrong car appearance
                year_in_link = year in link
                wrong_year_found = False

                # Check if a different year appears in the URL
                year_match = re.search(r'20\d{2}|19\d{2}', link)
                if year_match:
                    found_year = year_match.group()
                    if found_year == year:
                        year_in_link = True
                    elif found_year != year:
                        wrong_year_found = True
                        try:
                            year_diff = abs(int(found_year) - int(year))
                            # SKIP images with wrong year entirely if diff > 3 years
                            # A 2024 Challenger looks COMPLETELY different from 2008
                            if year_diff > 3:
                                print(f"[CarsXE] SKIPPING wrong year ({found_year} vs {year}, diff={year_diff}): {link[:60]}...")
                                continue  # Skip this image entirely
                            else:
                                # Small year diff (1-3 years) - penalize but allow
                                score -= 1000 + (year_diff * 300)
                                print(f"[CarsXE] Wrong year ({found_year} vs {year}, diff={year_diff}): {link[:60]}...")
                        except:
                            print(f"[CarsXE] SKIPPING unparseable year: {link[:60]}...")
                            continue

                if year_in_link:
                    score += 2000  # Big bonus for matching year
                    print(f"[CarsXE] Year matches {year}: {link[:60]}...")
                elif not wrong_year_found:
                    # No year in URL - might be generic, allow but no bonus
                    print(f"[CarsXE] No year in URL: {link[:60]}...")

                # CRITICAL: Check if model appears in URL - reject wrong models
                model_lower = model.lower().replace(" ", "").replace("-", "")
                link_clean = link.replace("-", "").replace("_", "").replace(" ", "")

                # For multi-word models like "Land Cruiser", check various formats
                model_variations = [model_lower]
                if " " in model:
                    model_variations.append(model.lower().replace(" ", "-"))
                    model_variations.append(model.lower().replace(" ", "_"))
                    model_variations.append(model.lower().replace(" ", ""))
                    # Also individual words for models like "Land Cruiser"
                    model_words = model.lower().split()
                    if len(model_words) >= 2:
                        model_variations.append(model_words[-1])  # Just "cruiser"

                model_in_link = any(mv in link_clean for mv in model_variations)
                if model_in_link:
                    score += 1000  # Bonus for matching model
                    print(f"[CarsXE] Model matches {model}: {link[:60]}...")
                else:
                    # Model NOT in URL - check if ANY other known model name is in the link
                    # This catches the color-matching-wrong-car issue
                    other_models = [
                        # Toyota
                        "tacoma", "tundra", "camry", "corolla", "rav4", "highlander",
                        "4runner", "sequoia", "sienna", "prius", "supra", "avalon",
                        "venza", "chr", "mirai", "yaris", "86", "gr86",
                        # Other makes - common models
                        "civic", "accord", "crv", "pilot", "odyssey",  # Honda
                        "mustang", "f150", "f-150", "explorer", "escape", "bronco",  # Ford
                        "silverado", "tahoe", "suburban", "equinox", "malibu", "camaro", "corvette",  # Chevy
                        "wrangler", "cherokee", "gladiator", "compass",  # Jeep
                        "charger", "challenger", "durango", "ram",  # Dodge/Ram
                        "altima", "maxima", "sentra", "pathfinder", "rogue", "frontier", "titan",  # Nissan
                        "outback", "forester", "crosstrek", "impreza", "wrx", "brz",  # Subaru
                        "cx5", "cx9", "mazda3", "mazda6", "miata", "mx5",  # Mazda
                        "elantra", "sonata", "tucson", "santafe", "palisade", "kona",  # Hyundai
                        "optima", "sorento", "sportage", "telluride", "stinger",  # Kia
                        "3series", "5series", "x3", "x5", "m3", "m5",  # BMW
                        "cclass", "eclass", "sclass", "glc", "gle", "amg",  # Mercedes
                        "a4", "a6", "q5", "q7", "rs", "s4",  # Audi
                    ]
                    other_models_found = [m for m in other_models if m in link_clean and m not in model_lower]
                    if other_models_found:
                        print(f"[CarsXE] SKIPPING wrong model ({other_models_found[0]} vs {model}): {link[:60]}...")
                        continue  # Skip entirely if wrong model detected

                    # If no model name found in URL at all, heavily penalize (might be generic/wrong)
                    score -= 800
                    print(f"[CarsXE] No model in URL (penalized): {link[:60]}...")

                # Check if trim appears in the link (e.g., "srt", "rt", "se")
                if trim:
                    trim_lower = trim.lower().replace(" ", "").replace("-", "")
                    # Also check common variations
                    trim_variations = [trim_lower]
                    if trim_lower == "r/t" or trim_lower == "rt":
                        trim_variations.extend(["rt", "r_t", "r-t"])
                    elif trim_lower == "srt8" or trim_lower == "srt-8":
                        trim_variations.extend(["srt8", "srt_8", "srt-8", "srt"])

                    link_clean = link.replace("-", "").replace("_", "")
                    if any(tv in link_clean for tv in trim_variations):
                        score += 500  # Bonus for matching trim
                        print(f"[CarsXE] Image matches trim {trim}: {link[:60]}...")

                # CRITICAL: Avoid Cloudflare-protected CDNs that block our proxy
                # These will always fail and fall back to low-quality thumbnails
                cf_blocked_domains = [
                    "sbacdn.com", "chromedata.com", "jdpower.com",
                    "dealerinspire.com", "tirerack.com", "cstatic.com",
                    "cdn-sba", "azurefd.net"
                ]
                if any(domain in link for domain in cf_blocked_domains):
                    score -= 3000  # Heavily penalize - these won't load
                    print(f"[CarsXE] CF-blocked domain detected: {link[:50]}...")

                # Prefer images from accessible sources
                if "groovecar" in link:
                    # Groovecar works but has white backgrounds - use as last resort
                    score -= 500
                elif "evox" in link:
                    score += 400
                elif "kelley" in link or "kbb" in link:
                    score += 300
                elif "autobytel" in link:
                    score += 200

                # CRITICAL: Skip part/accessory images (wheels, rims, tires, etc.)
                part_keywords = ["wheel", "rim", "tire", "brake", "exhaust", "bumper",
                                 "headlight", "taillight", "mirror", "grille", "spoiler",
                                 "interior", "dashboard", "steering", "seat", "trunk",
                                 "engine-bay", "underbody", "closeup", "close-up", "detail"]
                if any(pk in link for pk in part_keywords):
                    print(f"[CarsXE] SKIPPING part/detail image: {link[:60]}...")
                    continue  # Skip entirely - not a full car image

                # Avoid bad sources (game screenshots, user uploads)
                if "wikia" in link or "fandom" in link:
                    score -= 1000  # Game wiki/Forza screenshots
                if "redd.it" in link or "reddit" in link:
                    score -= 500   # User uploads
                if "ebay" in link:
                    score -= 300   # eBay listings
                if "forza" in link:
                    score -= 1000  # Game screenshots

                # Penalize low-res cropped versions
                if "cropmedium" in link or "cropsmall" in link:
                    score -= 300   # Low-res cropped versions

                # Prefer sources known for transparent/clean images
                if "evox" in link and "transparent" in link:
                    score += 800  # EVOX transparent images are excellent

                if score > best_score:
                    best_score = score
                    best_image = img

            if not best_image:
                best_image = images[0]  # Fallback to first

            print(f"[CarsXE] Selected image with score {best_score}: {best_image.get('link', '')[:60]}...")

            image_url = best_image.get("link", "")

            # Try to upgrade groovecar images to higher resolution
            if "groovecar" in image_url.lower():
                # Try upgrading from cropsmall/cropmedium to croplarge
                if "cropsmall" in image_url:
                    upgraded_url = image_url.replace("cropsmall", "croplarge")
                    print(f"[CarsXE] Upgrading groovecar from cropsmall to croplarge")
                    image_url = upgraded_url
                elif "cropmedium" in image_url:
                    upgraded_url = image_url.replace("cropmedium", "croplarge")
                    print(f"[CarsXE] Upgrading groovecar from cropmedium to croplarge")
                    image_url = upgraded_url

            result = {
                "url": image_url,
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
    Get vehicle details by ID (which is the trim's full name or year_make_model format).
    Parses from cached trim data.
    """
    cache = load_cache()

    # Check if vehicle_id is in "year_make_model" format (e.g., "2015_audi_a4")
    # If so, try to find a matching cache entry and use the first/best trim
    year_make_model_match = re.match(r'^(\d{4})_([a-z]+)_(.+)$', vehicle_id.lower())
    if year_make_model_match:
        target_year = year_make_model_match.group(1)
        target_make = year_make_model_match.group(2)
        target_model = year_make_model_match.group(3).replace("_", " ")
        cache_key = f"trims_{target_year}_{target_make}_{target_model.replace(' ', '_')}"
        print(f"[VehicleData] Looking up by year_make_model: {cache_key}")

        if cache_key in cache.get("trims", {}):
            cached_data = cache["trims"][cache_key]
            trims = cached_data.get("options", [])
            if trims:
                # Use the first trim as default
                trim = trims[0]
                engine_str = trim.get("engine", "")
                engine_lower = engine_str.lower()
                trim_name_lower = trim.get("name", "").lower() + " " + trim.get("full_name", "").lower()
                combined_check = engine_lower + " " + trim_name_lower

                is_supercharged = "supercharged" in combined_check or "supercharger" in combined_check or "s/c" in combined_check
                is_turbocharged = (
                    "turbo" in combined_check or
                    bool(re.search(r'\d+\.?\d*t\b', combined_check))
                )

                print(f"[VehicleData] Found via year_make_model: {trim.get('name')} turbo={is_turbocharged} super={is_supercharged}")

                # Parse displacement
                displacement = 0
                disp_match = re.search(r'(\d+\.?\d*)L', engine_str)
                if disp_match:
                    try:
                        displacement = float(disp_match.group(1))
                    except:
                        pass

                return {
                    "vehicle_id": vehicle_id,
                    "year": target_year,
                    "make": target_make.title(),
                    "model": target_model.title(),
                    "trim": trim.get("name", ""),
                    "full_name": f"{target_year} {target_make.title()} {target_model.title()} {trim.get('name', '')}",
                    "engine": engine_str,
                    "displacement": displacement,
                    "cylinders": 0,
                    "supercharged": is_supercharged,
                    "turbocharged": is_turbocharged,
                    "transmission": trim.get("transmission", "") or (trim.get("transmission_options", [{}])[0].get("name", "") if trim.get("transmission_options") else ""),
                    "drive": trim.get("drivetrain", ""),
                    "fuel_type": trim.get("fuel_type", ""),
                    "mpg_city": trim.get("mpg_city", ""),
                    "mpg_highway": trim.get("mpg_highway", ""),
                    "mpg_combined": trim.get("mpg_combined", ""),
                    "tank_capacity": trim.get("tank_capacity", ""),
                    "torque": trim.get("torque", ""),
                    "msrp": trim.get("msrp", ""),
                    "horsepower": trim.get("horsepower", ""),
                    "raw_data": trim.get("raw_data", {})
                }

    # Search through cached trims to find this vehicle by trim ID or full_name
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

                    # Check for forced induction - check engine string AND trim name
                    engine_lower = engine_str.lower()
                    trim_name_lower = trim.get("name", "").lower() + " " + trim.get("full_name", "").lower()
                    combined_check = engine_lower + " " + trim_name_lower

                    is_supercharged = "supercharged" in combined_check or "supercharger" in combined_check or "s/c" in combined_check
                    # Check for "turbo" keyword or "2.0T" pattern (common in Audi/VW/BMW)
                    is_turbocharged = (
                        "turbo" in combined_check or
                        bool(re.search(r'\d+\.?\d*t\b', combined_check))  # Matches "2.0t", "3.0t", etc.
                    )

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
                        "transmission": trim.get("transmission", "") or (trim.get("transmission_options", [{}])[0].get("name", "") if trim.get("transmission_options") else ""),
                        "drive": trim.get("drivetrain", ""),
                        "fuel_type": trim.get("fuel_type", ""),
                        "mpg_city": trim.get("mpg_city", ""),
                        "mpg_highway": trim.get("mpg_highway", ""),
                        "mpg_combined": trim.get("mpg_combined", ""),
                        "tank_capacity": trim.get("tank_capacity", ""),
                        "torque": trim.get("torque", ""),
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
    code_upper = code.upper()

    # Canonical SAE J2012 (loaded from ml/data/sae_j2012.json). Wins over
    # cache and CarsXE. CarsXE is known to return wrong descriptions for
    # at least 60% of standardized codes — see
    # notes/2026-05-18-carsxe-independent-verification.md.
    canonical = _get_canonical_obd_lookup()
    if code_upper in canonical:
        return {
            "success": True,
            "code": code_upper,
            "diagnosis": canonical[code_upper],
            "cached_at": datetime.now().isoformat(),
            "source": "canonical_sae_j2012",
        }

    # Fallback: CarsXE. Log the event for /health/dtc telemetry.
    _record_carsxe_fallback(code_upper)

    cache = load_cache()
    cache_key = f"obd_{code_upper}"

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


def format_engine_string(raw_engine: str, displacement: str = "", cylinders: str = "") -> str:
    """
    Clean up engine string to display format like "2.0L I4 Turbo" or "5.0L V8".

    Converts OEM strings like "2.0L L4 DOHC 16V TURBO" to cleaner format.
    """
    if not raw_engine:
        return ""

    raw = raw_engine.upper()

    # Extract displacement if not provided
    disp = ""
    import re
    disp_match = re.search(r'(\d+\.?\d*)\s*L', raw)
    if disp_match:
        disp = f"{disp_match.group(1)}L"
    elif displacement:
        # Try to convert from cc or other formats
        try:
            if "." in str(displacement):
                disp = f"{displacement}L"
            else:
                # Assume cc, convert to liters
                cc = float(displacement)
                if cc > 100:  # It's in cc
                    disp = f"{cc/1000:.1f}L"
                else:
                    disp = f"{displacement}L"
        except:
            disp = str(displacement)

    # Determine cylinder configuration
    config = ""
    if "V8" in raw or cylinders == "8":
        config = "V8"
    elif "V6" in raw or cylinders == "6":
        config = "V6"
    elif "V10" in raw or cylinders == "10":
        config = "V10"
    elif "V12" in raw or cylinders == "12":
        config = "V12"
    elif "I4" in raw or "L4" in raw or "4CYL" in raw or "INLINE-4" in raw or "INLINE 4" in raw or cylinders == "4":
        config = "I4"
    elif "I5" in raw or "L5" in raw or cylinders == "5":
        config = "I5"
    elif "I6" in raw or "L6" in raw or "INLINE-6" in raw or "INLINE 6" in raw or cylinders == "6":
        config = "I6"
    elif "I3" in raw or "L3" in raw or cylinders == "3":
        config = "I3"
    elif "W12" in raw:
        config = "W12"
    elif "FLAT" in raw or "BOXER" in raw:
        config = f"Flat-{cylinders}" if cylinders else "Flat"
    elif "ROTARY" in raw or "WANKEL" in raw:
        config = "Rotary"

    # Check for forced induction
    forced = ""
    if "TWIN TURBO" in raw or "TWINTURBO" in raw or "TT" in raw:
        forced = "Twin-Turbo"
    elif "TURBO" in raw:
        forced = "Turbo"
    elif re.search(r'\d+\.?\d*T\b', raw):
        # Detect "2.0T", "3.0T" patterns (common for Audi/VW/BMW turbo designations)
        forced = "Turbo"
    elif "SUPERCHARG" in raw or "S/C" in raw:
        forced = "Supercharged"
    elif "ELECTRIC" in raw:
        forced = "Electric"
    elif "HYBRID" in raw:
        forced = "Hybrid"

    # Build clean string
    parts = [p for p in [disp, config, forced] if p]
    return " ".join(parts) if parts else raw_engine


def format_transmission_string(raw_trans: str) -> str:
    """
    Clean up transmission string to readable format.

    Converts "8sp auto" to "8-Speed Automatic", "6MT" to "6-Speed Manual", etc.
    """
    if not raw_trans:
        return ""

    # Strip parentheses and extra whitespace
    raw = raw_trans.strip().strip('()').upper()

    # Extract number of speeds
    import re
    speed_match = re.search(r'(\d+)\s*(?:SP|SPD|SPEED|-SPEED)', raw)
    speeds = speed_match.group(1) if speed_match else ""

    # If no speed found, try just a number at the start
    if not speeds:
        num_match = re.search(r'^(\d+)', raw)
        if num_match:
            speeds = num_match.group(1)

    # Determine type
    trans_type = ""
    if "CVT" in raw:
        trans_type = "CVT"
        speeds = ""  # CVT doesn't have discrete speeds
    elif "DCT" in raw or "DUAL CLUTCH" in raw or "PDK" in raw or "DSG" in raw:
        trans_type = "Dual-Clutch"
    elif "MANUAL" in raw or "MT" in raw or "M/T" in raw:
        trans_type = "Manual"
    elif "AUTO" in raw or "AT" in raw or "A/T" in raw:
        trans_type = "Automatic"
    elif "SMG" in raw or "SEQUENTIAL" in raw:
        trans_type = "Sequential"
    else:
        # Default to automatic if unclear
        trans_type = "Automatic"

    # Build clean string
    if speeds and trans_type != "CVT":
        return f"{speeds}-Speed {trans_type}"
    elif trans_type:
        return trans_type
    else:
        return raw_trans


def format_drive_string(raw_drive: str) -> str:
    """Clean up drive type string."""
    if not raw_drive:
        return ""

    raw = raw_drive.upper()

    if "AWD" in raw or "ALL WHEEL" in raw or "ALL-WHEEL" in raw:
        return "AWD"
    elif "4WD" in raw or "4X4" in raw or "FOUR WHEEL" in raw or "FOUR-WHEEL" in raw:
        return "4WD"
    elif "FWD" in raw or "FRONT WHEEL" in raw or "FRONT-WHEEL" in raw or "FF" in raw:
        return "FWD"
    elif "RWD" in raw or "REAR WHEEL" in raw or "REAR-WHEEL" in raw or "FR" in raw:
        return "RWD"

    return raw_drive


def format_fuel_type(raw_fuel: str) -> str:
    """Clean up fuel type string."""
    if not raw_fuel:
        return ""

    raw = raw_fuel.upper()

    if "ELECTRIC" in raw and "HYBRID" not in raw:
        return "Electric"
    elif "PLUG" in raw or "PHEV" in raw:
        return "Plug-in Hybrid"
    elif "HYBRID" in raw:
        return "Hybrid"
    elif "DIESEL" in raw:
        return "Diesel"
    elif "FLEX" in raw or "E85" in raw:
        return "Flex Fuel"
    elif "PREMIUM" in raw:
        return "Premium Gasoline"
    elif "GAS" in raw or "PETROL" in raw or "UNLEADED" in raw:
        return "Gasoline"

    return raw_fuel


async def decode_vin_nhtsa(vin: str) -> dict:
    """
    Fallback VIN decode using free NHTSA API.
    Used when CarsXE doesn't have data (e.g., very new models).

    Args:
        vin: 17-character Vehicle Identification Number

    Returns:
        dict with basic vehicle info, or empty dict if failed
    """
    print(f"[NHTSA] Trying fallback VIN decode for {vin}...")

    try:
        url = f"https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/{vin}?format=json"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)

            if response.status_code != 200:
                print(f"[NHTSA] HTTP error: {response.status_code}")
                return {}

            data = response.json()
            results = data.get("Results", [])

            if not results:
                print("[NHTSA] No results returned")
                return {}

            vehicle = results[0]

            # Check for decode errors
            error_code = vehicle.get("ErrorCode", "")
            if error_code and error_code != "0":
                print(f"[NHTSA] Decode error: {vehicle.get('ErrorText', 'Unknown')}")
                # Still try to use partial data

            year = vehicle.get("ModelYear", "")
            make = vehicle.get("Make", "")
            model = vehicle.get("Model", "")
            trim = vehicle.get("Trim", "")
            series = vehicle.get("Series", "")

            # NHTSA often puts trim info in Series for luxury brands
            if series and not trim:
                trim = series
            elif series and trim:
                trim = f"{series} {trim}"

            # Normalize Mercedes-AMG
            if make.lower() in ["mercedes-amg", "mercedesamg"]:
                make = "Mercedes-Benz"
                if "amg" not in trim.lower() and "amg" not in model.lower():
                    trim = f"AMG {trim}".strip() if trim else "AMG"

            # Handle AMG in model name
            if model.lower().startswith("amg "):
                model = model[4:].strip()
                if "amg" not in trim.lower():
                    trim = f"AMG {trim}".strip()

            # Engine info
            engine_size = vehicle.get("DisplacementL", "")
            cylinders = vehicle.get("EngineCylinders", "")
            engine_config = vehicle.get("EngineConfiguration", "")
            fuel_type = vehicle.get("FuelTypePrimary", "")
            drive_type = vehicle.get("DriveType", "")
            transmission = vehicle.get("TransmissionStyle", "")
            body_style = vehicle.get("BodyClass", "")

            # Build engine string
            engine_str = ""
            if engine_size:
                engine_str = f"{engine_size}L"
            if cylinders:
                try:
                    cyl = int(cylinders)
                    if cyl >= 6:
                        engine_str += f" V{cyl}"
                    elif cyl == 4:
                        engine_str += " I4"
                    else:
                        engine_str += f" {cyl}-cyl"
                except:
                    pass

            # Check for turbo/supercharger
            forced_induction = vehicle.get("Turbo", "") or vehicle.get("EngineConfiguration", "")
            if "turbo" in str(forced_induction).lower():
                engine_str += " Turbo"
            elif "supercharg" in str(forced_induction).lower():
                engine_str += " Supercharged"

            if not year or not make or not model:
                print(f"[NHTSA] Incomplete data: year={year} make={make} model={model}")
                return {}

            print(f"[NHTSA] ✓ Decoded: {year} {make} {model} {trim}")
            return {
                "success": True,
                "source": "nhtsa",
                "vin": vin,
                "year": str(year),
                "make": make,
                "model": model,
                "trim": trim.strip() if trim else "",
                "engine": engine_str.strip(),
                "cylinders": str(cylinders) if cylinders else "",
                "displacement": str(engine_size) if engine_size else "",
                "drive_type": format_drive_string(drive_type),
                "transmission": format_transmission_string(transmission),
                "fuel_type": format_fuel_type(fuel_type),
                "body_style": body_style,
                "is_turbo": "turbo" in str(forced_induction).lower(),
                "is_supercharged": "supercharg" in str(forced_induction).lower(),
            }

    except Exception as e:
        print(f"[NHTSA] Error: {type(e).__name__}: {e}")
        return {}


async def decode_vin(vin: str) -> dict:
    """
    Decode a VIN using CarsXE VIN Decoder API, with NHTSA fallback.
    Returns vehicle information including year, make, model, trim, engine specs.

    Args:
        vin: 17-character Vehicle Identification Number

    Returns:
        dict with keys: success, year, make, model, trim, engine, etc.
        Returns {"success": False} if decode fails or VIN is invalid
    """
    if not vin or len(vin) != 17:
        print(f"[CarsXE] Invalid VIN length: {len(vin) if vin else 0}")
        return {"success": False, "error": "Invalid VIN"}

    vin = vin.upper().strip()
    cache = load_cache()

    # Check cache - VIN decodes never expire
    if "vin_decodes" not in cache:
        cache["vin_decodes"] = {}

    # Invalidate old VIN cache if version changed
    if cache.get("vin_cache_version", 1) < VIN_CACHE_VERSION:
        print(f"[Cache] Clearing old VIN cache (version {cache.get('vin_cache_version', 1)} -> {VIN_CACHE_VERSION})")
        cache["vin_decodes"] = {}
        cache["vin_cache_version"] = VIN_CACHE_VERSION
        save_cache(cache)

    if vin in cache["vin_decodes"]:
        cached = cache["vin_decodes"][vin]
        # Only use cache if it was successful - retry errors
        if cached.get("success", False):
            print(f"[CarsXE] Using cached VIN decode for {vin}")
            return cached
        else:
            print(f"[CarsXE] Skipping cached error for {vin}, retrying...")

    print(f"[CarsXE] Decoding VIN {vin}...")

    try:
        url = f"{CARSXE_BASE}/specs"
        params = {
            "key": CARSXE_API_KEY,
            "vin": vin
        }

        print(f"[CarsXE] Request URL: {url}")
        print(f"[CarsXE] Request params: vin={vin}")

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params, headers=HEADERS)

            print(f"[CarsXE] Response status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                print(f"[CarsXE] Response type: {type(data)}")
                print(f"[CarsXE] Response preview: {str(data)[:500]}")

                # Handle different response formats from CarsXE
                vehicle = None

                # Format 1: List of vehicles (expected for specs endpoint)
                if isinstance(data, list) and len(data) > 0:
                    vehicle = data[0]
                    print(f"[CarsXE] Found vehicle in list format")
                # Format 2: Object with data array
                elif isinstance(data, dict):
                    if data.get("data") and isinstance(data["data"], list) and len(data["data"]) > 0:
                        vehicle = data["data"][0]
                        print(f"[CarsXE] Found vehicle in data array")
                    # Format 3: Direct object with vehicle fields
                    elif data.get("year") or data.get("make") or data.get("model"):
                        vehicle = data
                        print(f"[CarsXE] Found vehicle as direct object")
                    # Format 4: Check for input/attributes structure (NHTSA-style)
                    elif data.get("input") and data.get("attributes"):
                        attrs = data.get("attributes", {})
                        vehicle = {
                            "year": attrs.get("year", ""),
                            "make": attrs.get("make", ""),
                            "model": attrs.get("model", ""),
                            "trim": attrs.get("trim", ""),
                            "engine": attrs.get("engine", ""),
                            "cylinders": attrs.get("cylinders", ""),
                            "displacement": attrs.get("displacement", ""),
                            "drive": attrs.get("drive_type", ""),
                            "transmission": attrs.get("transmission", ""),
                            "fuel_type": attrs.get("fuel_type", ""),
                            "body": attrs.get("body_style", ""),
                        }
                        print(f"[CarsXE] Found vehicle in attributes format")
                    else:
                        print(f"[CarsXE] Unknown response structure. Keys: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")

                if vehicle:
                    # Log all available fields for debugging
                    print(f"[CarsXE] Raw vehicle data keys: {list(vehicle.keys())}")

                    # Normalize Mercedes-AMG make to Mercedes-Benz
                    # CarsXE sometimes returns "Mercedes-AMG" as the make for AMG models
                    raw_make = vehicle.get("make", "")
                    raw_model = vehicle.get("model", "")
                    raw_trim = vehicle.get("trim", "")

                    if raw_make.lower() in ["mercedes-amg", "mercedesamg", "mercedes amg"]:
                        print(f"[CarsXE] Normalizing Mercedes-AMG make: {raw_make} -> Mercedes-Benz")
                        vehicle["make"] = "Mercedes-Benz"
                        # Add AMG to trim if not already there
                        if "amg" not in raw_trim.lower() and "amg" not in raw_model.lower():
                            vehicle["trim"] = f"AMG {raw_trim}".strip() if raw_trim else "AMG"
                            print(f"[CarsXE] Added AMG to trim: {vehicle['trim']}")

                    # Also handle case where model contains "AMG" designation (e.g., "AMG E53")
                    # Normalize to model without prefix, add AMG to trim
                    if raw_model.lower().startswith("amg "):
                        normalized_model = raw_model[4:].strip()  # Remove "AMG " prefix
                        vehicle["model"] = normalized_model
                        if "amg" not in (vehicle.get("trim", "") or "").lower():
                            vehicle["trim"] = f"AMG {vehicle.get('trim', '')}".strip()
                        print(f"[CarsXE] Normalized AMG model: {raw_model} -> {normalized_model}, trim: {vehicle.get('trim', '')}")

                    # Extract and clean engine string
                    raw_engine = vehicle.get("engine", "")
                    cylinders = vehicle.get("cylinders", "")
                    displacement = vehicle.get("displacement", "")

                    # Build clean engine string: "2.0L I4 Turbo" format
                    engine_clean = format_engine_string(raw_engine, displacement, cylinders)

                    # Extract and clean transmission
                    raw_transmission = vehicle.get("transmission", "")
                    transmission_clean = format_transmission_string(raw_transmission)

                    # Extract drive type and clean it
                    raw_drive = vehicle.get("drive", "") or vehicle.get("drivetrain", "") or vehicle.get("drive_type", "")
                    drive_clean = format_drive_string(raw_drive)

                    # Extract fuel type
                    raw_fuel = vehicle.get("fuel_type", "") or vehicle.get("fuel", "")
                    fuel_clean = format_fuel_type(raw_fuel)

                    # Check for turbo/supercharger in engine string AND trim name
                    engine_lower = raw_engine.lower()
                    trim_lower = vehicle.get("trim", "").lower()
                    combined_text = engine_lower + " " + trim_lower
                    is_turbo = (
                        "turbo" in combined_text or
                        bool(re.search(r'\d+\.?\d*t\b', combined_text))  # "2.0T", "3.0T" patterns
                    )
                    is_supercharged = "supercharg" in combined_text or "s/c" in combined_text
                    print(f"[CarsXE] VIN turbo check: engine='{raw_engine}' trim='{vehicle.get('trim', '')}' turbo={is_turbo} super={is_supercharged}")

                    # Extract MPG data
                    mpg_city = vehicle.get("mpg_city", "") or vehicle.get("city_mpg", "") or ""
                    mpg_highway = vehicle.get("mpg_highway", "") or vehicle.get("highway_mpg", "") or ""
                    mpg_combined = vehicle.get("mpg_combined", "") or vehicle.get("combined_mpg", "") or ""

                    # Extract tank capacity
                    tank_capacity = vehicle.get("fuel_tank_capacity", "") or vehicle.get("tank_size", "") or ""

                    # Extract horsepower/torque
                    horsepower = vehicle.get("horsepower", "") or vehicle.get("hp", "") or ""
                    torque = vehicle.get("torque", "") or ""

                    result = {
                        "success": True,
                        "vin": vin,
                        "year": str(vehicle.get("year", "")),
                        "make": vehicle.get("make", ""),
                        "model": vehicle.get("model", ""),
                        "trim": vehicle.get("trim", ""),
                        "engine": engine_clean,
                        "engine_raw": raw_engine,  # Keep raw for debugging
                        "cylinders": cylinders,
                        "displacement": displacement,
                        "drive_type": drive_clean,
                        "transmission": transmission_clean,
                        "fuel_type": fuel_clean,
                        "body_style": vehicle.get("body", "") or vehicle.get("body_style", ""),
                        "is_turbo": is_turbo,
                        "is_supercharged": is_supercharged,
                        "mpg_city": str(mpg_city) if mpg_city else "",
                        "mpg_highway": str(mpg_highway) if mpg_highway else "",
                        "mpg_combined": str(mpg_combined) if mpg_combined else "",
                        "tank_capacity": str(tank_capacity) if tank_capacity else "",
                        "horsepower": str(horsepower) if horsepower else "",
                        "torque": str(torque) if torque else "",
                        "raw_data": vehicle  # Store full response
                    }

                    print(f"[CarsXE] Cleaned engine: '{raw_engine}' -> '{engine_clean}'")

                    # Validate that we have minimum required data
                    has_year = result["year"] and result["year"].isdigit()
                    has_make = result["make"] and len(result["make"]) > 1
                    has_model = result["model"] and len(result["model"]) > 0

                    if not has_year or not has_make or not has_model:
                        print(f"[CarsXE] ⚠ VIN decode incomplete: year={result['year']} make={result['make']} model={result['model']}")
                        result["partial"] = True
                        result["success"] = False  # Mark as failed so app falls back to manual
                        result["error"] = f"Incomplete data: {'no year' if not has_year else ''} {'no make' if not has_make else ''} {'no model' if not has_model else ''}".strip()
                        # Still return the partial data - app can use what it has
                        return result

                    # Cache successful result (never expires)
                    cache["vin_decodes"][vin] = result
                    save_cache(cache)

                    print(f"[CarsXE] ✓ VIN decoded: {result['year']} {result['make']} {result['model']} {result['trim']}")
                    return result
                else:
                    print(f"[CarsXE] No vehicle data found in response for VIN {vin}")
                    print(f"[CarsXE] Full response for debugging: {str(data)[:1000]}")

                    # Try NHTSA fallback
                    print("[CarsXE] Trying NHTSA fallback...")
                    nhtsa_result = await decode_vin_nhtsa(vin)
                    if nhtsa_result and nhtsa_result.get("success"):
                        # Cache the NHTSA result
                        cache["vin_decodes"][vin] = nhtsa_result
                        save_cache(cache)
                        return nhtsa_result

                    # Don't cache errors - allow retry on next request
                    return {"success": False, "vin": vin, "error": "No data found"}
            else:
                print(f"[CarsXE] VIN decode failed: HTTP {response.status_code}")
                try:
                    error_body = response.text[:500]
                    print(f"[CarsXE] Error response: {error_body}")
                except:
                    pass

                # Try NHTSA fallback
                print("[CarsXE] Trying NHTSA fallback...")
                nhtsa_result = await decode_vin_nhtsa(vin)
                if nhtsa_result and nhtsa_result.get("success"):
                    # Cache the NHTSA result
                    cache["vin_decodes"][vin] = nhtsa_result
                    save_cache(cache)
                    return nhtsa_result

                return {"success": False, "vin": vin, "error": f"HTTP {response.status_code}"}

    except Exception as e:
        print(f"[CarsXE] VIN decode error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

        # Try NHTSA fallback
        print("[CarsXE] Trying NHTSA fallback...")
        nhtsa_result = await decode_vin_nhtsa(vin)
        if nhtsa_result and nhtsa_result.get("success"):
            return nhtsa_result

        return {"success": False, "vin": vin, "error": str(e)}


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
