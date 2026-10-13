"""Brief 2c step 6: deterministic filter over the synthesized targets.

A target is dropped, never repaired. Checks run in this order and the first failure is the
recorded reason:

  no_target   no raw output, a refusal, or a response cut off at max_tokens
  schema      does not match the backend's output format (see check_schema)
  grounding   states a recall number, a bulletin number or a known-issue sentence that
              does not string-match the record's context block (see check_grounding)
  length      under 40 or over 500 words
  duplicate   exact duplicate of, or more than 0.9 token-set Jaccard with, a kept target

The context block is the part of the built prompt that carries facts about the vehicle:
everything the backend placed between its "[VEHICLE INFO]" and "[SAFETY VERDICT" markers
(vehicle, code definitions, measurements, computed diagnosis, retrieved NHTSA material and
any known_issues.json entry). The clean-scan prompt has no such markers, so its context is
the text before "Respond in this EXACT format".

Run with the backend's dependencies (.venv-distill); it imports main.parse_guidance.
    python scripts/distill_filter.py      # writes data/train/filtered.jsonl, filter_report.json
"""
from __future__ import annotations

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
PROMPTS = TRAIN / "prompts.jsonl"
RAW_DIR = TRAIN / "raw_targets"
FILTERED = TRAIN / "filtered.jsonl"
REPORT = TRAIN / "filter_report.json"

MIN_WORDS, MAX_WORDS = 40, 500
JACCARD_MAX = 0.9
SENTENCE_OVERLAP_MIN = 0.5   # share of a known-issue sentence's content words found in context

CODED_HEADERS = [
    ("SAFETY LEVEL", "safety_level"), ("WHAT'S HAPPENING", "dont_panic"),
    ("LIKELY CAUSES", "likely_causes"), ("WHAT YOU MIGHT NOTICE", "symptoms"),
    ("IF YOU IGNORE THIS", "if_ignored"), ("QUICK CHECKS", "quick_checks"),
    ("DIY FIX", "diy_fix"), ("WHEN TO SEE A MECHANIC", "urgency"),
    ("ESTIMATED REPAIR COST", "repair_cost"),
    ("SERVICE RECOMMENDATIONS", "service_recommendations"),
    ("KNOWN ISSUES FOR THIS ENGINE", "known_issues"), ("OTHER OWNERS REPORT", "owner_reports"),
]
CLEAN_HEADERS = ["SUMMARY", "SERVICE RECOMMENDATIONS", "KNOWN ISSUES"]
NO_HISTORY = "No verified issue history was available for this vehicle."

RECALL_RE = re.compile(r"\b\d{2}[VETC]\d{3,6}\b")
BULLETIN_RE = re.compile(
    r"\b(?:TSB|technical service bulletin|service bulletin|bulletin)\s*(?:number|no\.?|#)?\s*[:#]?\s*"
    r"((?=[A-Z0-9-]*\d)[A-Z0-9][A-Z0-9-]{2,})", re.IGNORECASE)
NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])\d+(?:,\d{3})*(?:\.\d+)?(?![A-Za-z])")
WORD_RE = re.compile(r"[a-z][a-z'-]{3,}")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")
STOPWORDS = set("""
that this these those with from have has been were was will would could should about there their
they them than then when what which while where also into onto over under more most some such
only very your yours here does doing done being because before after other others each both
any none not for and the are but its may can per via one two three four five
vehicle vehicles issue issues known engine
""".split())


def in_context(word: str, low_context: str) -> bool:
    """Case-insensitive string match of the word, or of the word without a common ending."""
    if word in low_context:
        return True
    stem = re.sub(r"(?:ing|ed|es|s|ly)$", "", word)
    return len(stem) >= 4 and stem in low_context


def raw_path(record_id: str) -> Path:
    return RAW_DIR / (re.sub(r"[^A-Za-z0-9_-]", "_", record_id) + ".json")


def context_of(row: dict) -> str:
    user = row["user"]
    if row["path"] == "coded":
        return user[user.index("[VEHICLE INFO]"):user.index("[SAFETY VERDICT")]
    return user[:user.index("Respond in this EXACT format")]


def split_exact(target: str, headers: list[str]) -> dict | None:
    """Section text keyed by header; None unless every header starts a line exactly once, in order."""
    lines = target.strip().split("\n")
    found, sections, current = [], {}, None
    for line in lines:
        hit = max((h for h in headers if line.strip().startswith(h + ":")), key=len, default=None)
        if hit:
            found.append(hit)
            current = hit
            sections[current] = [line.strip()[len(hit) + 1:].strip()]
        elif current is not None:
            sections[current].append(line.strip())
        elif line.strip():
            return None            # text before the first header
    if found != headers:
        return None
    return {h: "\n".join(x for x in body if x) for h, body in sections.items()}


def check_schema(row: dict, target: str, parse_guidance) -> str | None:
    if re.search(r"[*#]|__", target):
        return "markdown characters"
    if row["path"] == "coded":
        sections = split_exact(target, [h for h, _ in CODED_HEADERS])
        if sections is None:
            return "the 12 headers are not each present once, in order, with no preamble"
        if sections["SAFETY LEVEL"] != row["safety_label"]:
            return f"SAFETY LEVEL is {sections['SAFETY LEVEL']!r}, computed {row['safety_label']!r}"
        parsed = parse_guidance(target)
        for header, key in CODED_HEADERS[1:]:
            if not sections[header]:
                return f"empty section {header}"
            if parsed[key] != sections[header]:
                return f"backend parser reads {header} differently (stray header inside a section)"
        return None
    sections = split_exact(target, CLEAN_HEADERS)
    if sections is None:
        return "the 3 clean-scan headers are not each present once, in order, with no preamble"
    # main.interpret's clean-scan parser switches section on any line that starts with
    # SUMMARY / SERVICE / KNOWN and discards that line, so a header must stand alone.
    lines = [l.strip() for l in target.strip().split("\n") if l.strip()]
    switches = [l for l in lines if l.upper().startswith(("SUMMARY", "SERVICE", "KNOWN"))]
    if switches != [h + ":" for h in CLEAN_HEADERS]:
        return "a clean-scan header line carries text, or a body line starts like a header"
    if not all(sections[h] for h in CLEAN_HEADERS):
        return "empty clean-scan section"
    return None


def check_grounding(row: dict, target: str) -> str | None:
    context = context_of(row)
    low = context.lower()
    for m in RECALL_RE.finditer(target):
        if m.group(0).lower() not in low:
            return f"recall number {m.group(0)} not in context"
    for m in BULLETIN_RE.finditer(target):
        if m.group(1).lower() not in low:
            return f"bulletin number {m.group(1)} not in context"
    headers = [h for h, _ in CODED_HEADERS] if row["path"] == "coded" else CLEAN_HEADERS
    known_header = "KNOWN ISSUES FOR THIS ENGINE" if row["path"] == "coded" else "KNOWN ISSUES"
    known = split_exact(target, headers)[known_header]
    context_numbers = set(NUMBER_RE.findall(context))
    for sentence in (s.strip() for s in SENTENCE_RE.split(known)):
        if not sentence or sentence == NO_HISTORY:
            continue
        for number in NUMBER_RE.findall(sentence):
            if number not in context_numbers:
                return f"known-issue sentence states {number}, not in context: {sentence}"
        words = [w for w in WORD_RE.findall(sentence.lower()) if w not in STOPWORDS]
        if words:
            share = sum(1 for w in words if in_context(w, low)) / len(words)
            if share < SENTENCE_OVERLAP_MIN:
                return f"known-issue sentence not found in context ({share:.0%} of its words): {sentence}"
    return None


def main() -> int:
    with contextlib.redirect_stdout(io.StringIO()):
        from main import parse_guidance

    prompts = Path(sys.argv[1]) if len(sys.argv) > 1 else PROMPTS   # optional pilot file
    rows = [json.loads(line) for line in prompts.open(encoding="utf-8")]
    drops, examples, kept = Counter(), {"schema": [], "grounding": []}, []
    for row in rows:
        path = raw_path(row["record_id"])
        raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        if raw is None or raw.get("stop_reason") != "end_turn" or not raw.get("target", "").strip():
            drops["no_target"] += 1
            continue
        target = raw["target"].strip()
        if reason := check_schema(row, target, parse_guidance):
            drops["schema"] += 1
            examples["schema"].append({"record_id": row["record_id"], "reason": reason})
            continue
        if reason := check_grounding(row, target):
            drops["grounding"] += 1
            examples["grounding"].append({"record_id": row["record_id"], "invented": reason})
            continue
        n_words = len(target.split())
        if not MIN_WORDS <= n_words <= MAX_WORDS:
            drops["length_under_40" if n_words < MIN_WORDS else "length_over_500"] += 1
            continue
        kept.append({**row, "target": target, "words": n_words})

    unique, token_sets, exact = [], [], set()
    for item in kept:
        tokens = frozenset(re.findall(r"[a-z0-9']+", item["target"].lower()))
        if item["target"] in exact:
            drops["duplicate_exact"] += 1
            continue
        if any(len(tokens & other) / len(tokens | other) > JACCARD_MAX for other in token_sets):
            drops["duplicate_jaccard"] += 1
            continue
        exact.add(item["target"])
        token_sets.append(tokens)
        unique.append(item)

    with FILTERED.open("w", encoding="utf-8") as f:
        for item in unique:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    report = {"prompts": len(rows), "kept": len(unique), "dropped": dict(drops),
              "dropped_total": sum(drops.values()),
              "words": {"min": min((i["words"] for i in unique), default=0),
                        "max": max((i["words"] for i in unique), default=0),
                        "mean": round(sum(i["words"] for i in unique) / max(1, len(unique)), 1)},
              "schema_examples": examples["schema"][:20],
              "invented_facts": examples["grounding"]}
    REPORT.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"prompts {len(rows)}; kept {len(unique)}; dropped {sum(drops.values())}")
    for reason, n in drops.most_common():
        print(f"  {reason:<22}{n:>6}")
    print(f"words per kept target: {report['words']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
