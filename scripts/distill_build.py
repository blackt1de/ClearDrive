"""Brief 2c step 4: build the model input for every sampled record.

Each record is sent through the backend's own `/interpret` code path, in-process, as an
`eval_case`-shaped payload (vehicle, stated DTCs, every measurement null). The model call
is intercepted, so nothing is generated here: the script only captures the system prompt
and the user prompt the backend would have sent. That makes the training input
byte-identical to production by construction; no prompt text is written in this file.

The backend assembles the context itself: DTC definitions from dtc_definitions.py, NHTSA
complaints and recalls through knowledge.py, and any known_issues.json entry. NHTSA results
are cached per (endpoint, make, model, year) and fetched one vehicle at a time.

Run from the repo root with the backend's dependencies (.venv-distill):
    python scripts/distill_build.py        # writes data/train/prompts.jsonl
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
TRAIN = REPO / "data" / "train"
SAMPLE = TRAIN / "sample.jsonl"
PROMPTS = TRAIN / "prompts.jsonl"
NHTSA_CACHE = TRAIN / "nhtsa_cache.json"
BUILD_LOG = TRAIN / "build_backend_stdout.log"

NHTSA_DELAY_S = 0.5   # pause after each live NHTSA request
NHTSA_ATTEMPTS = 3

LIMITATION_CODED = ("Reconstructed from a written owner report: only the stated trouble codes "
                    "are known. No live data, freeze frame, fuel trims or Mode 06 were captured.")
LIMITATION_NO_CODES = ("Reconstructed from a written owner report: no trouble codes were stated "
                       "and no live data was captured.")


def case_for(rec: dict) -> dict:
    """An eval_case-shaped payload. Unknown vehicle facts and all measurements are null."""
    from schemas import OBDSnapshot

    v = rec["vehicle"]
    vehicle = {"year": str(v["year"]), "make": v["make"], "model": v["model"],
               "full_name": f"{v['year']} {v['make']} {v['model']}",
               "engine": None, "displacement": None, "cylinders": None, "transmission": None,
               "drive": None, "fuel_type": None, "turbocharged": None, "supercharged": None,
               "horsepower": None}
    snapshot = OBDSnapshot(
        dtc_codes=[{"code": c, "description": ""} for c in rec["dtcs"]],
        capability={"limitations": [LIMITATION_CODED if rec["dtcs"] else LIMITATION_NO_CODES]},
    ).model_dump(mode="json")
    return {"case_id": "train-" + re.sub(r"[^A-Za-z0-9_-]", "_", rec["record_id"]),
            "vehicle": vehicle, "trim": "", "snapshot": snapshot}


async def main() -> int:
    backend_out = io.StringIO()
    with contextlib.redirect_stdout(backend_out):
        import httpx
        import knowledge
        import main as backend
        import ollama_client

    cache = json.loads(NHTSA_CACHE.read_text(encoding="utf-8")) if NHTSA_CACHE.exists() else {}
    failed_lookups = set()

    async def cached_fetch(url, issue_type, limit, timeout, make, model, year):
        key = f"{issue_type}|{make}|{model}|{year}"
        if key in cache:
            return cache[key]
        for attempt in range(NHTSA_ATTEMPTS):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    results = await knowledge._nhtsa_fetch(client, url, issue_type, make, model, year, limit)
                await asyncio.sleep(NHTSA_DELAY_S)
                cache[key] = results
                return results
            except Exception as exc:
                print(f"[distill] NHTSA {key} attempt {attempt + 1} failed: {exc!r}")
                await asyncio.sleep(2.0 * (attempt + 1))
        failed_lookups.add(key)   # not cached: a failure is not an empty result
        return []

    async def search_nhtsa(make, model, year):
        return await cached_fetch(knowledge.NHTSA_API, "c", 10, 15, make, model, year)

    async def search_nhtsa_recalls(make, model, year):
        return await cached_fetch(knowledge.NHTSA_RECALLS_API, "r", 5, 10, make, model, year)

    captured = {}

    async def capture(prompt, model=None):
        captured["user"] = prompt
        return "ERROR: prompt captured for training-data build; no model was called."

    async def no_image(*args, **kwargs):
        return None

    knowledge.search_nhtsa = search_nhtsa
    knowledge.search_nhtsa_recalls = search_nhtsa_recalls
    backend.ask_ollama = capture
    backend.get_vehicle_image = no_image
    backend.log_scan = lambda *args, **kwargs: None   # the clean-scan path logs after the call

    records = [json.loads(line) for line in SAMPLE.open(encoding="utf-8")]
    if len(sys.argv) > 1:   # optional: first N records, for a dry run
        records = records[:int(sys.argv[1])]
    stats, n = Counter(), 0
    with PROMPTS.open("w", encoding="utf-8") as out:
        for rec in records:
            captured.clear()
            before = len(failed_lookups)
            with contextlib.redirect_stdout(backend_out):
                response = await backend.interpret(backend.InterpretRequest(eval_case=case_for(rec)))
            n += 1
            if len(failed_lookups) > before:
                stats["dropped_retrieval_failed"] += 1
                continue
            if "user" not in captured or response.get("error"):
                stats["dropped_backend_error"] += 1
                print(f"backend error for {rec['record_id']}: {response.get('error')}")
                continue
            path = "coded" if rec["dtcs"] else "no_codes"
            stats[path] += 1
            out.write(json.dumps({
                "record_id": rec["record_id"], "label": rec["label"], "source": rec["source"],
                "vehicle": rec["vehicle"], "dtcs": rec["dtcs"], "path": path,
                "safety_label": response.get("safety_level") if path == "coded" else None,
                "data_sources": response.get("data_sources"),
                "system": ollama_client.SYSTEM_PROMPT, "user": captured["user"],
            }, ensure_ascii=False) + "\n")
            if n % 500 == 0:
                NHTSA_CACHE.write_text(json.dumps(cache), encoding="utf-8")
                print(f"  {n}/{len(records)} built; NHTSA cache {len(cache)} entries")

    NHTSA_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    BUILD_LOG.write_text(backend_out.getvalue(), encoding="utf-8")
    print(f"records in: {len(records)}; prompts written: {stats['coded'] + stats['no_codes']} "
          f"(coded {stats['coded']}, no_codes {stats['no_codes']})")
    print(f"dropped: retrieval failed {stats['dropped_retrieval_failed']}, "
          f"backend error {stats['dropped_backend_error']}")
    print(f"NHTSA cache: {len(cache)} lookups, {sum(1 for v in cache.values() if v)} non-empty; "
          f"failed lookups: {len(failed_lookups)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
