"""Brief 2c step 1: normalize the scraped corpus into one record per owner report.

training_data/raw/<year>_<make>_<model>/<DTC>.json holds, per (vehicle, code) file, five
scraped sources. A record is one owner-written item inside a file:

  reddit            one post found by the "<model> <code>" search
  nhtsa_complaints  one NHTSA complaint for the vehicle (the same list repeats in all 50
                    code files of a vehicle, so it is de-duplicated on the ODI number)
  repairpal         one "common problems" string for the vehicle
  carcomplaints     one problem string for the vehicle
  nhtsa_recalls     recall notices: not owner reports, so counted in and dropped

Every record becomes
  {"record_id", "source", "vehicle": {year, make, model, engine|null}, "dtcs": [...],
   "symptoms": str, "resolution": str|null, "url"}
Records with no DTC and no symptoms are dropped. training_data/raw/ is read-only.

    python scripts/distill_normalize.py            # writes data/train/normalized.jsonl
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "training_data" / "raw"
OUT_DIR = REPO / "data" / "train"
OUT = OUT_DIR / "normalized.jsonl"
COUNTS = OUT_DIR / "normalize_counts.json"

# Powertrain codes only: the eval taxonomy scopes B/C/U out (eval/taxonomy.json).
DTC_RE = re.compile(r"\bP[0-3][0-9A-F]{3}\b", re.IGNORECASE)
MAX_DTCS = 4
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")
RESOLUTION_RE = re.compile(
    r"\b(replaced|replacing|replacement of|repaired|fixed (?:it|the|my)|was fixed|solved|"
    r"resolved|turned out|ended up being|the (?:fix|problem|issue|culprit) was)\b",
    re.IGNORECASE,
)
MIN_PROBLEM_CHARS = 15  # drops scrape debris such as "Learn More"


def find_dtcs(text: str) -> list[str]:
    seen = []
    for m in DTC_RE.finditer(text or ""):
        code = m.group(0).upper()
        if code not in seen:
            seen.append(code)
    return seen[:MAX_DTCS]


def find_resolution(text: str) -> str | None:
    hits = [s.strip() for s in SENTENCE_RE.split(text or "") if RESOLUTION_RE.search(s)]
    return " ".join(hits)[:600] or None


def clean(text) -> str:
    return " ".join(str(text or "").split())


def rid(source: str, *parts) -> str:
    return f"{source}:{hashlib.sha1('|'.join(map(str, parts)).encode('utf-8')).hexdigest()[:16]}"


def main() -> int:
    if not RAW.is_dir():
        print(f"FAIL: {RAW} not found")
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    n_in, n_out, n_dropped = Counter(), Counter(), Counter()
    files = 0
    with OUT.open("w", encoding="utf-8") as out:

        def emit(source, record_id, vehicle, dtcs, symptoms, resolution, url):
            n_in[source] += 1
            if not dtcs and not symptoms:
                n_dropped[source] += 1
                return
            n_out[source] += 1
            out.write(json.dumps({
                "record_id": record_id, "source": source, "vehicle": vehicle, "dtcs": dtcs,
                "symptoms": symptoms, "resolution": resolution, "url": url,
            }, ensure_ascii=False) + "\n")

        for vdir in sorted(p for p in RAW.iterdir() if p.is_dir()):
            seen_odi, seen_posts, seen_strings, seen_recalls = set(), set(), set(), set()
            for path in sorted(vdir.glob("*.json")):
                files += 1
                doc = json.loads(path.read_text(encoding="utf-8"))
                v = doc["vehicle"]
                vehicle = {"year": int(v["year"]), "make": v["make"], "model": v["model"],
                           "engine": None}
                file_code = str(doc["code"]).upper()
                src = doc.get("sources") or {}

                reddit = src.get("reddit") or {}
                for post in reddit.get("posts") or []:
                    url = post.get("url") or ""
                    body = clean(f"{post.get('title', '')}\n{post.get('text', '')}")
                    # The search hit ties the post to this file's code; codes written in
                    # the post itself take precedence over that association.
                    dtcs = find_dtcs(body) or ([file_code] if DTC_RE.fullmatch(file_code) else [])
                    key = (url or body[:200], tuple(dtcs))
                    if key in seen_posts:
                        continue
                    seen_posts.add(key)
                    sub = clean(post.get("subreddit") or post.get("_subreddit_searched") or "unknown")
                    emit(f"reddit/r/{sub}", rid("reddit", vdir.name, url, *dtcs), vehicle,
                         dtcs, body, find_resolution(body), url or None)

                for c in (src.get("nhtsa_complaints") or {}).get("results") or []:
                    odi = c.get("odiNumber")
                    if odi in seen_odi:
                        continue
                    seen_odi.add(odi)
                    summary = clean(c.get("summary"))
                    url = ("https://api.nhtsa.gov/complaints/complaintsByVehicle?"
                           f"make={v['make']}&model={v['model']}&modelYear={v['year']}"
                           f"#odiNumber={odi}")
                    emit("nhtsa_complaints", f"nhtsa_complaints:{odi}", vehicle,
                         find_dtcs(summary), summary, find_resolution(summary), url)

                for r in (src.get("nhtsa_recalls") or {}).get("results") or []:
                    camp = r.get("NHTSACampaignNumber")
                    if camp in seen_recalls:
                        continue
                    seen_recalls.add(camp)
                    emit("nhtsa_recalls", f"nhtsa_recalls:{vdir.name}:{camp}", vehicle, [], "",
                         None, None)

                for source, block, fields in (
                    ("repairpal", src.get("repairpal") or {}, ("common_problems",)),
                    ("carcomplaints", src.get("carcomplaints") or {},
                     ("problems", "worst_problems", "engine_problems", "trim_relevant")),
                ):
                    for field in fields:
                        for item in block.get(field) or []:
                            text = clean(item if isinstance(item, str) else json.dumps(item))
                            if (source, text) in seen_strings:
                                continue
                            seen_strings.add((source, text))
                            symptoms = text if len(text) >= MIN_PROBLEM_CHARS else ""
                            emit(source, rid(source, vdir.name, text), vehicle, find_dtcs(text),
                                 symptoms, find_resolution(text), block.get("url"))

    summary = {
        "files_read": files,
        "records_in": dict(sorted(n_in.items())),
        "records_out": dict(sorted(n_out.items())),
        "dropped_no_dtc_no_symptoms": dict(sorted(n_dropped.items())),
        "total_in": sum(n_in.values()), "total_out": sum(n_out.values()),
    }
    COUNTS.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    reddit_in = sum(n for s, n in n_in.items() if s.startswith("reddit/"))
    reddit_out = sum(n for s, n in n_out.items() if s.startswith("reddit/"))
    print(f"files read: {files}")
    print(f"{'source':<28}{'in':>10}{'out':>10}")
    print(f"{'reddit (all subreddits)':<28}{reddit_in:>10}{reddit_out:>10}")
    for s in sorted(n_in):
        if not s.startswith("reddit/"):
            print(f"{s:<28}{n_in[s]:>10}{n_out[s]:>10}")
    print(f"{'TOTAL':<28}{summary['total_in']:>10}{summary['total_out']:>10}")
    print(f"subreddits: {sum(1 for s in n_in if s.startswith('reddit/'))}; per-source counts in {COUNTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
