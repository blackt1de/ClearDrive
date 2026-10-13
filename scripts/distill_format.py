"""Brief 2c step 7: write the chat-format training files and their manifest.

Each kept pair becomes one line:
  {"messages": [{"role": "system", ...}, {"role": "user", ...}, {"role": "assistant", ...}]}
The system and user content are the backend's own prompts as captured by
scripts/distill_build.py; the assistant content is the filtered Opus target.

Length: a pair is dropped (never truncated) when its rendered chat exceeds MAX_TOKENS with
the training tokenizer, using the same rendering as ml/train_qlora.py
(apply_chat_template(..., enable_thinking=False)), which refuses over-length pairs.

Split: 95/5 train/val. Validation holds out whole platforms (make + model), per the root
CLAUDE.md research-integrity rule, and the platforms are chosen greedily so the validation
label mix tracks the overall mix (brief 2c: "stratified by label").

Run in the training venv (.venv), which has the tokenizer:
    python scripts/distill_format.py
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from transformers import AutoTokenizer

REPO = Path(__file__).resolve().parent.parent
TRAIN = REPO / "data" / "train"
FILTERED = TRAIN / "filtered.jsonl"
ALL, TRAIN_FILE, VAL_FILE = TRAIN / "cleardrive_sft.jsonl", TRAIN / "train.jsonl", TRAIN / "val.jsonl"
MANIFEST = TRAIN / "MANIFEST.json"

TOKENIZER_ID = "Qwen/Qwen3-14B"
MAX_TOKENS = 8192        # ml/train_qlora.py --max-seq-length (decisions.md 2026-09-25)
VAL_FRACTION = 0.05
TARGET_PAIRS = 5000      # decisions.md 2026-09-25, ruling 7; Phase 6.1 caps train.jsonl at 5,000
SEED = 42


def platform(v: dict) -> str:
    return re.sub(r"[\s\-]", "", f"{v['make']}|{v['model']}").upper()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write(path: Path, items: list) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for it in items:
            f.write(json.dumps({"messages": it["messages"]}, ensure_ascii=False) + "\n")


def main() -> int:
    tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_ID)
    items, over = [], []
    for line in FILTERED.open(encoding="utf-8"):
        r = json.loads(line)
        messages = [{"role": "system", "content": r["system"]},
                    {"role": "user", "content": r["user"]},
                    {"role": "assistant", "content": r["target"]}]
        text = tokenizer.apply_chat_template(messages, tokenize=False,
                                             add_generation_prompt=False, enable_thinking=False)
        n_tokens = len(tokenizer(text, add_special_tokens=False)["input_ids"])
        if n_tokens > MAX_TOKENS:
            over.append({"record_id": r["record_id"], "tokens": n_tokens})
            continue
        items.append({"record_id": r["record_id"], "label": r["label"], "path": r["path"],
                      "platform": platform(r["vehicle"]), "tokens": n_tokens,
                      "messages": messages})
    if not items:
        print("FAIL: no pairs to format")
        return 1
    # More pairs survived the filter than the target: trim from the largest labels, which
    # also evens the label mix. Seeded, so the same pairs go every time.
    surplus = max(0, len(items) - TARGET_PAIRS)
    if surplus:
        rng = random.Random(SEED)
        pools = defaultdict(list)
        for it in sorted(items, key=lambda i: i["record_id"]):
            pools[it["label"]].append(it)
        for pool in pools.values():
            rng.shuffle(pool)
        for _ in range(surplus):
            biggest = max(sorted(pools), key=lambda l: len(pools[l]))
            pools[biggest].pop()
        keep = {it["record_id"] for pool in pools.values() for it in pool}
        items = [it for it in items if it["record_id"] in keep]
    systems = {it["messages"][0]["content"] for it in items}
    assert len(systems) == 1, "system prompt differs between pairs"

    by_platform = defaultdict(list)
    for it in items:
        by_platform[it["platform"]].append(it)
    overall = Counter(it["label"] for it in items)
    want = VAL_FRACTION * len(items)
    names = sorted(by_platform)
    random.Random(SEED).shuffle(names)
    val_platforms, val_labels, val_n = [], Counter(), 0

    def distance(labels: Counter, n: int) -> float:
        return sum(abs(labels[l] / n - overall[l] / len(items)) for l in overall)

    while True:
        fits = [p for p in names if p not in val_platforms and val_n + len(by_platform[p]) <= want]
        if not fits:
            break
        best = min(fits, key=lambda p: (distance(val_labels + Counter(i["label"] for i in by_platform[p]),
                                                 val_n + len(by_platform[p])), p))
        val_platforms.append(best)
        val_labels += Counter(i["label"] for i in by_platform[best])
        val_n += len(by_platform[best])

    held = set(val_platforms)
    val = [it for it in items if it["platform"] in held]
    train = [it for it in items if it["platform"] not in held]
    write(ALL, items)
    write(TRAIN_FILE, train)
    write(VAL_FILE, val)

    files = {p.name: {"sha256": sha256(p), "lines": sum(1 for _ in p.open(encoding="utf-8")),
                      "bytes": p.stat().st_size} for p in (ALL, TRAIN_FILE, VAL_FILE)}
    manifest = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "brief": "docs/briefs/weekend/brief-2c-training-data-distillation.md",
        "files": files,
        "pairs": {"total": len(items), "train": len(train), "val": len(val),
                  "trimmed_to_target": surplus,
                  "val_fraction": round(len(val) / len(items), 4)},
        "split": {"unit": "platform (make + model)", "seed": SEED,
                  "val_platforms": sorted(held), "train_platforms": len(by_platform) - len(held)},
        "by_label": {l: {"train": sum(1 for i in train if i["label"] == l),
                         "val": sum(1 for i in val if i["label"] == l)} for l in sorted(overall)},
        "by_path": dict(Counter(i["path"] for i in items)),
        "tokens": {"tokenizer": TOKENIZER_ID, "limit": MAX_TOKENS,
                   "max": max(i["tokens"] for i in items),
                   "mean": round(sum(i["tokens"] for i in items) / len(items)),
                   "dropped_over_limit": len(over)},
        "system_prompt_sha256": hashlib.sha256(next(iter(systems)).encode("utf-8")).hexdigest(),
        "synthesis_prompt_sha256": sha256(TRAIN / "synthesis_prompt.txt"),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"pairs {len(items)} (dropped over {MAX_TOKENS} tokens: {len(over)}; "
          f"trimmed to the {TARGET_PAIRS} target: {surplus}); "
          f"train {len(train)}, val {len(val)} ({len(val) / len(items):.1%}) "
          f"on {len(held)} held-out platforms of {len(by_platform)}")
    print(f"tokens per pair: max {manifest['tokens']['max']}, mean {manifest['tokens']['mean']}")
    print(f"  {'label':<28}{'train':>7}{'val':>6}")
    for l, c in manifest["by_label"].items():
        print(f"  {l:<28}{c['train']:>7}{c['val']:>6}")
    for name, meta in files.items():
        print(f"  {name}: {meta['lines']} lines, sha256 {meta['sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
