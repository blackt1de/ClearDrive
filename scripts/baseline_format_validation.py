#!/usr/bin/env python3
"""Baseline format-validation experiment for base Gemma 4 E4B on ClearDrive prompts.

Calls main.interpret() directly with a mock InterpretRequest for each
(vehicle, DTC) combination. Monkey-patches `main.ask_ollama` with a spy so we
capture both:
  - the EXACT prompt main.py builds (no re-implementation), and
  - the raw model response before parse_guidance() rewrites it.

This gives us baseline numbers (format adherence, vehicle-specificity, latency,
safety-level consistency) for the H1+H2 eval matrix. Re-runnable against a
fine-tuned model by repointing ollama_client to the new endpoint or model.

Writes results to notes/baseline-gemma-format-validation-<YYYY-MM-DD>.md.

Usage:
    py -3 scripts/baseline_format_validation.py
"""

import asyncio
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Make project root importable when script is invoked directly.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import main  # noqa: E402
from main import InterpretRequest, interpret  # noqa: E402
from vehicle_data import get_available_trims  # noqa: E402


VEHICLES = [
    {
        # CarsXE expects "silverado 1500" (with space) and caches as
        # underscore-separated. Vehicle ID uses underscore so get_vehicle_by_id
        # parses model = "silverado 1500" and the cache key lines up.
        "id": "2015_chevrolet_silverado_1500",
        "year": "2015",
        "make": "chevrolet",
        "model": "silverado 1500",
        "label": "2015 Chevrolet Silverado 1500",
        "expected_engine": "5.3L V8",
    },
    {
        "id": "2018_honda_civic",
        "year": "2018",
        "make": "honda",
        "model": "civic",
        "label": "2018 Honda Civic",
        "expected_engine": "1.5L turbo I4",
    },
    {
        # User originally requested M550i (Austin's interest case) but CarsXE
        # returns 404 for M550i / 5-Series / 540i / 550i. M5 is the closest
        # available 2020 BMW V8 — same family (S63 vs N63TU), same diagnostic
        # surface (timing chain guides, oil consumption, etc.).
        "id": "2020_bmw_m5",
        "year": "2020",
        "make": "bmw",
        "model": "m5",
        "label": "2020 BMW M5 (M550i substitute)",
        "expected_engine": "4.4L twin-turbo V8 (S63)",
    },
    {
        "id": "2010_toyota_camry",
        "year": "2010",
        "make": "toyota",
        "model": "camry",
        "label": "2010 Toyota Camry",
        "expected_engine": "2.5L I4",
    },
]

CODES = ["P0420", "P0171", "P0300", "P0011", "P0455"]

EXPECTED_SECTIONS = [
    "SAFETY LEVEL",
    "WHAT'S HAPPENING",
    "LIKELY CAUSES",
    "WHAT YOU MIGHT NOTICE",
    "IF YOU IGNORE",
    "QUICK CHECKS",
    "DIY FIX",
    "WHEN TO SEE A MECHANIC",
    "ESTIMATED REPAIR COST",
    "SERVICE RECOMMENDATIONS",
    "KNOWN ISSUES",
    "OTHER OWNERS REPORT",
]


def date_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def run_one(vehicle: dict, code: str) -> dict:
    """Run a single (vehicle, code). Returns prompt + raw + parsed + elapsed."""
    captured = {"prompt": None, "raw_response": None}
    original_ask = main.ask_ollama

    async def spy_ask(prompt: str, model: str | None = None) -> str:
        captured["prompt"] = prompt
        if model is None:
            result = await original_ask(prompt)
        else:
            result = await original_ask(prompt, model)
        captured["raw_response"] = result
        return result

    main.ask_ollama = spy_ask
    try:
        req = InterpretRequest(
            vehicle_id=vehicle["id"],
            client_codes=[code],
            client_rpm=750,
            client_speed=0,
            client_coolant_temp=205,
            obd_source="BaselineValidation",
        )
        start = time.monotonic()
        parsed = await interpret(req)
        elapsed = time.monotonic() - start
    finally:
        main.ask_ollama = original_ask

    return {
        "vehicle": vehicle,
        "code": code,
        "prompt": captured["prompt"],
        "raw_response": captured["raw_response"],
        "parsed": parsed,
        "elapsed_seconds": elapsed,
    }


def score_format_adherence(raw: str | None) -> tuple[int, list[str], list[str]]:
    """Count how many of the 12 expected section headers appear in raw text."""
    if not raw:
        return 0, [], list(EXPECTED_SECTIONS)
    raw_upper = raw.upper()
    found, missing = [], []
    for sec in EXPECTED_SECTIONS:
        if sec.upper() in raw_upper:
            found.append(sec)
        else:
            missing.append(sec)
    return len(found), found, missing


def extract_safety_level(raw: str | None) -> str | None:
    if not raw:
        return None
    m = re.search(r"SAFETY LEVEL[:\s]+(SAFE|CAUTION|STOP)", raw, re.IGNORECASE)
    return m.group(1).upper() if m else None


async def prewarm_trim_cache() -> dict[str, int]:
    """Populate the vehicle trim cache so get_vehicle_by_id() actually returns data."""
    results = {}
    for vehicle in VEHICLES:
        print(f"  prewarm: {vehicle['label']}...", end=" ", flush=True)
        try:
            trims = await get_available_trims(vehicle["year"], vehicle["make"], vehicle["model"])
            n = len(trims) if trims else 0
            print(f"{n} trims")
            results[vehicle["id"]] = n
        except Exception as e:
            print(f"ERROR: {e!r}")
            results[vehicle["id"]] = 0
    return results


async def main_async() -> None:
    print("Prewarming trim cache (CarsXE lookups for each test vehicle):")
    await prewarm_trim_cache()
    print()

    results: list[dict] = []
    total = len(VEHICLES) * len(CODES)
    idx = 0
    for vehicle in VEHICLES:
        for code in CODES:
            idx += 1
            print(f"[{idx}/{total}] {vehicle['label']} -- {code}", flush=True)
            try:
                r = await run_one(vehicle, code)
                r["fmt_score"], r["fmt_found"], r["fmt_missing"] = score_format_adherence(r["raw_response"])
                r["safety_level_raw"] = extract_safety_level(r["raw_response"])
                results.append(r)
                print(
                    f"   format: {r['fmt_score']}/12 | "
                    f"safety: {r['safety_level_raw']} | "
                    f"{r['elapsed_seconds']:.1f}s",
                    flush=True,
                )
            except Exception as e:
                print(f"   ERROR: {e!r}", flush=True)
                results.append({"vehicle": vehicle, "code": code, "error": repr(e)})

    write_report(results)


def write_report(results: list[dict]) -> None:
    out = PROJECT_ROOT / "notes" / f"baseline-gemma-format-validation-{date_str()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    with open(out, "w", encoding="utf-8") as fh:
        fh.write(f"# Base Gemma 4 E4B -- format validation baseline\n\n")
        fh.write(f"**Date:** {date_str()} (UTC)\n")
        fh.write(
            f"**Setup:** `gemma4:e4b` on A4500 via `ollama_client.py` (/api/chat). "
            f"Prompts built by `main.interpret()`, captured via spy on `main.ask_ollama`.\n"
        )
        fh.write(f"**Scenarios:** {len(CODES)} DTCs x {len(VEHICLES)} vehicles = {len(CODES) * len(VEHICLES)}.\n\n")

        # --- Format-adherence grid -------------------------------------------------
        fh.write("## Format-adherence grid (sections present / 12)\n\n")
        fh.write("| Vehicle | " + " | ".join(CODES) + " |\n")
        fh.write("|" + "---|" * (len(CODES) + 1) + "\n")
        for vehicle in VEHICLES:
            row = [f"**{vehicle['label']}**"]
            for code in CODES:
                r = next(
                    (x for x in results if x["vehicle"]["id"] == vehicle["id"] and x["code"] == code),
                    None,
                )
                if r is None or "error" in r:
                    row.append("ERR")
                else:
                    row.append(f"{r['fmt_score']}/12")
            fh.write("| " + " | ".join(row) + " |\n")
        fh.write("\n")

        # --- Latency grid ----------------------------------------------------------
        fh.write("## Latency grid (seconds)\n\n")
        fh.write("| Vehicle | " + " | ".join(CODES) + " |\n")
        fh.write("|" + "---|" * (len(CODES) + 1) + "\n")
        for vehicle in VEHICLES:
            row = [f"**{vehicle['label']}**"]
            for code in CODES:
                r = next(
                    (x for x in results if x["vehicle"]["id"] == vehicle["id"] and x["code"] == code),
                    None,
                )
                if r is None or "error" in r:
                    row.append("ERR")
                else:
                    row.append(f"{r['elapsed_seconds']:.0f}s")
            fh.write("| " + " | ".join(row) + " |\n")
        fh.write("\n")

        # --- Safety-level consistency ----------------------------------------------
        fh.write("## Safety-level consistency (per DTC across vehicles)\n\n")
        fh.write("| DTC | " + " | ".join(v["label"].split()[-1] for v in VEHICLES) + " | Consistent? |\n")
        fh.write("|" + "---|" * (len(VEHICLES) + 2) + "\n")
        for code in CODES:
            sls = []
            for vehicle in VEHICLES:
                r = next(
                    (x for x in results if x["vehicle"]["id"] == vehicle["id"] and x["code"] == code),
                    None,
                )
                sls.append(r.get("safety_level_raw") if r and "error" not in r else "ERR")
            seen = {s for s in sls if s and s != "ERR"}
            consistent = "yes" if len(seen) <= 1 else "no"
            fh.write(f"| {code} | {' | '.join(s or 'NONE' for s in sls)} | {consistent} |\n")
        fh.write("\n")

        # --- Vehicle-specificity grid (to be filled manually) ----------------------
        fh.write("## Vehicle-specificity grid (1=generic name-swap, 5=highly specific)\n\n")
        fh.write("*Filled in below the responses by reading them.*\n\n")
        fh.write("| Vehicle | " + " | ".join(CODES) + " |\n")
        fh.write("|" + "---|" * (len(CODES) + 1) + "\n")
        for vehicle in VEHICLES:
            row = [f"**{vehicle['label']}**"]
            for _ in CODES:
                row.append("__")
            fh.write("| " + " | ".join(row) + " |\n")
        fh.write("\n")

        # --- Per-scenario detail ---------------------------------------------------
        fh.write("## Per-scenario detail\n\n")
        for r in results:
            v = r["vehicle"]
            fh.write(f"### {v['label']} ({v['expected_engine']}) -- {r['code']}\n\n")
            if "error" in r:
                fh.write(f"**ERROR:** `{r['error']}`\n\n---\n\n")
                continue
            fh.write(f"- Latency: **{r['elapsed_seconds']:.1f}s**\n")
            fh.write(f"- Format adherence: **{r['fmt_score']}/12**\n")
            if r["fmt_missing"]:
                fh.write(f"- Missing sections: {', '.join(r['fmt_missing'])}\n")
            fh.write(f"- Safety level extracted: **{r['safety_level_raw']}**\n\n")
            fh.write("**Raw response:**\n\n")
            fh.write("```\n")
            fh.write((r["raw_response"] or "(empty)").strip())
            fh.write("\n```\n\n")
            fh.write("**Scoring (manual):**\n\n")
            fh.write("- Vehicle-specificity (1-5): __\n")
            fh.write("- Known-issues quality (real / plausible-generic / hallucinated): __\n")
            fh.write("- Notes:\n\n")
            fh.write("---\n\n")

        # --- Honest assessment placeholder ----------------------------------------
        fh.write("## Honest assessment\n\n")
        fh.write("*Filled in after reading the 20 responses.*\n\n")
        fh.write("### What base Gemma 4 E4B does well\n\n- \n\n")
        fh.write("### What it does poorly\n\n- \n\n")
        fh.write("### What fine-tuning needs to fix\n\n- \n\n")

    print(f"\nReport written to {out}", flush=True)


if __name__ == "__main__":
    asyncio.run(main_async())
