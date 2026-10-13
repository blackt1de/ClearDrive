"""Brief 2c step 5: synthesize one target per built prompt with Claude Opus.

Model: claude-opus-5-5 through the Anthropic API directly (decisions.md 2026-09-25,
ruling 7). It is not an eval-condition model. The instruction is the fixed text in
data/train/synthesis_prompt.txt and is never varied per record; the record's own content
arrives only as the backend's system and user prompts (scripts/distill_build.py).

No temperature is sent: claude-opus-5-5 rejects the parameter with a 400 ("`temperature`
is deprecated for this model"), so brief 2c's 0.3 cannot be set. No refusal fallback is
configured either, because a fallback would let a second model write targets.

Raw API output is saved per record to data/train/raw_targets/<record_id>.json and a record
with a saved file is skipped, so the run resumes after an interruption.

    python scripts/distill_synthesize.py [--limit N] [--effort medium]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

import anthropic

REPO = Path(__file__).resolve().parent.parent
TRAIN = REPO / "data" / "train"
PROMPTS = TRAIN / "prompts.jsonl"
SYNTHESIS_PROMPT = TRAIN / "synthesis_prompt.txt"
RAW_DIR = TRAIN / "raw_targets"
COST = TRAIN / "synthesis_cost.json"

MODEL = "claude-opus-5-5"
CONCURRENCY = 16
MAX_TOKENS = 16000          # thinking tokens count against this
USD_PER_MTOK_IN, USD_PER_MTOK_OUT = 4.00, 20.00   # claude-opus-5-5 list price


def raw_path(record_id: str) -> Path:
    return RAW_DIR / (re.sub(r"[^A-Za-z0-9_-]", "_", record_id) + ".json")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="only the first N pending records")
    ap.add_argument("--effort", default="medium", choices=["low", "medium", "high"])
    ap.add_argument("--prompts", type=Path, default=PROMPTS, help="alternative prompts file (pilot)")
    args = ap.parse_args()

    instruction = SYNTHESIS_PROMPT.read_text(encoding="utf-8")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in args.prompts.open(encoding="utf-8")]
    pending = [r for r in rows if not raw_path(r["record_id"]).exists()]
    if args.limit:
        pending = pending[:args.limit]
    print(f"{len(rows)} prompts, {len(rows) - len(pending)} already done or out of this run, "
          f"{len(pending)} to synthesize; effort={args.effort}, concurrency={CONCURRENCY}")

    client = anthropic.AsyncAnthropic(max_retries=2)   # brief: retry twice on transport error
    sem = asyncio.Semaphore(CONCURRENCY)
    totals = {"calls": 0, "ok": 0, "failed": 0, "input_tokens": 0, "output_tokens": 0}
    started = time.time()

    def dollars() -> float:
        return (totals["input_tokens"] * USD_PER_MTOK_IN
                + totals["output_tokens"] * USD_PER_MTOK_OUT) / 1e6

    async def one(row):
        user = (f"<backend_system>\n{row['system']}\n</backend_system>\n\n"
                f"<backend_user>\n{row['user']}\n</backend_user>")
        async with sem:
            try:
                msg = await client.messages.create(
                    model=MODEL, max_tokens=MAX_TOKENS, system=instruction,
                    output_config={"effort": args.effort},
                    messages=[{"role": "user", "content": user}],
                )
            except anthropic.RateLimitError as exc:
                error = f"rate_limit: {exc.message}"
            except anthropic.APIStatusError as exc:
                error = f"http_{exc.status_code}: {exc.message}"
            except anthropic.APIConnectionError as exc:
                error = f"connection: {exc!r}"
            else:
                error = None
        totals["calls"] += 1
        if error:
            totals["failed"] += 1      # no file is written, so the next run retries it
            print(f"FAILED {row['record_id']}: {error[:200]}")
            return
        totals["ok"] += 1
        totals["input_tokens"] += msg.usage.input_tokens
        totals["output_tokens"] += msg.usage.output_tokens
        text = "".join(b.text for b in msg.content if b.type == "text")
        raw_path(row["record_id"]).write_text(json.dumps({
            "record_id": row["record_id"], "model": msg.model, "request_id": msg._request_id,
            "stop_reason": msg.stop_reason, "effort": args.effort,
            "usage": {"input_tokens": msg.usage.input_tokens,
                      "output_tokens": msg.usage.output_tokens},
            "target": text,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        if totals["ok"] % 100 == 0:
            print(f"  {totals['ok']} ok / {totals['failed']} failed; "
                  f"in {totals['input_tokens']:,} out {totals['output_tokens']:,} tokens; "
                  f"${dollars():.2f}; {time.time() - started:.0f}s", flush=True)

    await asyncio.gather(*(one(r) for r in pending))

    history = json.loads(COST.read_text(encoding="utf-8")) if COST.exists() else {"runs": []}
    history["runs"].append({**totals, "usd": round(dollars(), 2), "effort": args.effort,
                            "model": MODEL, "seconds": round(time.time() - started),
                            "finished": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    for k in ("calls", "ok", "failed", "input_tokens", "output_tokens"):
        history[f"total_{k}"] = sum(r[k] for r in history["runs"])
    history["total_usd"] = round(sum(r["usd"] for r in history["runs"]), 2)
    COST.write_text(json.dumps(history, indent=2), encoding="utf-8")
    print(f"this run: {totals['ok']} ok, {totals['failed']} failed, "
          f"in {totals['input_tokens']:,} out {totals['output_tokens']:,} tokens, ${dollars():.2f}")
    print(f"running total: {history['total_ok']} ok, ${history['total_usd']:.2f}; "
          f"raw targets on disk: {sum(1 for _ in RAW_DIR.glob('*.json'))}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
