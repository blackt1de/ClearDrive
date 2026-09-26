#!/usr/bin/env python3
"""Run the frozen eval set against a live /interpret (Brief 2a, step 10).

Sends every case in eval/eval_set.json and eval/codeless_set.json as
{"eval_case": {"case_id", **payload}}, in file order, one at a time (latency is
per call, not under load). Saves each raw response to
eval/runs/<run_id>/<case_id>.json plus run_meta.json.

Before the first case it sends one warm-up request, so the model's cold load
does not land in the latency numbers. The warm-up is recorded in run_meta and
excluded from scoring.

The serving condition is read from /health and must match --expect-model and
--expect-think, or the run refuses to start. A transport error is retried once,
then recorded as a failure. Never edits the eval files.

Run:
    .venv/bin/python scripts/eval_run.py --run-id base-qwen3-14b-2026-09-26 \
        --expect-model cleardrive-qwen --expect-think default
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "eval"
WARMUP = {"scenario": "f150-2015-p0301-coil"}
TRUNCATION_LIMIT = 0.05  # ruling 2026-09-25: over 5% truncated stops the run before scoring
FAILURE_LIMIT = 0.05     # the same limit for failed calls (review 2026-09-26)
# Longer than ollama_client.MODEL_TIMEOUT_S (300 s), so a slow model call comes back
# as the backend's own classified error instead of a transport timeout here.
DEFAULT_TIMEOUT_S = 330.0


def load_items():
    cases = json.loads((EVAL / "eval_set.json").read_text())["cases"]
    profiles = json.loads((EVAL / "codeless_set.json").read_text())["profiles"]
    return cases + profiles


def request_body(item):
    return {"eval_case": {"case_id": item["case_id"], **item["payload"]}}


def post_with_retry(client, url, body, timeout, sleep=time.sleep):
    """(status, json_or_None, error_or_None, seconds). One retry on a transport error."""
    last_error = None
    for attempt in range(2):
        t0 = time.monotonic()
        try:
            r = client.post(url, json=body, timeout=timeout)
            secs = time.monotonic() - t0
            try:
                return r.status_code, r.json(), None if r.status_code == 200 else f"HTTP {r.status_code}", secs
            except ValueError:
                return r.status_code, None, f"HTTP {r.status_code}: non-JSON body", secs
        except httpx.TransportError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt == 0:
                sleep(5)
    return None, None, last_error, None


def call_error(status, body, transport_error):
    """Why a call failed, or None. /interpret reports a model failure as HTTP 200
    with dont_panic "ERROR: ...", so a 200 is not enough to count as a success."""
    if transport_error:
        return transport_error
    if status != 200:
        return f"HTTP {status}"
    if body is None:
        return "non-JSON body"
    if "error" in body:
        return f"backend error: {body['error']}"
    if str(body.get("dont_panic", "")).startswith("ERROR:"):
        return f"model error: {body['dont_panic'][:160]}"
    if body.get("finish_reason") is None:
        return "no finish_reason: the model's completion state is unknown"
    return None


def failure_summary(calls):
    scored = [c for c in calls if not c.get("warmup")]
    failed = [c["case_id"] for c in scored if c.get("error")]
    share = len(failed) / len(scored) if scored else 0.0
    return {"failed": len(failed), "calls": len(scored), "share": round(share, 4),
            "limit": FAILURE_LIMIT, "gate": "FAIL" if share > FAILURE_LIMIT else "PASS",
            "case_ids": failed}


def serving_condition(client, base_url):
    health = client.get(f"{base_url}/health", timeout=30).json()
    return health.get("serving", {}), health


def check_condition(serving, expect_model, expect_think):
    problems = []
    if serving.get("model") != expect_model:
        problems.append(f"serving model {serving.get('model')!r} != expected {expect_model!r}")
    if serving.get("think") != expect_think:
        problems.append(f"serving think {serving.get('think')!r} != expected {expect_think!r}")
    return problems


def truncation_summary(calls):
    scored = [c for c in calls if not c.get("warmup")]
    truncated = [c["case_id"] for c in scored if c.get("finish_reason") == "length"]
    share = len(truncated) / len(scored) if scored else 0.0
    return {"truncated": len(truncated), "calls": len(scored), "share": round(share, 4),
            "limit": TRUNCATION_LIMIT, "gate": "FAIL" if share > TRUNCATION_LIMIT else "PASS",
            "case_ids": truncated}


def _git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True).stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--expect-model", required=True)
    ap.add_argument("--expect-think", required=True, choices=["default", "off"])
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    ap.add_argument("--limit", type=int, default=None, help="first N items only (dry runs)")
    args = ap.parse_args()

    out = EVAL / "runs" / args.run_id
    if out.exists():
        sys.exit(f"{out} exists; a run id is used once")
    items = load_items()[: args.limit]
    url = f"{args.base_url}/interpret"
    with httpx.Client() as client:
        serving, health = serving_condition(client, args.base_url)
        problems = check_condition(serving, args.expect_model, args.expect_think)
        if problems:
            sys.exit("REFUSING TO RUN: " + "; ".join(problems))
        out.mkdir(parents=True)
        meta = {"run_id": args.run_id, "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "base_url": args.base_url, "serving": serving, "health": health,
                "backend_commit": _git("rev-parse", "HEAD"),
                "backend_tree_clean": _git("status", "--porcelain", "--untracked-files=no") == "",
                "eval_manifest": json.loads((EVAL / "MANIFEST.json").read_text())["sha256"],
                "calls": []}
        try:
            meta["ollama_ps"] = httpx.get("http://localhost:11434/api/ps", timeout=10).json()
        except Exception as exc:  # recorded, not fatal: the run is about /interpret
            meta["ollama_ps"] = f"unavailable: {exc}"
        status, body, error, secs = post_with_retry(client, url, WARMUP, args.timeout)
        error = call_error(status, body, error)
        meta["calls"].append({"case_id": "warmup", "warmup": True, "status": status, "error": error,
                              "seconds": round(secs, 2) if secs else None,
                              "finish_reason": (body or {}).get("finish_reason")})
        if error:
            # A failed warm-up would move the cold load onto the first scored case.
            (out / "run_meta.json").write_text(json.dumps(meta, indent=1))
            sys.exit(f"WARM-UP FAILED ({error}); run aborted before any scored case")
        t_run = time.monotonic()
        for i, item in enumerate(items, 1):
            status, body, error, secs = post_with_retry(client, url, request_body(item), args.timeout)
            if body is not None:
                (out / f"{item['case_id']}.json").write_text(json.dumps(body, indent=1))
            error = call_error(status, body, error)
            meta["calls"].append({"case_id": item["case_id"], "status": status, "error": error,
                                  "seconds": round(secs, 2) if secs else None,
                                  "finish_reason": (body or {}).get("finish_reason")})
            print(f"[{i}/{len(items)}] {item['case_id']} {status} {secs and round(secs, 1)}s "
                  f"{(body or {}).get('finish_reason')} {error or ''}", flush=True)
        meta["wall_seconds"] = round(time.monotonic() - t_run, 1)
    meta["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta["truncation"] = truncation_summary(meta["calls"])
    meta["failure"] = failure_summary(meta["calls"])
    (out / "run_meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps({k: meta[k] for k in ("failure", "truncation", "wall_seconds")}, indent=1))
    if meta["truncation"]["gate"] == "FAIL":
        sys.exit("TRUNCATION GATE FAILED: stop and report before scoring")
    if meta["failure"]["gate"] == "FAIL":
        sys.exit("FAILURE GATE FAILED: stop and report before scoring")


if __name__ == "__main__":
    main()
