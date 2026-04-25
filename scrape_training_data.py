#!/usr/bin/env python3
"""Overnight scraper v2 — raw diagnostic training data corpus.

For each combination of ~300 US-market vehicle (year, make, model)
profiles and 50 OBD-II codes (~15,000 combos), collect raw records from
five sources:

  1. NHTSA complaintsByVehicle API
  2. NHTSA recallsByVehicle API
  3. RepairPal (vehicle common repairs)
  4. CarComplaints.com (vehicle complaint narratives)
  5. Reddit (lean wrapper around forum_scraper primitives)

OBD-Codes.com was originally included as a sixth source for generic
code descriptions but is currently behind a Cloudflare browser
challenge that returns HTTP 403 to the scraper on every request. It
was removed from the source list in this revision; investigation of
a Cloudflare workaround is tracked separately.

One JSON file per (vehicle, code) combination is written to:
    training_data/raw/{vehicle_slug}/{code}.json
with one top-level key per source under `sources`.

Designed to run unattended overnight as a detached process. Idempotent
(skip-if-output-exists, --force overrides). Resilient (per-source
try/except, per-combo try/except, run never crashes on a bad URL).
Atomic writes (.tmp -> rename) so an interrupted run never leaves a
half-written file.

Memoization keeps the upstream request count proportional to the
unique key each source actually varies over:
  - NHTSA complaints: per (year,make,model) -> 300 fresh fetches
  - NHTSA recalls:    per (year,make,model) -> 300 fresh fetches
  - RepairPal:        per (year,make,model) -> 300 fresh fetches
  - CarComplaints:    per (year,make,model) -> 300 fresh fetches
  - Reddit:           per (make,model,code)  -> 141 unique (make,model)
                                              x 50 codes = 7,050

So total upstream requests across a fresh run are on the order of
~8,000, not the naive 5 x 15,000 = 75,000.

Reddit is the dominant cost. A "lean wrapper" around forum_scraper's
primitives (search_reddit + get_post_comments) is used instead of
calling scrape_reddit_fallback directly, because the latter does
4 subreddits x 2 queries + 3 comment fetches per call (~14s) which
would push the run past the 12h trim threshold. The lean wrapper does
3 subreddits (MechanicAdvice + Cartalk + brand-specific) x 1 query
+ 1 conditional comment fetch per call (~6s).

Logging:
  Each per-combo result is printed to stdout AND appended to
  training_data/scrape.log so a detached run is fully inspectable
  the next morning.

Hard timeout: stops cleanly after --max-hours hours (default 8.0),
checked before each combo.
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
    scrape_repairpal,
)
from forum_scraper import get_post_comments, search_reddit


# --- Paths and config ------------------------------------------------------

DATA_ROOT = Path(__file__).parent / "training_data"
RAW_DIR = DATA_ROOT / "raw"
LOG_FILE = DATA_ROOT / "scrape.log"

DEFAULT_MAX_HOURS = 8.0
PER_DOMAIN_COOLDOWN_SECONDS = 1.5  # gap between hits to the same host

HTTP_HEADERS = {
    "User-Agent": (
        "ClearDrive-training-scraper/2.0 "
        "(+research; contact: conorpbrennan@gmail.com)"
    ),
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
}

NHTSA_COMPLAINTS_URL = "https://api.nhtsa.gov/complaints/complaintsByVehicle"
NHTSA_RECALLS_URL = "https://api.nhtsa.gov/recalls/recallsByVehicle"

# Reddit subreddits per spec: MechanicAdvice + Cartalk (always) plus a
# brand-specific sub when one is mapped below.
GENERAL_SUBREDDITS = ["MechanicAdvice", "Cartalk"]

BRAND_SUBREDDITS: dict[str, str] = {
    "ford":          "Ford",
    "chevrolet":     "chevrolet",
    "gmc":           "GMC",
    "ram":           "ram_trucks",
    "dodge":         "Dodge",
    "chrysler":      "Chrysler",
    "jeep":          "Jeep",
    "buick":         "Buick",
    "toyota":        "Toyota",
    "honda":         "Honda",
    "nissan":        "Nissan",
    "mazda":         "mazda",
    "subaru":        "subaru",
    "hyundai":       "Hyundai",
    "kia":           "kia",
    "genesis":       "Genesis",
    "volkswagen":    "Volkswagen",
    "audi":          "Audi",
    "bmw":           "BMW",
    "mercedes-benz": "mercedes_benz",
    "mini":          "MINI",
    "volvo":         "Volvo",
    "lexus":         "Lexus",
    "acura":         "Acura",
    "infiniti":      "infiniti",
}


# --- 50 OBD-II codes (chosen by frequency, with category coverage) ---------

TOP_50_CODES: list[str] = [
    # Original 15 (per spec)
    "P0171", "P0300", "P0420", "P0455", "P0301",
    "P0128", "P0411", "P0440", "P0606", "P0700",
    "P0011", "P0016", "P0014", "P0345", "P0102",
    # Individual cylinder misfires (P0302-P0308)
    "P0302", "P0303", "P0304", "P0305", "P0306", "P0307", "P0308",
    # Sensor codes
    "P0101",  # MAF circuit range/performance
    "P0113",  # IAT sensor circuit high
    "P0117",  # ECT sensor circuit low
    "P0131",  # O2 sensor circuit low (bank 1 sensor 1)
    "P0135",  # O2 sensor heater circuit (bank 1 sensor 1)
    "P0141",  # O2 sensor heater circuit (bank 1 sensor 2)
    # Other commonly seen
    "P0325",  # Knock sensor 1 circuit
    "P0340",  # Camshaft position sensor circuit
    "P0401",  # EGR insufficient flow
    "P0421",  # Catalyst efficiency below threshold (bank 2)
    # Evap family (P0455 / P0440 already in original 15)
    "P0441", "P0442", "P0446", "P0456",
    # Transmission family
    "P0715", "P0730", "P0740", "P0750",
    # Charging / electrical
    "P0500",  # Vehicle speed sensor
    "P0507",  # Idle air control RPM higher than expected
    "P0521",  # Engine oil pressure sensor performance
    # ECU / voltage
    "P0601", "P0603", "P0604", "P0605",
    # VVT family (P0011 / P0014 / P0016 already in original 15)
    "P0010", "P0013", "P0015",
]
assert len(TOP_50_CODES) == 50, f"expected 50 codes, got {len(TOP_50_CODES)}"
assert len(set(TOP_50_CODES)) == 50, "duplicate code in TOP_50_CODES"


# --- ~300 vehicle profiles -------------------------------------------------
# Picked for US sales volume and engine diversity (turbo-4, NA V6, V8,
# hybrid). Multiple year entries for top sellers with significant
# generation/engine changes (e.g. F-150 5.0L V8 vs 3.5L EcoBoost vs
# PowerBoost hybrid). EVs intentionally excluded (no OBD-II diagnostic
# patterns we care about for this corpus).

TOP_VEHICLES: list[dict[str, Any]] = [
    # ===== Ford (38) =====
    {"year": 2015, "make": "Ford", "model": "F-150"},
    {"year": 2016, "make": "Ford", "model": "F-150"},
    {"year": 2017, "make": "Ford", "model": "F-150"},
    {"year": 2018, "make": "Ford", "model": "F-150"},
    {"year": 2019, "make": "Ford", "model": "F-150"},
    {"year": 2020, "make": "Ford", "model": "F-150"},
    {"year": 2021, "make": "Ford", "model": "F-150"},
    {"year": 2022, "make": "Ford", "model": "F-150"},
    {"year": 2017, "make": "Ford", "model": "F-250 Super Duty"},
    {"year": 2020, "make": "Ford", "model": "F-250 Super Duty"},
    {"year": 2019, "make": "Ford", "model": "F-350 Super Duty"},
    {"year": 2015, "make": "Ford", "model": "Mustang"},
    {"year": 2018, "make": "Ford", "model": "Mustang"},
    {"year": 2021, "make": "Ford", "model": "Mustang"},
    {"year": 2023, "make": "Ford", "model": "Mustang"},
    {"year": 2015, "make": "Ford", "model": "Explorer"},
    {"year": 2018, "make": "Ford", "model": "Explorer"},
    {"year": 2020, "make": "Ford", "model": "Explorer"},
    {"year": 2022, "make": "Ford", "model": "Explorer"},
    {"year": 2015, "make": "Ford", "model": "Edge"},
    {"year": 2018, "make": "Ford", "model": "Edge"},
    {"year": 2020, "make": "Ford", "model": "Edge"},
    {"year": 2016, "make": "Ford", "model": "Escape"},
    {"year": 2019, "make": "Ford", "model": "Escape"},
    {"year": 2021, "make": "Ford", "model": "Escape"},
    {"year": 2023, "make": "Ford", "model": "Escape"},
    {"year": 2021, "make": "Ford", "model": "Bronco"},
    {"year": 2023, "make": "Ford", "model": "Bronco"},
    {"year": 2022, "make": "Ford", "model": "Bronco Sport"},
    {"year": 2019, "make": "Ford", "model": "Ranger"},
    {"year": 2022, "make": "Ford", "model": "Ranger"},
    {"year": 2016, "make": "Ford", "model": "Fusion"},
    {"year": 2018, "make": "Ford", "model": "Fusion"},
    {"year": 2020, "make": "Ford", "model": "Fusion"},
    {"year": 2015, "make": "Ford", "model": "Focus"},
    {"year": 2018, "make": "Ford", "model": "Focus"},
    {"year": 2018, "make": "Ford", "model": "Expedition"},
    {"year": 2022, "make": "Ford", "model": "Expedition"},

    # ===== Chevrolet (32) =====
    {"year": 2015, "make": "Chevrolet", "model": "Silverado 1500"},
    {"year": 2017, "make": "Chevrolet", "model": "Silverado 1500"},
    {"year": 2019, "make": "Chevrolet", "model": "Silverado 1500"},
    {"year": 2020, "make": "Chevrolet", "model": "Silverado 1500"},
    {"year": 2021, "make": "Chevrolet", "model": "Silverado 1500"},
    {"year": 2023, "make": "Chevrolet", "model": "Silverado 1500"},
    {"year": 2017, "make": "Chevrolet", "model": "Tahoe"},
    {"year": 2019, "make": "Chevrolet", "model": "Tahoe"},
    {"year": 2021, "make": "Chevrolet", "model": "Tahoe"},
    {"year": 2018, "make": "Chevrolet", "model": "Suburban"},
    {"year": 2021, "make": "Chevrolet", "model": "Suburban"},
    {"year": 2018, "make": "Chevrolet", "model": "Equinox"},
    {"year": 2020, "make": "Chevrolet", "model": "Equinox"},
    {"year": 2022, "make": "Chevrolet", "model": "Equinox"},
    {"year": 2018, "make": "Chevrolet", "model": "Traverse"},
    {"year": 2020, "make": "Chevrolet", "model": "Traverse"},
    {"year": 2022, "make": "Chevrolet", "model": "Traverse"},
    {"year": 2016, "make": "Chevrolet", "model": "Malibu"},
    {"year": 2020, "make": "Chevrolet", "model": "Malibu"},
    {"year": 2016, "make": "Chevrolet", "model": "Camaro"},
    {"year": 2020, "make": "Chevrolet", "model": "Camaro"},
    {"year": 2017, "make": "Chevrolet", "model": "Colorado"},
    {"year": 2020, "make": "Chevrolet", "model": "Colorado"},
    {"year": 2018, "make": "Chevrolet", "model": "Trax"},
    {"year": 2021, "make": "Chevrolet", "model": "Trax"},
    {"year": 2021, "make": "Chevrolet", "model": "Trailblazer"},
    {"year": 2018, "make": "Chevrolet", "model": "Corvette"},
    {"year": 2021, "make": "Chevrolet", "model": "Corvette"},
    {"year": 2017, "make": "Chevrolet", "model": "Impala"},
    {"year": 2017, "make": "Chevrolet", "model": "Cruze"},

    # ===== GMC (12) =====
    {"year": 2015, "make": "GMC", "model": "Sierra 1500"},
    {"year": 2018, "make": "GMC", "model": "Sierra 1500"},
    {"year": 2021, "make": "GMC", "model": "Sierra 1500"},
    {"year": 2023, "make": "GMC", "model": "Sierra 1500"},
    {"year": 2018, "make": "GMC", "model": "Yukon"},
    {"year": 2021, "make": "GMC", "model": "Yukon"},
    {"year": 2017, "make": "GMC", "model": "Acadia"},
    {"year": 2020, "make": "GMC", "model": "Acadia"},
    {"year": 2018, "make": "GMC", "model": "Terrain"},
    {"year": 2021, "make": "GMC", "model": "Terrain"},
    {"year": 2018, "make": "GMC", "model": "Canyon"},
    {"year": 2020, "make": "GMC", "model": "Canyon"},

    # ===== Ram (8) =====
    {"year": 2015, "make": "Ram", "model": "1500"},
    {"year": 2017, "make": "Ram", "model": "1500"},
    {"year": 2019, "make": "Ram", "model": "1500"},
    {"year": 2020, "make": "Ram", "model": "1500"},
    {"year": 2021, "make": "Ram", "model": "1500"},
    {"year": 2023, "make": "Ram", "model": "1500"},
    {"year": 2018, "make": "Ram", "model": "2500"},
    {"year": 2021, "make": "Ram", "model": "2500"},

    # ===== Jeep (16) =====
    {"year": 2015, "make": "Jeep", "model": "Wrangler"},
    {"year": 2018, "make": "Jeep", "model": "Wrangler"},
    {"year": 2020, "make": "Jeep", "model": "Wrangler"},
    {"year": 2022, "make": "Jeep", "model": "Wrangler"},
    {"year": 2015, "make": "Jeep", "model": "Grand Cherokee"},
    {"year": 2017, "make": "Jeep", "model": "Grand Cherokee"},
    {"year": 2019, "make": "Jeep", "model": "Grand Cherokee"},
    {"year": 2021, "make": "Jeep", "model": "Grand Cherokee"},
    {"year": 2015, "make": "Jeep", "model": "Cherokee"},
    {"year": 2018, "make": "Jeep", "model": "Cherokee"},
    {"year": 2020, "make": "Jeep", "model": "Cherokee"},
    {"year": 2017, "make": "Jeep", "model": "Compass"},
    {"year": 2019, "make": "Jeep", "model": "Compass"},
    {"year": 2022, "make": "Jeep", "model": "Compass"},
    {"year": 2017, "make": "Jeep", "model": "Renegade"},
    {"year": 2020, "make": "Jeep", "model": "Gladiator"},

    # ===== Buick (5) =====
    {"year": 2017, "make": "Buick", "model": "Encore"},
    {"year": 2020, "make": "Buick", "model": "Encore"},
    {"year": 2018, "make": "Buick", "model": "Enclave"},
    {"year": 2021, "make": "Buick", "model": "Enclave"},
    {"year": 2018, "make": "Buick", "model": "Envision"},

    # ===== Dodge / Chrysler (12) =====
    {"year": 2015, "make": "Dodge", "model": "Charger"},
    {"year": 2017, "make": "Dodge", "model": "Charger"},
    {"year": 2019, "make": "Dodge", "model": "Charger"},
    {"year": 2021, "make": "Dodge", "model": "Charger"},
    {"year": 2015, "make": "Dodge", "model": "Challenger"},
    {"year": 2018, "make": "Dodge", "model": "Challenger"},
    {"year": 2020, "make": "Dodge", "model": "Challenger"},
    {"year": 2018, "make": "Dodge", "model": "Durango"},
    {"year": 2020, "make": "Dodge", "model": "Durango"},
    {"year": 2017, "make": "Chrysler", "model": "300"},
    {"year": 2018, "make": "Chrysler", "model": "Pacifica"},
    {"year": 2020, "make": "Chrysler", "model": "Pacifica"},

    # ===== Toyota (38) =====
    {"year": 2015, "make": "Toyota", "model": "Camry"},
    {"year": 2018, "make": "Toyota", "model": "Camry"},
    {"year": 2018, "make": "Toyota", "model": "Camry Hybrid"},
    {"year": 2020, "make": "Toyota", "model": "Camry"},
    {"year": 2020, "make": "Toyota", "model": "Camry Hybrid"},
    {"year": 2022, "make": "Toyota", "model": "Camry"},
    {"year": 2024, "make": "Toyota", "model": "Camry"},
    {"year": 2015, "make": "Toyota", "model": "Corolla"},
    {"year": 2019, "make": "Toyota", "model": "Corolla"},
    {"year": 2020, "make": "Toyota", "model": "Corolla Hybrid"},
    {"year": 2022, "make": "Toyota", "model": "Corolla Hybrid"},
    {"year": 2015, "make": "Toyota", "model": "RAV4"},
    {"year": 2019, "make": "Toyota", "model": "RAV4 Hybrid"},
    {"year": 2020, "make": "Toyota", "model": "RAV4"},
    {"year": 2022, "make": "Toyota", "model": "RAV4 Prime"},
    {"year": 2023, "make": "Toyota", "model": "RAV4 Hybrid"},
    {"year": 2017, "make": "Toyota", "model": "Highlander"},
    {"year": 2020, "make": "Toyota", "model": "Highlander Hybrid"},
    {"year": 2021, "make": "Toyota", "model": "Highlander"},
    {"year": 2017, "make": "Toyota", "model": "4Runner"},
    {"year": 2019, "make": "Toyota", "model": "4Runner"},
    {"year": 2021, "make": "Toyota", "model": "4Runner"},
    {"year": 2017, "make": "Toyota", "model": "Tacoma"},
    {"year": 2019, "make": "Toyota", "model": "Tacoma"},
    {"year": 2021, "make": "Toyota", "model": "Tacoma"},
    {"year": 2017, "make": "Toyota", "model": "Tundra"},
    {"year": 2019, "make": "Toyota", "model": "Tundra"},
    {"year": 2022, "make": "Toyota", "model": "Tundra"},
    {"year": 2018, "make": "Toyota", "model": "Sienna"},
    {"year": 2021, "make": "Toyota", "model": "Sienna"},
    {"year": 2017, "make": "Toyota", "model": "Avalon"},
    {"year": 2017, "make": "Toyota", "model": "Prius"},
    {"year": 2020, "make": "Toyota", "model": "Prius"},
    {"year": 2018, "make": "Toyota", "model": "Sequoia"},

    # ===== Honda (25) =====
    {"year": 2017, "make": "Honda", "model": "Accord"},
    {"year": 2018, "make": "Honda", "model": "Accord"},
    {"year": 2018, "make": "Honda", "model": "Accord Hybrid"},
    {"year": 2020, "make": "Honda", "model": "Accord"},
    {"year": 2021, "make": "Honda", "model": "Accord Hybrid"},
    {"year": 2017, "make": "Honda", "model": "Civic"},
    {"year": 2020, "make": "Honda", "model": "Civic"},
    {"year": 2022, "make": "Honda", "model": "Civic"},
    {"year": 2017, "make": "Honda", "model": "CR-V"},
    {"year": 2019, "make": "Honda", "model": "CR-V"},
    {"year": 2020, "make": "Honda", "model": "CR-V Hybrid"},
    {"year": 2022, "make": "Honda", "model": "CR-V Hybrid"},
    {"year": 2017, "make": "Honda", "model": "Pilot"},
    {"year": 2020, "make": "Honda", "model": "Pilot"},
    {"year": 2023, "make": "Honda", "model": "Pilot"},
    {"year": 2018, "make": "Honda", "model": "Odyssey"},
    {"year": 2021, "make": "Honda", "model": "Odyssey"},
    {"year": 2019, "make": "Honda", "model": "Passport"},
    {"year": 2022, "make": "Honda", "model": "Passport"},
    {"year": 2017, "make": "Honda", "model": "Ridgeline"},
    {"year": 2020, "make": "Honda", "model": "Ridgeline"},
    {"year": 2016, "make": "Honda", "model": "Fit"},
    {"year": 2017, "make": "Honda", "model": "HR-V"},
    {"year": 2020, "make": "Honda", "model": "HR-V"},

    # ===== Nissan (22) =====
    {"year": 2017, "make": "Nissan", "model": "Altima"},
    {"year": 2019, "make": "Nissan", "model": "Altima"},
    {"year": 2021, "make": "Nissan", "model": "Altima"},
    {"year": 2018, "make": "Nissan", "model": "Sentra"},
    {"year": 2020, "make": "Nissan", "model": "Sentra"},
    {"year": 2022, "make": "Nissan", "model": "Sentra"},
    {"year": 2017, "make": "Nissan", "model": "Maxima"},
    {"year": 2019, "make": "Nissan", "model": "Maxima"},
    {"year": 2017, "make": "Nissan", "model": "Versa"},
    {"year": 2017, "make": "Nissan", "model": "Rogue"},
    {"year": 2019, "make": "Nissan", "model": "Rogue"},
    {"year": 2021, "make": "Nissan", "model": "Rogue"},
    {"year": 2023, "make": "Nissan", "model": "Rogue"},
    {"year": 2018, "make": "Nissan", "model": "Murano"},
    {"year": 2020, "make": "Nissan", "model": "Murano"},
    {"year": 2017, "make": "Nissan", "model": "Pathfinder"},
    {"year": 2019, "make": "Nissan", "model": "Pathfinder"},
    {"year": 2022, "make": "Nissan", "model": "Pathfinder"},
    {"year": 2018, "make": "Nissan", "model": "Frontier"},
    {"year": 2022, "make": "Nissan", "model": "Frontier"},
    {"year": 2017, "make": "Nissan", "model": "Titan"},
    {"year": 2018, "make": "Nissan", "model": "Kicks"},

    # ===== Mazda (12) =====
    {"year": 2017, "make": "Mazda", "model": "CX-5"},
    {"year": 2019, "make": "Mazda", "model": "CX-5"},
    {"year": 2021, "make": "Mazda", "model": "CX-5"},
    {"year": 2023, "make": "Mazda", "model": "CX-5"},
    {"year": 2017, "make": "Mazda", "model": "CX-9"},
    {"year": 2020, "make": "Mazda", "model": "CX-9"},
    {"year": 2015, "make": "Mazda", "model": "Mazda3"},
    {"year": 2017, "make": "Mazda", "model": "Mazda3"},
    {"year": 2019, "make": "Mazda", "model": "Mazda3"},
    {"year": 2017, "make": "Mazda", "model": "Mazda6"},
    {"year": 2018, "make": "Mazda", "model": "Mazda6"},
    {"year": 2020, "make": "Mazda", "model": "CX-30"},

    # ===== Subaru (18) =====
    {"year": 2015, "make": "Subaru", "model": "Outback"},
    {"year": 2019, "make": "Subaru", "model": "Outback"},
    {"year": 2020, "make": "Subaru", "model": "Outback"},
    {"year": 2022, "make": "Subaru", "model": "Outback"},
    {"year": 2017, "make": "Subaru", "model": "Forester"},
    {"year": 2019, "make": "Subaru", "model": "Forester"},
    {"year": 2021, "make": "Subaru", "model": "Forester"},
    {"year": 2017, "make": "Subaru", "model": "Impreza"},
    {"year": 2019, "make": "Subaru", "model": "Impreza"},
    {"year": 2018, "make": "Subaru", "model": "Crosstrek"},
    {"year": 2020, "make": "Subaru", "model": "Crosstrek"},
    {"year": 2022, "make": "Subaru", "model": "Crosstrek"},
    {"year": 2017, "make": "Subaru", "model": "Legacy"},
    {"year": 2020, "make": "Subaru", "model": "Legacy"},
    {"year": 2019, "make": "Subaru", "model": "Ascent"},
    {"year": 2017, "make": "Subaru", "model": "WRX"},
    {"year": 2022, "make": "Subaru", "model": "WRX"},

    # ===== Hyundai (12) =====
    {"year": 2017, "make": "Hyundai", "model": "Elantra"},
    {"year": 2019, "make": "Hyundai", "model": "Elantra"},
    {"year": 2021, "make": "Hyundai", "model": "Elantra"},
    {"year": 2017, "make": "Hyundai", "model": "Sonata"},
    {"year": 2019, "make": "Hyundai", "model": "Sonata"},
    {"year": 2018, "make": "Hyundai", "model": "Sonata Hybrid"},
    {"year": 2017, "make": "Hyundai", "model": "Tucson"},
    {"year": 2019, "make": "Hyundai", "model": "Tucson"},
    {"year": 2022, "make": "Hyundai", "model": "Tucson"},
    {"year": 2019, "make": "Hyundai", "model": "Santa Fe"},
    {"year": 2020, "make": "Hyundai", "model": "Palisade"},
    {"year": 2019, "make": "Hyundai", "model": "Kona"},

    # ===== Kia (13) =====
    {"year": 2017, "make": "Kia", "model": "Forte"},
    {"year": 2019, "make": "Kia", "model": "Forte"},
    {"year": 2021, "make": "Kia", "model": "Forte"},
    {"year": 2021, "make": "Kia", "model": "K5"},
    {"year": 2017, "make": "Kia", "model": "Optima"},
    {"year": 2019, "make": "Kia", "model": "Optima"},
    {"year": 2017, "make": "Kia", "model": "Sportage"},
    {"year": 2019, "make": "Kia", "model": "Sportage"},
    {"year": 2017, "make": "Kia", "model": "Sorento"},
    {"year": 2019, "make": "Kia", "model": "Sorento"},
    {"year": 2020, "make": "Kia", "model": "Telluride"},
    {"year": 2017, "make": "Kia", "model": "Soul"},
    {"year": 2020, "make": "Kia", "model": "Soul"},

    # ===== Genesis (5) =====
    {"year": 2019, "make": "Genesis", "model": "G70"},
    {"year": 2021, "make": "Genesis", "model": "G70"},
    {"year": 2018, "make": "Genesis", "model": "G80"},
    {"year": 2021, "make": "Genesis", "model": "G80"},
    {"year": 2017, "make": "Genesis", "model": "G90"},

    # ===== VW (7) =====
    {"year": 2017, "make": "Volkswagen", "model": "Jetta"},
    {"year": 2019, "make": "Volkswagen", "model": "Jetta"},
    {"year": 2017, "make": "Volkswagen", "model": "Passat"},
    {"year": 2018, "make": "Volkswagen", "model": "Tiguan"},
    {"year": 2020, "make": "Volkswagen", "model": "Tiguan"},
    {"year": 2018, "make": "Volkswagen", "model": "Atlas"},
    {"year": 2017, "make": "Volkswagen", "model": "GTI"},

    # ===== Audi (5) =====
    {"year": 2017, "make": "Audi", "model": "A4"},
    {"year": 2019, "make": "Audi", "model": "A4"},
    {"year": 2018, "make": "Audi", "model": "Q5"},
    {"year": 2020, "make": "Audi", "model": "Q5"},
    {"year": 2017, "make": "Audi", "model": "Q7"},

    # ===== BMW (5) =====
    {"year": 2017, "make": "BMW", "model": "330i"},
    {"year": 2019, "make": "BMW", "model": "330i"},
    {"year": 2018, "make": "BMW", "model": "X3"},
    {"year": 2020, "make": "BMW", "model": "X3"},
    {"year": 2018, "make": "BMW", "model": "X5"},

    # ===== Mercedes-Benz (5) =====
    {"year": 2017, "make": "Mercedes-Benz", "model": "C300"},
    {"year": 2019, "make": "Mercedes-Benz", "model": "C300"},
    {"year": 2017, "make": "Mercedes-Benz", "model": "E300"},
    {"year": 2018, "make": "Mercedes-Benz", "model": "GLC300"},
    {"year": 2018, "make": "Mercedes-Benz", "model": "GLE350"},

    # ===== Mini (1) =====
    {"year": 2018, "make": "MINI", "model": "Cooper"},

    # ===== Volvo (2) =====
    {"year": 2018, "make": "Volvo", "model": "XC60"},
    {"year": 2018, "make": "Volvo", "model": "XC90"},

    # ===== Lexus (8) =====
    {"year": 2017, "make": "Lexus", "model": "RX350"},
    {"year": 2019, "make": "Lexus", "model": "RX350"},
    {"year": 2021, "make": "Lexus", "model": "RX350"},
    {"year": 2018, "make": "Lexus", "model": "ES350"},
    {"year": 2021, "make": "Lexus", "model": "ES350"},
    {"year": 2018, "make": "Lexus", "model": "GX460"},
    {"year": 2017, "make": "Lexus", "model": "IS300"},
    {"year": 2018, "make": "Lexus", "model": "NX300"},

    # ===== Acura (5) =====
    {"year": 2017, "make": "Acura", "model": "MDX"},
    {"year": 2020, "make": "Acura", "model": "MDX"},
    {"year": 2018, "make": "Acura", "model": "RDX"},
    {"year": 2021, "make": "Acura", "model": "RDX"},
    {"year": 2018, "make": "Acura", "model": "TLX"},

    # ===== Infiniti (2) =====
    {"year": 2017, "make": "Infiniti", "model": "Q50"},
    {"year": 2018, "make": "Infiniti", "model": "QX60"},
]
assert len(TOP_VEHICLES) == 300, f"expected 300 vehicles, got {len(TOP_VEHICLES)}"


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

_nhtsa_complaints_cache: dict[str, dict] = {}
_nhtsa_recalls_cache: dict[str, dict] = {}
_repairpal_cache: dict[str, dict] = {}
_carcomp_cache: dict[str, dict] = {}
_reddit_cache: dict[str, dict] = {}


def _vkey(make: str, model: str, year: int) -> str:
    return f"{year}|{make.lower()}|{model.lower()}"


def _mmkey(make: str, model: str, code: str) -> str:
    return f"{make.lower()}|{model.lower()}|{code.upper()}"


# --- Source: NHTSA complaints ---------------------------------------------

async def fetch_nhtsa_complaints(
    client: httpx.AsyncClient, make: str, model: str, year: int
) -> dict:
    """NHTSA complaintsByVehicle.

    Quirk: the API returns HTTP 400 with a fully-formed empty-results
    body ({"count": 0, "message": "Results returned successfully",
    "results": []}) for vehicles with no complaints on file. Try to
    parse the body BEFORE treating the status code as a failure.
    """
    key = _vkey(make, model, year)
    if key in _nhtsa_complaints_cache:
        return _nhtsa_complaints_cache[key]
    await wait_for_domain("api.nhtsa.gov")
    try:
        resp = await client.get(
            NHTSA_COMPLAINTS_URL,
            params={"make": make, "model": model, "modelYear": str(year)},
            timeout=30,
        )
        try:
            data = resp.json()
            if not isinstance(data, dict):
                data = {"raw": data}
        except Exception:
            # Body wasn't JSON — surface the underlying HTTP failure.
            resp.raise_for_status()
            raise
    except Exception as e:
        log(f"  NHTSA-complaints error for {year} {make} {model}: {e!r}")
        data = {"error": repr(e), "count": 0, "results": []}
    _nhtsa_complaints_cache[key] = data
    return data


# --- Source: NHTSA recalls ------------------------------------------------

async def fetch_nhtsa_recalls(
    client: httpx.AsyncClient, make: str, model: str, year: int
) -> dict:
    """NHTSA recallsByVehicle.

    Same HTTP-400-on-empty-results quirk as the complaints endpoint —
    parse the body before deciding the status code was a failure.

    NHTSA does NOT expose TSBs publicly via API; TSB counts are
    surfaced through the CarComplaints scrape instead.
    """
    key = _vkey(make, model, year)
    if key in _nhtsa_recalls_cache:
        return _nhtsa_recalls_cache[key]
    await wait_for_domain("api.nhtsa.gov")
    try:
        resp = await client.get(
            NHTSA_RECALLS_URL,
            params={"make": make, "model": model, "modelYear": str(year)},
            timeout=30,
        )
        try:
            data = resp.json()
            if not isinstance(data, dict):
                data = {"raw": data}
        except Exception:
            resp.raise_for_status()
            raise
    except Exception as e:
        log(f"  NHTSA-recalls error for {year} {make} {model}: {e!r}")
        data = {"error": repr(e), "count": 0, "results": []}
    _nhtsa_recalls_cache[key] = data
    return data


# --- Source: RepairPal (existing scraper) ---------------------------------

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


# --- Source: CarComplaints (existing scraper) -----------------------------

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


# --- Source: Reddit (LEAN WRAPPER around forum_scraper primitives) --------

async def fetch_reddit(make: str, model: str, code: str) -> dict:
    """Lean per-(make, model, code) Reddit fetch.

    Per spec: searches MechanicAdvice + Cartalk + (brand-specific sub
    if mapped) = up to 3 search calls per invocation. Then fetches
    comments only for the single highest-scoring post across all subs
    (1 conditional call). forum_scraper's primitives already include a
    1-second internal sleep between calls; the PER_DOMAIN_COOLDOWN
    gap on top keeps Reddit rate well under their unauth limit.

    Returns a dict with `query`, `subreddits_tried`, `posts` (combined
    list across subs), `top_post`, and `top_post_comments`.
    """
    cache_key = _mmkey(make, model, code)
    if cache_key in _reddit_cache:
        return _reddit_cache[cache_key]

    query = f"{make} {model} {code}"
    subs = list(GENERAL_SUBREDDITS)
    brand_sub = BRAND_SUBREDDITS.get(make.lower())
    if brand_sub and brand_sub not in subs:
        subs.append(brand_sub)

    all_posts: list[dict] = []
    for sub in subs:
        await wait_for_domain("www.reddit.com")
        try:
            posts = await search_reddit(query, sub, limit=5) or []
        except Exception as e:
            log(f"  Reddit search error for r/{sub} {query!r}: {e!r}")
            posts = []
        for p in posts:
            all_posts.append({**p, "_subreddit_searched": sub})

    top_comments: list[str] = []
    top_post: dict | None = None
    if all_posts:
        top_post = max(all_posts, key=lambda p: p.get("score", 0))
        permalink = (top_post.get("url") or "").replace("https://reddit.com", "")
        if permalink:
            await wait_for_domain("www.reddit.com")
            try:
                top_comments = await get_post_comments(permalink, limit=5) or []
            except Exception as e:
                log(f"  Reddit comments error for {permalink!r}: {e!r}")
                top_comments = []

    data = {
        "query": query,
        "subreddits_tried": subs,
        "posts": all_posts,
        "top_post": top_post,
        "top_post_comments": top_comments[:3] if top_comments else [],
    }
    _reddit_cache[cache_key] = data
    return data


# --- Per-combo processing --------------------------------------------------

def slug_vehicle(vehicle: dict) -> str:
    raw = f"{vehicle['year']}_{vehicle['make'].lower()}_{vehicle['model'].lower()}"
    return re.sub(r"[^a-z0-9_-]+", "-", raw).strip("-_")


def output_path(vehicle: dict, code: str) -> Path:
    return RAW_DIR / slug_vehicle(vehicle) / f"{code}.json"


def _len_or_count(source: Any, *keys: str) -> int:
    """Return the first int / len(list) found at any of `keys` in `source`."""
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
    return _len_or_count(data, "count", "results")


def summarize_repairpal(data: dict) -> int:
    return _len_or_count(data, "common_repairs") + _len_or_count(data, "common_problems")


def summarize_carcomplaints(data: dict) -> int:
    return _len_or_count(data, "worst_problems") + _len_or_count(data, "engine_problems")


def summarize_reddit(data: dict) -> int:
    if not isinstance(data, dict) or "error" in data:
        return 0
    return len(data.get("posts", [])) + len(data.get("top_post_comments", []))


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
        return "skipped", f"[{index}/{total}] {label} - skipped (already exists)"

    try:
        nhtsa_c = await fetch_nhtsa_complaints(client, vehicle["make"], vehicle["model"], vehicle["year"])
        nhtsa_r = await fetch_nhtsa_recalls(client, vehicle["make"], vehicle["model"], vehicle["year"])
        repairpal = await fetch_repairpal(vehicle["make"], vehicle["model"], vehicle["year"])
        carcomp = await fetch_carcomplaints(vehicle["make"], vehicle["model"], vehicle["year"])
        reddit = await fetch_reddit(vehicle["make"], vehicle["model"], code)

        record = {
            "vehicle": vehicle,
            "code": code,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "sources": {
                "nhtsa_complaints": nhtsa_c,
                "nhtsa_recalls": nhtsa_r,
                "repairpal": repairpal,
                "carcomplaints": carcomp,
                "reddit": reddit,
            },
        }

        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
        tmp.replace(out)

        summary = (
            f"[{index}/{total}] {label} - "
            f"NHTSA: {summarize_nhtsa(nhtsa_c)}, "
            f"Recalls: {summarize_nhtsa(nhtsa_r)}, "
            f"RepairPal: {summarize_repairpal(repairpal)}, "
            f"CarComplaints: {summarize_carcomplaints(carcomp)}, "
            f"Reddit: {summarize_reddit(reddit)}"
        )
        return "processed", summary
    except Exception as e:
        return "failed", f"[{index}/{total}] {label} - FAILED: {e!r}"


# --- Main ------------------------------------------------------------------

async def run(force: bool, max_seconds: float) -> int:
    _log_init()
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    combos = [(v, c) for v in TOP_VEHICLES for c in TOP_50_CODES]
    total = len(combos)
    log(f"=== ClearDrive training-data scraper v2 ===")
    log(
        f"Vehicles: {len(TOP_VEHICLES)}, codes: {len(TOP_50_CODES)}, "
        f"combos: {total}"
    )
    log(
        f"Sources: nhtsa_complaints, nhtsa_recalls, repairpal, "
        f"carcomplaints, reddit (lean wrapper)"
    )
    log(f"Output root: {RAW_DIR}")
    log(f"Hard timeout: {max_seconds/3600:.2f}h, force={force}")

    start = time.monotonic()
    processed = skipped = failed = 0

    async with httpx.AsyncClient(headers=HTTP_HEADERS, follow_redirects=True) as client:
        for i, (vehicle, code) in enumerate(combos, 1):
            if time.monotonic() - start > max_seconds:
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

    elapsed_min = (time.monotonic() - start) / 60
    log(
        f"Run complete. processed={processed} skipped={skipped} "
        f"failed={failed} elapsed={elapsed_min:.1f}min "
        f"unique_upstream(approx)="
        f"nhtsa_c={len(_nhtsa_complaints_cache)} "
        f"nhtsa_r={len(_nhtsa_recalls_cache)} "
        f"repairpal={len(_repairpal_cache)} "
        f"carcomp={len(_carcomp_cache)} "
        f"reddit={len(_reddit_cache)}"
    )
    return 0 if failed == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Collect raw training-data corpus across ~300 US-market vehicles "
            "and 50 OBD-II codes from 5 sources. Designed to run unattended "
            "overnight; idempotent re-runs skip already-fetched combinations."
        )
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch combinations even if the output file already exists.",
    )
    parser.add_argument(
        "--max-hours",
        type=float,
        default=DEFAULT_MAX_HOURS,
        help=(
            "Hard timeout in hours (default: 8.0). The run stops cleanly "
            "before starting the next combination once this is exceeded."
        ),
    )
    args = parser.parse_args()
    if args.max_hours <= 0:
        sys.exit("--max-hours must be positive")

    try:
        exit_code = asyncio.run(run(force=args.force, max_seconds=args.max_hours * 3600))
    except KeyboardInterrupt:
        log("Interrupted by user.")
        exit_code = 130
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
