#!/usr/bin/env python3
"""Overnight scraper that populates raw diagnostic training data.

For each combination of the top 50 US-market vehicles (2015-2024) and
the top 15 OBD-II codes, collect raw records from four sources:

  - NHTSA complaintsByVehicle API
  - OBD-Codes.com (generic code description)
  - RepairPal (vehicle common repairs)
  - CarComplaints.com (vehicle complaint narratives)

One JSON file per (vehicle, code) combination is written to
    training_data/raw/{vehicle_slug}/{code}.json
with one top-level key per source. Runs are idempotent: existing output
files are skipped unless --force is passed.

Each upstream source is memoized in-memory by the minimum unique key it
actually varies over (OBD-Codes by code only, the rest by vehicle only),
so total upstream request count is 15 + 3*50 = 165, not 4*750 = 3000.

Progress is logged to both stdout and training_data/scrape.log, so a
run can be inspected in the morning even if the terminal session closed.

Hard-stops after 8 hours regardless of remaining work.
"""

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from code_scraper import (
    scrape_car_complaints,
    scrape_obd_codes,
    scrape_repairpal,
)


# --- Configuration ---------------------------------------------------------

DATA_ROOT = Path(__file__).parent / "training_data"
RAW_DIR = DATA_ROOT / "raw"
LOG_FILE = DATA_ROOT / "scrape.log"

TIMEOUT_SECONDS = 8 * 3600           # hard stop
PER_DOMAIN_COOLDOWN_SECONDS = 3.0    # gap between hits to the same host
INTER_COMBO_DELAY_SECONDS = 1.0      # gap between combinations

HTTP_HEADERS = {
    "User-Agent": (
        "ClearDrive-training-scraper/1.0 "
        "(+research; contact: conorpbrennan@gmail.com)"
    ),
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
}

NHTSA_URL = "https://api.nhtsa.gov/complaints/complaintsByVehicle"

TOP_15_CODES: list[str] = [
    "P0171", "P0300", "P0420", "P0455", "P0301",
    "P0128", "P0411", "P0440", "P0606", "P0700",
    "P0011", "P0016", "P0014", "P0345", "P0102",
]

# 50 representative US-market vehicles spanning model years 2015-2024 and
# a mix of engine types (turbo-4, NA V6, V8, hybrid). If a
# top_50_vehicles.md is ever checked in, load from that instead.
TOP_50_VEHICLES: list[dict[str, Any]] = [
    {"year": 2018, "make": "Ford",        "model": "F-150"},
    {"year": 2019, "make": "Ford",        "model": "F-150"},
    {"year": 2022, "make": "Ford",        "model": "F-150"},
    {"year": 2020, "make": "Chevrolet",   "model": "Silverado 1500"},
    {"year": 2018, "make": "Chevrolet",   "model": "Silverado 1500"},
    {"year": 2019, "make": "Ram",         "model": "1500"},
    {"year": 2021, "make": "Ram",         "model": "1500"},
    {"year": 2019, "make": "Toyota",      "model": "RAV4"},
    {"year": 2020, "make": "Toyota",      "model": "RAV4 Hybrid"},
    {"year": 2018, "make": "Toyota",      "model": "Camry"},
    {"year": 2020, "make": "Toyota",      "model": "Camry Hybrid"},
    {"year": 2019, "make": "Honda",       "model": "CR-V"},
    {"year": 2022, "make": "Honda",       "model": "CR-V Hybrid"},
    {"year": 2020, "make": "Honda",       "model": "Civic"},
    {"year": 2021, "make": "Honda",       "model": "Accord"},
    {"year": 2019, "make": "Honda",       "model": "Accord Hybrid"},
    {"year": 2017, "make": "Toyota",      "model": "Corolla"},
    {"year": 2024, "make": "Toyota",      "model": "Corolla Hybrid"},
    {"year": 2019, "make": "Nissan",      "model": "Altima"},
    {"year": 2018, "make": "Nissan",      "model": "Rogue"},
    {"year": 2020, "make": "Nissan",      "model": "Sentra"},
    {"year": 2019, "make": "Jeep",        "model": "Grand Cherokee"},
    {"year": 2021, "make": "Jeep",        "model": "Grand Cherokee"},
    {"year": 2018, "make": "Jeep",        "model": "Wrangler"},
    {"year": 2022, "make": "Jeep",        "model": "Wrangler 4xe"},
    {"year": 2019, "make": "Jeep",        "model": "Compass"},
    {"year": 2020, "make": "Chevrolet",   "model": "Equinox"},
    {"year": 2018, "make": "Chevrolet",   "model": "Malibu"},
    {"year": 2019, "make": "Hyundai",     "model": "Elantra"},
    {"year": 2021, "make": "Hyundai",     "model": "Tucson"},
    {"year": 2020, "make": "Hyundai",     "model": "Santa Fe"},
    {"year": 2018, "make": "Hyundai",     "model": "Sonata Hybrid"},
    {"year": 2019, "make": "Kia",         "model": "Forte"},
    {"year": 2021, "make": "Kia",         "model": "Sorento"},
    {"year": 2020, "make": "Kia",         "model": "Sportage"},
    {"year": 2015, "make": "Subaru",      "model": "Outback"},
    {"year": 2020, "make": "Subaru",      "model": "Forester"},
    {"year": 2019, "make": "Subaru",      "model": "Impreza"},
    {"year": 2019, "make": "Mazda",       "model": "CX-5"},
    {"year": 2016, "make": "Mazda",       "model": "3"},
    {"year": 2019, "make": "Ford",        "model": "Escape"},
    {"year": 2020, "make": "Ford",        "model": "Explorer"},
    {"year": 2018, "make": "Ford",        "model": "Mustang"},
    {"year": 2019, "make": "Ford",        "model": "Edge"},
    {"year": 2020, "make": "Chevrolet",   "model": "Tahoe"},
    {"year": 2018, "make": "GMC",         "model": "Sierra 1500"},
    {"year": 2019, "make": "Toyota",      "model": "Tacoma"},
    {"year": 2020, "make": "Toyota",      "model": "Tundra"},
    {"year": 2021, "make": "Toyota",      "model": "Highlander"},
    {"year": 2020, "make": "Honda",       "model": "Pilot"},
]
assert len(TOP_50_VEHICLES) == 50, f"expected 50 vehicles, got {len(TOP_50_VEHICLES)}"


# --- Logging ---------------------------------------------------------------

_log_handle = None


def _log_init() -> None:
    global _log_handle
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    _log_handle = LOG_FILE.open("a", encoding="utf-8")


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if _log_handle is not None:
        _log_handle.write(line + "\n")
        _log_handle.flush()


# --- Per-domain rate limiting ---------------------------------------------

_last_hit: dict[str, float] = {}


async def wait_for_domain(domain: str, min_gap: float = PER_DOMAIN_COOLDOWN_SECONDS) -> None:
    """Sleep so the gap since the previous hit to `domain` is at least min_gap."""
    now = time.monotonic()
    elapsed = now - _last_hit.get(domain, 0.0)
    if elapsed < min_gap:
        await asyncio.sleep(min_gap - elapsed)
    _last_hit[domain] = time.monotonic()


# --- Per-run upstream caches ----------------------------------------------

_obd_cache: dict[str, dict] = {}
_nhtsa_cache: dict[str, dict] = {}
_repairpal_cache: dict[str, dict] = {}
_carcomp_cache: dict[str, dict] = {}


def _vkey(make: str, model: str, year: int) -> str:
    return f"{year}|{make.lower()}|{model.lower()}"


async def fetch_nhtsa(client: httpx.AsyncClient, make: str, model: str, year: int) -> dict:
    key = _vkey(make, model, year)
    if key in _nhtsa_cache:
        return _nhtsa_cache[key]
    await wait_for_domain("api.nhtsa.gov")
    try:
        resp = await client.get(
            NHTSA_URL,
            params={"make": make, "model": model, "modelYear": str(year)},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            data = {"raw": data}
    except Exception as e:
        log(f"  NHTSA error for {year} {make} {model}: {e!r}")
        data = {"error": repr(e), "count": 0, "results": []}
    _nhtsa_cache[key] = data
    return data


async def fetch_obd_codes(code: str) -> dict:
    if code in _obd_cache:
        return _obd_cache[code]
    await wait_for_domain("www.obd-codes.com")
    try:
        data = await scrape_obd_codes(code) or {}
    except Exception as e:
        log(f"  OBD-Codes error for {code}: {e!r}")
        data = {"error": repr(e)}
    _obd_cache[code] = data
    return data


async def fetch_repairpal(make: str, model: str, year: int) -> dict:
    key = _vkey(make, model, year)
    if key in _repairpal_cache:
        return _repairpal_cache[key]
    await wait_for_domain("repairpal.com")
    try:
        data = await scrape_repairpal(make, model, str(year)) or {}
    except Exception as e:
        log(f"  RepairPal error for {year} {make} {model}: {e!r}")
        data = {"error": repr(e)}
    _repairpal_cache[key] = data
    return data


async def fetch_carcomplaints(make: str, model: str, year: int) -> dict:
    key = _vkey(make, model, year)
    if key in _carcomp_cache:
        return _carcomp_cache[key]
    await wait_for_domain("www.carcomplaints.com")
    try:
        data = await scrape_car_complaints(make, model, str(year)) or {}
    except Exception as e:
        log(f"  CarComplaints error for {year} {make} {model}: {e!r}")
        data = {"error": repr(e)}
    _carcomp_cache[key] = data
    return data


# --- Per-combo processing --------------------------------------------------

def slug_vehicle(vehicle: dict) -> str:
    raw = f"{vehicle['year']}_{vehicle['make'].lower()}_{vehicle['model'].lower()}"
    return re.sub(r"[^a-z0-9_-]+", "-", raw).strip("-_")


def output_path(vehicle: dict, code: str) -> Path:
    return RAW_DIR / slug_vehicle(vehicle) / f"{code}.json"


def _count(source: Any, *keys: str) -> int:
    """Sum len() of the first list found under any of `keys` in `source`."""
    if not isinstance(source, dict) or "error" in source:
        return 0
    for k in keys:
        v = source.get(k)
        if isinstance(v, list):
            return len(v)
        if isinstance(v, int):
            return v
    return 0


def summarize_nhtsa(data: dict) -> int:
    return _count(data, "count", "results")


def summarize_repairpal(data: dict) -> int:
    return _count(data, "common_repairs") + _count(data, "common_problems")


def summarize_carcomplaints(data: dict) -> int:
    return _count(data, "worst_problems") + _count(data, "engine_problems")


async def process_combo(
    client: httpx.AsyncClient,
    vehicle: dict,
    code: str,
    index: int,
    total: int,
    force: bool,
) -> tuple[str, str]:
    """Return (status, summary_line). status in {processed, skipped, failed}."""
    label = f"{vehicle['year']} {vehicle['make']} {vehicle['model']} {code}"
    out = output_path(vehicle, code)

    if out.exists() and not force:
        return "skipped", f"[{index}/{total}] {label} — skipped (already exists)"

    try:
        nhtsa = await fetch_nhtsa(client, vehicle["make"], vehicle["model"], vehicle["year"])
        obd = await fetch_obd_codes(code)
        repairpal = await fetch_repairpal(vehicle["make"], vehicle["model"], vehicle["year"])
        carcomp = await fetch_carcomplaints(vehicle["make"], vehicle["model"], vehicle["year"])

        record = {
            "vehicle": vehicle,
            "code": code,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "sources": {
                "nhtsa": nhtsa,
                "obd_codes": obd,
                "repairpal": repairpal,
                "carcomplaints": carcomp,
            },
        }

        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
        tmp.replace(out)

        summary = (
            f"[{index}/{total}] {label} — "
            f"NHTSA: {summarize_nhtsa(nhtsa)}, "
            f"RepairPal: {summarize_repairpal(repairpal)}, "
            f"CarComplaints: {summarize_carcomplaints(carcomp)}"
        )
        return "processed", summary
    except Exception as e:
        return "failed", f"[{index}/{total}] {label} — FAILED: {e!r}"


# --- Main ------------------------------------------------------------------

async def run(force: bool) -> int:
    _log_init()
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    combos = [(v, c) for v in TOP_50_VEHICLES for c in TOP_15_CODES]
    total = len(combos)
    log(f"Starting scrape: {total} combinations (force={force})")
    log(
        f"Vehicles: {len(TOP_50_VEHICLES)}, codes: {len(TOP_15_CODES)}, "
        f"hard timeout: {TIMEOUT_SECONDS/3600:.1f}h"
    )
    log(f"Output root: {RAW_DIR}")

    start = time.monotonic()
    processed = skipped = failed = 0

    async with httpx.AsyncClient(headers=HTTP_HEADERS, follow_redirects=True) as client:
        for i, (vehicle, code) in enumerate(combos, 1):
            if time.monotonic() - start > TIMEOUT_SECONDS:
                log(f"Hard timeout reached after {i-1}/{total}. Stopping.")
                break

            status, summary = await process_combo(client, vehicle, code, i, total, force)
            log(summary)
            if status == "processed":
                processed += 1
            elif status == "skipped":
                skipped += 1
            else:
                failed += 1

            await asyncio.sleep(INTER_COMBO_DELAY_SECONDS)

    elapsed_min = (time.monotonic() - start) / 60
    log(
        f"Run complete. processed={processed} skipped={skipped} "
        f"failed={failed} elapsed={elapsed_min:.1f}min"
    )
    return 0 if failed == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Collect raw training data for the top 50 US vehicles x top 15 "
            "OBD-II codes from NHTSA, OBD-Codes, RepairPal, CarComplaints."
        )
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch combinations even if the output file already exists.",
    )
    args = parser.parse_args()
    try:
        exit_code = asyncio.run(run(force=args.force))
    except KeyboardInterrupt:
        log("Interrupted by user.")
        exit_code = 130
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
