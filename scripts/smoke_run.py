#!/usr/bin/env python3
"""Headless fixture smoke runner (Brief 1c).

Exercises the full pipeline — rules → retrieval → model → parsed response — for
every fixture scenario in fixtures.py against a RUNNING server, exactly as the
iOS client would (POST /interpret {"scenario": name}). No iOS, no pipeline code
touched: this script only reads.

Run (from the repo root, server already up):

    venv/bin/python scripts/smoke_run.py                       # server on localhost:8000
    venv/bin/python scripts/smoke_run.py --base http://localhost:8001

Outputs
    runs/smoke_<YYYY-MM-DD>/<fixture_name>.json   raw response, untouched
    runs/smoke_<YYYY-MM-DD>/summary.json          the table below, machine-readable
    a summary table on stdout, one row per fixture

Exit status is non-zero if any request errors or any response lacks `safety`.

Every column is a mechanically checkable fact; nothing here judges output
quality. "adhered" compares the SAFETY LEVEL line the model actually wrote
(read back from the `scans` table via the response's scan_id — /interpret
stores the raw model text there) against the computed legacy label in the
response. It is `n/a` when the scan row cannot be found, which happens when the
server's database is not the one at --db (e.g. a server running from a
different checkout).
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from datetime import date

import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import fixtures  # noqa: E402  (read-only: the list of scenario names)

TIERS = ("standardized_unverified", "oem_verified", "structural_only")
RETRIEVAL_NONE_SOURCES = {"CarsXE"}  # vehicle metadata, not retrieval


def model_safety_line(db_path: str, scan_id) -> str:
    """The SAFETY LEVEL label the model itself wrote, from the stored raw text."""
    if scan_id is None or not os.path.exists(db_path):
        return None
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT guidance FROM scans WHERE id = ?", (scan_id,)).fetchone()
        conn.close()
    except sqlite3.Error:
        return None
    if not row or not row[0]:
        return None
    m = re.search(r"SAFETY LEVEL\s*:\s*\**\s*([A-Z]+)", row[0])
    return m.group(1) if m else "(no SAFETY LEVEL line)"


def run_one(client: httpx.Client, base: str, name: str, db_path: str) -> dict:
    t0 = time.monotonic()
    error = None
    data = None
    try:
        r = client.post(f"{base}/interpret", json={"scenario": name})
        secs = time.monotonic() - t0
        if r.status_code != 200:
            error = f"HTTP {r.status_code}"
        else:
            data = r.json()
            if "error" in data and "safety" not in data:
                error = data["error"]
    except httpx.HTTPError as exc:
        secs = time.monotonic() - t0
        error = f"{type(exc).__name__}: {exc}"

    row = {"fixture": name, "secs": round(secs, 1), "error": error}
    if data is None:
        return row, None

    safety = data.get("safety")
    row["verdict"] = safety.get("verdict") if isinstance(safety, dict) else None
    row["safety_present"] = isinstance(safety, dict) and "verdict" in safety
    row["safety_level"] = data.get("safety_level")
    row["codes"] = [c.get("code") for c in data.get("code_definitions", [])] \
        or data.get("dtc_codes") or []
    tiers = Counter(c.get("tier") for c in data.get("code_definitions", []))
    row["tiers"] = {t: tiers.get(t, 0) for t in TIERS}
    srcs = [s for s in data.get("data_sources", []) if s not in RETRIEVAL_NONE_SOURCES]
    row["retrieval_sources"] = srcs
    written = model_safety_line(db_path, data.get("scan_id"))
    row["model_wrote"] = written
    row["adhered"] = (None if written is None
                      else written == row["safety_level"])
    # A model failure is reported by the server as prose, not a status code.
    if str(data.get("dont_panic", "")).startswith("ERROR:"):
        row["error"] = data["dont_panic"]
    return row, data


def fmt_row(r: dict) -> str:
    tiers = r.get("tiers") or {}
    tier_s = "/".join(str(tiers.get(t, 0)) for t in TIERS)
    srcs = ", ".join(r.get("retrieval_sources") or []) or "NONE"
    adhered = {True: "yes", False: "no", None: "n/a"}[r.get("adhered")]
    if r.get("adhered") is False:
        adhered += f" (wrote {r.get('model_wrote')})"
    return (f"{r['fixture']:<42} {str(r.get('verdict')):<18} "
            f"{','.join(r.get('codes') or []):<32} {tier_s:<8} {srcs:<48} "
            f"{adhered:<16} {r['secs']:>6.1f}"
            + (f"   ERROR: {r['error']}" if r.get("error") else ""))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default=os.environ.get("CLEARDRIVE_BASE", "http://localhost:8000"))
    ap.add_argument("--db", default=os.path.join(ROOT, "cleardrive.db"),
                    help="sqlite file the SERVER writes scans to (for the adhered column)")
    ap.add_argument("--out", default=os.path.join(ROOT, "runs", f"smoke_{date.today().isoformat()}"))
    ap.add_argument("--timeout", type=float, default=300.0, help="per-request seconds")
    ap.add_argument("--only", nargs="*", help="subset of fixture names")
    args = ap.parse_args()

    names = [n for n in fixtures.SCENARIOS if not args.only or n in args.only]
    os.makedirs(args.out, exist_ok=True)

    try:
        health = httpx.get(f"{args.base}/health", timeout=10).json()
    except Exception as exc:
        print(f"server at {args.base} not reachable: {exc}", file=sys.stderr)
        return 2
    print(f"server {args.base}  health={health}  fixtures={len(names)}  out={args.out}\n")

    header = (f"{'fixture':<42} {'verdict':<18} {'codes':<32} {'std/oem/struct':<8} "
              f"{'retrieval sources':<48} {'adhered':<16} {'secs':>6}")
    print(header)
    print("-" * len(header))

    rows = []
    with httpx.Client(timeout=args.timeout) as client:
        for name in names:
            row, data = run_one(client, args.base, name, args.db)
            if data is not None:
                with open(os.path.join(args.out, f"{name}.json"), "w") as fh:
                    json.dump(data, fh, indent=2, sort_keys=True)
            rows.append(row)
            print(fmt_row(row), flush=True)

    with open(os.path.join(args.out, "summary.json"), "w") as fh:
        json.dump({"base": args.base, "date": date.today().isoformat(), "rows": rows},
                  fh, indent=2)

    errors = [r for r in rows if r.get("error")]
    no_safety = [r for r in rows if not r.get("error") and not r.get("safety_present")]
    verdicts = Counter(r.get("verdict") for r in rows)
    adhered = Counter({True: "yes", False: "no", None: "n/a"}[r.get("adhered")] for r in rows)
    print(f"\n{len(rows)} fixtures · verdicts {dict(verdicts)} · adhered {dict(adhered)} · "
          f"mean {sum(r['secs'] for r in rows) / max(len(rows), 1):.1f}s")
    if errors:
        print(f"FAIL: {len(errors)} request(s) errored: {[r['fixture'] for r in errors]}")
    if no_safety:
        print(f"FAIL: {len(no_safety)} response(s) missing `safety`: {[r['fixture'] for r in no_safety]}")
    return 1 if (errors or no_safety) else 0


if __name__ == "__main__":
    sys.exit(main())
