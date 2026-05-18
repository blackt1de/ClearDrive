#!/usr/bin/env python3
"""CarComplaints-only backfill for vehicles hit by the `.title()` bug.

Why this exists
---------------
`code_scraper.py:239` used to call `base_model.title().replace(" ", "_")` to
build the CarComplaints URL. Python's `str.title()` mangles multi-letter
prefixes ("GLC300" -> "Glc300", "CR-V" -> "Cr-V"), and CarComplaints serves
404 on case-mismatched paths. 39 vehicles in the corpus have `carcomplaints:
{}` for every P-code as a result. See GLC300_INVESTIGATION.md for the full
analysis.

The bug is fixed at `code_scraper.py:241` (now `base_model.replace(" ", "_")`
without `.title()`). This script re-fetches CarComplaints for any vehicle
where `extract_base_model(model).title() != extract_base_model(model)` AND
the stored blob is `{}`. ~33 unique (year, make, model) vehicles, 1 fetch
each (memoized) -> a few minutes total.

What gets touched
-----------------
- Walks `training_data/raw/*/*.json`.
- A FILE is in scope iff `sources.carcomplaints == {}` AND no
  `carcomplaints_backfill_at` key.
- A VEHICLE is in scope iff `extract_base_model(model).title() != ...`
  (i.e. the .title() bug would have mangled its URL).
- Per-vehicle: ONE call to `scrape_car_complaints(make, model, year, ...)`.
  Result is written into every in-scope code file under that vehicle's dir.
- `sources.carcomplaints` is replaced with the new dict (the original was
  `{}`, no data to merge). A `carcomplaints_backfill_at` ISO timestamp is
  added to `sources` for traceability and idempotency.
- Atomic writes: write to `{path}.tmp` then rename.

Idempotency / resume
--------------------
- A second run sees the per-file backfill stamp and skips with no upstream
  calls.
- Interrupted mid-vehicle: any files written so far are stamped; remaining
  unstamped files in that vehicle are picked up on the next run.

Usage
-----
    py -3 backfill_carcomplaints.py --dry-run    # report scope, no calls
    py -3 backfill_carcomplaints.py              # run for real
"""

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from code_scraper import extract_base_model, scrape_car_complaints


DATA_ROOT = Path(__file__).parent / "training_data"
RAW_DIR = DATA_ROOT / "raw"
LOG_FILE = DATA_ROOT / "backfill_carcomplaints.log"

PER_VEHICLE_COOLDOWN_SECONDS = 1.5

_log_handle = None


def _log_init() -> None:
    global _log_handle
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _log_handle = open(LOG_FILE, "a", encoding="utf-8")


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if _log_handle:
        _log_handle.write(line + "\n")
        _log_handle.flush()


def model_was_mangled(model: str) -> bool:
    """True iff str.title() changes the base model (i.e. URL would have 404'd)."""
    base = extract_base_model(model) or ""
    return base.title() != base


def load_combo(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        log(f"  parse fail {path.name}: {exc!r}")
        return None


def atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    tmp.replace(path)


def scan() -> tuple[dict, dict]:
    """Walk raw dir. Returns (in_scope_by_vehicle, counters).

    in_scope_by_vehicle: { vehicle_dir_name: { "vehicle": dict, "files": [Path...] } }
    counters: scan-time stats.
    """
    in_scope: dict[str, dict] = {}
    counters = defaultdict(int)

    for vehicle_dir in sorted(RAW_DIR.iterdir()):
        if not vehicle_dir.is_dir():
            continue
        files = sorted(vehicle_dir.glob("*.json"))
        counters["files_total"] += len(files)
        if not files:
            continue

        # Use the first file to read the model name (vehicle metadata is identical).
        sample = load_combo(files[0])
        if not sample:
            counters["parse_fail"] += 1
            continue
        veh = sample.get("vehicle", {})
        model = veh.get("model", "")
        if not model:
            counters["no_model"] += 1
            continue
        if not model_was_mangled(model):
            counters["not_bug_condition"] += len(files)
            continue

        # This vehicle's model satisfies the bug condition. Filter files.
        vehicle_in_scope_files: list[Path] = []
        for path in files:
            combo = load_combo(path)
            if not combo:
                counters["parse_fail"] += 1
                continue
            sources = combo.get("sources", {})
            cc = sources.get("carcomplaints", {})
            if sources.get("carcomplaints_backfill_at"):
                counters["already_backfilled"] += 1
                continue
            if cc:  # non-empty already
                counters["already_populated"] += 1
                continue
            vehicle_in_scope_files.append(path)

        if vehicle_in_scope_files:
            in_scope[vehicle_dir.name] = {
                "vehicle": veh,
                "files": vehicle_in_scope_files,
            }
            counters["in_scope_files"] += len(vehicle_in_scope_files)
            counters["in_scope_vehicles"] += 1

    return in_scope, counters


async def run_vehicle(vehicle: dict, files: list[Path], dry_run: bool) -> tuple[int, dict]:
    """Fetch CarComplaints once for this vehicle, write into all in-scope files.

    Returns (files_written, fetched_result_summary).
    """
    make = vehicle.get("make", "")
    model = vehicle.get("model", "")
    year = str(vehicle.get("year", ""))
    trim = vehicle.get("trim", "") or ""
    engine = vehicle.get("engine", "") or ""

    if dry_run:
        log(f"  [dry] {year} {make} {model} -- would fetch, write to {len(files)} files")
        return 0, {}

    try:
        result = await scrape_car_complaints(make, model, year, trim, engine)
    except Exception as exc:
        log(f"  fetch ERROR {year} {make} {model}: {exc!r}")
        return 0, {}

    if not result:
        # Empty result. Still stamp the files so we don't retry indefinitely.
        result_for_storage: dict = {}
        summary = {"empty": True}
    else:
        result_for_storage = result
        summary = {
            "worst_problems": len(result.get("worst_problems", [])),
            "recalls": result.get("recalls", 0),
            "tsbs": result.get("tsbs", 0),
            "complaints_count": result.get("complaints_count", 0),
        }

    stamp = datetime.now(timezone.utc).isoformat()
    written = 0
    for path in files:
        combo = load_combo(path)
        if not combo:
            continue
        sources = combo.setdefault("sources", {})
        sources["carcomplaints"] = result_for_storage
        sources["carcomplaints_backfill_at"] = stamp
        atomic_write(path, combo)
        written += 1

    log(f"  {year} {make} {model} -> wrote {written} files, summary={summary}")
    return written, summary


async def main_async(args: argparse.Namespace) -> int:
    _log_init()
    log(f"backfill_carcomplaints starting | dry_run={args.dry_run}")

    in_scope, counters = scan()
    log(f"Scan complete:")
    log(f"  files_total:        {counters['files_total']}")
    log(f"  in_scope_vehicles:  {counters['in_scope_vehicles']}")
    log(f"  in_scope_files:     {counters['in_scope_files']}")
    log(f"  not_bug_condition:  {counters['not_bug_condition']}")
    log(f"  already_backfilled: {counters['already_backfilled']}")
    log(f"  already_populated:  {counters['already_populated']}")
    log(f"  parse_fail:         {counters['parse_fail']}")

    if not in_scope:
        log("Nothing to do.")
        return 0

    log(f"In-scope vehicles:")
    for name in sorted(in_scope):
        veh = in_scope[name]["vehicle"]
        n = len(in_scope[name]["files"])
        log(f"  {veh.get('year')} {veh.get('make')} {veh.get('model')}  ({n} files)")

    if args.dry_run:
        log("DRY RUN -- no upstream calls, no files modified.")
        return 0

    start = time.monotonic()
    total_written = 0
    populated_vehicles = 0

    for idx, name in enumerate(sorted(in_scope), 1):
        entry = in_scope[name]
        log(f"[{idx}/{len(in_scope)}] {name}")
        written, summary = await run_vehicle(entry["vehicle"], entry["files"], dry_run=False)
        total_written += written
        if summary and not summary.get("empty"):
            populated_vehicles += 1
        # Per-vehicle cooldown so we don't hammer CarComplaints.
        if idx < len(in_scope):
            await asyncio.sleep(PER_VEHICLE_COOLDOWN_SECONDS)

    elapsed = (time.monotonic() - start) / 60.0
    log(
        f"Run complete. vehicles={len(in_scope)} populated={populated_vehicles} "
        f"files_written={total_written} elapsed={elapsed:.1f}min"
    )
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill CarComplaints for vehicles hit by the .title() bug.")
    p.add_argument("--dry-run", action="store_true", help="Report scope, do not fetch or write.")
    return p.parse_args()


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async(parse_args())))
