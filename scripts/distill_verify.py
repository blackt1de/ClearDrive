"""Brief 2c acceptance checks over the finished training files.

  2  train.jsonl has 3,000 to 5,000 pairs; val.jsonl is about 5%
  3  no pair matches an eval case on URL or (year, make, model, DTC), or a codeless profile
     on (year, make, model)
  4  every pair passes the schema and grounding checks (scripts/distill_filter.py, re-run)
  5  system prompt and user layout are byte-identical to what the backend sends: the system
     prompt equals ollama_client.SYSTEM_PROMPT, and a random sample of pairs is rebuilt
     through the backend and compared (the retrieved_at timestamps are masked; they are the
     only part of the prompt that changes between two builds)
  6  MANIFEST.json hashes match the files

Run with the backend's dependencies (.venv-distill):
    python scripts/distill_verify.py
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import json
import random
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
TRAIN = REPO / "data" / "train"
EVAL = REPO / "eval"
REBUILD_SAMPLE = 100
SEED = 42
TIMESTAMP_RE = re.compile(r'retrieved_at="[^"]*"')


def norm(s) -> str:
    return re.sub(r"[\s\-]", "", str(s)).upper()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


async def main() -> int:
    import distill_build
    import distill_filter
    with contextlib.redirect_stdout(io.StringIO()):
        import knowledge
        import main as backend
        import ollama_client

    ok = True

    def check(name: str, passed: bool, detail: str) -> None:
        nonlocal ok
        ok = ok and passed
        print(f"{'PASS' if passed else 'FAIL'}  {name}: {detail}")

    lines = {n: [json.loads(l) for l in (TRAIN / n).open(encoding="utf-8")]
             for n in ("train.jsonl", "val.jsonl", "cleardrive_sft.jsonl")}
    n_train, n_val = len(lines["train.jsonl"]), len(lines["val.jsonl"])
    check("2 pair count", 3000 <= n_train <= 5000, f"train {n_train}, val {n_val} "
          f"({n_val / (n_train + n_val):.1%} of {n_train + n_val})")

    by_user = {r["user"]: r for r in (json.loads(l) for l in (TRAIN / "filtered.jsonl").open(encoding="utf-8"))}
    urls = {r["record_id"]: r.get("url") for r in
            (json.loads(l) for l in (TRAIN / "sample.jsonl").open(encoding="utf-8"))}
    pairs = []
    for row in lines["cleardrive_sft.jsonl"]:
        system, user, assistant = (m["content"] for m in row["messages"])
        pairs.append({**by_user[user], "system": system, "target": assistant})

    cases = json.loads((EVAL / "eval_set.json").read_text(encoding="utf-8"))["cases"]
    profiles = json.loads((EVAL / "codeless_set.json").read_text(encoding="utf-8"))["profiles"]
    eval_odi, eval_tuples, held = set(), set(), set()
    for c in cases:
        if m := re.search(r"odiNumber=(\d+)", (c.get("ground_truth") or {}).get("source_url") or ""):
            eval_odi.add(m.group(1))
        v = (int(c["vehicle"]["year"]), norm(c["vehicle"]["make"]), norm(c["vehicle"]["model"]))
        held.add(v)
        eval_tuples.update((*v, d["code"].upper()) for d in c["payload"]["snapshot"]["dtc_codes"])
    for p in profiles:
        held.add((int(p["vehicle"]["year"]), norm(p["vehicle"]["make"]), norm(p["vehicle"]["model"])))
    hits = {"url": 0, "tuple": 0, "vehicle": 0}
    for p in pairs:
        v = (int(p["vehicle"]["year"]), norm(p["vehicle"]["make"]), norm(p["vehicle"]["model"]))
        m = re.search(r"odiNumber=(\d+)", urls.get(p["record_id"]) or "")
        hits["url"] += bool(m and m.group(1) in eval_odi)
        hits["tuple"] += any((*v, d) in eval_tuples for d in p["dtcs"])
        hits["vehicle"] += v in held
    check("3 eval overlap", not any(hits.values()), f"{hits} over {len(pairs)} pairs, "
          f"{len(cases)} eval cases, {len(profiles)} codeless profiles")

    failures = []
    for p in pairs:
        reason = (distill_filter.check_schema(p, p["target"], backend.parse_guidance)
                  or distill_filter.check_grounding(p, p["target"]))
        words = len(p["target"].split())
        if reason or not distill_filter.MIN_WORDS <= words <= distill_filter.MAX_WORDS:
            failures.append((p["record_id"], reason or f"{words} words"))
    check("4 schema, grounding, length", not failures, f"{len(failures)} failing of {len(pairs)}"
          + (f"; first: {failures[0]}" if failures else ""))

    systems = {p["system"] for p in pairs}
    check("5a system prompt", systems == {ollama_client.SYSTEM_PROMPT},
          f"{len(systems)} distinct system prompt(s); equals ollama_client.SYSTEM_PROMPT: "
          f"{systems == {ollama_client.SYSTEM_PROMPT}}")

    cache = json.loads((TRAIN / "nhtsa_cache.json").read_text(encoding="utf-8"))

    async def cached(issue_type, make, model, year):
        return cache[f"{issue_type}|{make}|{model}|{year}"]

    async def complaints(make, model, year):
        return await cached("c", make, model, year)

    async def recalls(make, model, year):
        return await cached("r", make, model, year)

    captured = {}

    async def capture(prompt, model=None):
        captured["user"] = prompt
        return "ERROR: prompt captured for verification; no model was called."

    async def no_image(*a, **k):
        return None

    knowledge.search_nhtsa, knowledge.search_nhtsa_recalls = complaints, recalls
    backend.ask_ollama, backend.get_vehicle_image = capture, no_image
    backend.log_scan = lambda *a, **k: None
    sample = random.Random(SEED).sample(pairs, min(REBUILD_SAMPLE, len(pairs)))
    mismatches = 0
    for p in sample:
        captured.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            await backend.interpret(backend.InterpretRequest(eval_case=distill_build.case_for(p)))
        if TIMESTAMP_RE.sub("", captured.get("user", "")) != TIMESTAMP_RE.sub("", p["user"]):
            mismatches += 1
    check("5b user layout", mismatches == 0,
          f"{len(sample)} pairs rebuilt through main.interpret; {mismatches} differ outside retrieved_at")

    manifest = json.loads((TRAIN / "MANIFEST.json").read_text(encoding="utf-8"))
    bad = [n for n, meta in manifest["files"].items() if sha256(TRAIN / n) != meta["sha256"]]
    check("6 manifest", not bad, f"{len(manifest['files'])} files hashed; mismatching: {bad or 'none'}")

    print("ALL PASS" if ok else "ACCEPTANCE FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
