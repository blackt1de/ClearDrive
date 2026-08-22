#!/usr/bin/env python3
"""Tier-1 mechanical rubric: scores saved /interpret response JSONs.

Every check is a binary, mechanically decidable fact — no language judgment,
no model. Tier-2 (claim decomposition and source tracing) is a separate,
human-or-judge-LM instrument and is deliberately NOT here.

Run:
    venv/bin/python scripts/rubric_score.py runs/replay_pilot_2026-08-22/synthetic
    venv/bin/python scripts/rubric_score.py <dir-or-json> [--csv out.csv]

Checks (pass=1 / fail=0; blank when not applicable to that response):

  verdict_consistent      safety_level matches safety.verdict via the fixed map
  summary_present         WHAT'S HAPPENING / SUMMARY text is non-empty
  service_sentence_exact  no-codes path: SERVICE RECOMMENDATIONS is byte-exact
                          the mandated sentence (the prompt demands it verbatim)
  known_fallback_exact    retrieval empty: KNOWN ISSUES is byte-exact the
                          mandated "No verified issue history..." sentence
  no_invented_numbers     every number in the prose appears in the response's
                          own structured fields (year, rpm, coolant, mileage,
                          displacement, horsepower, mpg, code digits) — the
                          "server computes, model narrates" rule. Strict only
                          when NO retrieval was hit; with retrieval, unmatched
                          numbers go to the invented_numbers review column
                          instead (the response JSON cannot carry the block)
  no_oil_specs            no oil grade (0W-20 style) or spec code anywhere
  no_interval_claims      no "every N miles/months" style service interval
  no_unsourced_recall_talk  "recall"/"TSB" appears only if a retrieval source
                          was actually hit
  no_error                response is not a model-error fallback

Output: one row per file with per-check 0/1, a pass fraction, and a summary
line. Exit non-zero if any applicable check fails anywhere (so it can gate).
"""

import argparse
import csv
import glob
import json
import os
import re
import sys

SERVICE_SENTENCE = (
    "The correct oil specification and service interval for this engine are in "
    "the owner's manual or on the oil filler cap. We do not yet hold a verified "
    "maintenance record for this vehicle."
)
KNOWN_FALLBACK = "No verified issue history was available for this vehicle."

VERDICT_TO_LEGACY = {"ok": "SAFE", "caution": "CAUTION", "stop_driving": "STOP",
                     "insufficient_data": "UNKNOWN"}

OIL_RE = re.compile(r"\b[0-9]{1,2}W-?[0-9]{2}\b|\bVW\s?50[0-9]\s?0[0-9]\b|\bACEA\b|\bILSAC\b|\bdexos\b",
                    re.IGNORECASE)
INTERVAL_RE = re.compile(r"every\s+[\d,\.]+\s*(k\b|miles|mi\b|km|months)", re.IGNORECASE)
NUM_RE = re.compile(r"\d[\d,]*\.?\d*")
RETRIEVAL_SOURCE_NAMES = {"NHTSA Complaints Database", "NHTSA Recalls Database",
                          "ClearDrive Known Issues KB"}

PROSE_FIELDS = ("dont_panic", "likely_causes", "symptoms", "if_ignored", "quick_checks",
                "diy_fix", "urgency", "service_recommendations", "known_issues",
                "owner_reports")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def allowed_numbers(d: dict) -> set:
    """Number strings the model may legitimately restate, from structured fields."""
    out = set()

    def add(v):
        if v is None or v == "":
            return
        t = str(v)
        for m in NUM_RE.findall(t):
            c = m.replace(",", "").rstrip(".")
            out.add(c)
            if "." in c:
                out.add(c.split(".")[0])
            # 118400 is often written 118,400 — both normalise to the same
            # string here; also allow the 'thousands' shorthand.
            if c.isdigit() and len(c) > 3:
                out.add(str(int(c) // 1000))

    for k in ("vehicle", "engine", "rpm", "speed", "coolant_temp", "mileage",
              "horsepower", "mpg_city", "mpg_highway", "mpg_combined",
              "tank_capacity", "transmission", "drive", "trim"):
        add(d.get(k))
    for c in d.get("codes") or []:
        add(re.sub(r"[A-Z]", "", str(c)))
    for cd in d.get("code_definitions") or []:
        add(re.sub(r"[A-Z]", "", str(cd.get("code", ""))))
        add(cd.get("description"))
    for f in d.get("differential") or []:
        for e in f.get("evidence") or []:
            add(e.get("restatement"))
    for r in (d.get("safety") or {}).get("reasons") or []:
        add(r.get("statement"))
        for e in r.get("evidence") or []:
            add(e.get("restatement"))
    for lim in d.get("capability_limitations") or []:
        add(lim)
    # Small counts (one/two-digit) appear naturally in prose ("all four wheels",
    # "3-4 sentences", cylinder counts); numbers of 1-2 digits are not the
    # fabrication class this check exists for (costs, intervals, years, temps).
    out.update(str(i) for i in range(0, 100))
    return out


def score_one(path: str) -> dict:
    d = json.load(open(path))
    row = {"file": os.path.basename(path)}

    err = str(d.get("dont_panic", "")).startswith("ERROR:")
    row["no_error"] = 0 if err else 1

    v = (d.get("safety") or {}).get("verdict")
    row["verdict_consistent"] = int(VERDICT_TO_LEGACY.get(v) == d.get("safety_level")) if v else ""

    row["summary_present"] = int(bool(norm(d.get("dont_panic"))) and not err)

    no_codes = not (d.get("codes") or [])
    if no_codes and not err:
        row["service_sentence_exact"] = int(norm(d.get("service_recommendations")) == norm(SERVICE_SENTENCE))
    else:
        row["service_sentence_exact"] = ""

    sources_hit = RETRIEVAL_SOURCE_NAMES & set(d.get("data_sources") or [])
    if not sources_hit and not err:
        row["known_fallback_exact"] = int(norm(d.get("known_issues")) == norm(KNOWN_FALLBACK))
    else:
        row["known_fallback_exact"] = ""

    prose = " ".join(str(d.get(f) or "") for f in PROSE_FIELDS)
    allowed = allowed_numbers(d)
    unmatched = sorted({m.replace(",", "").rstrip(".") for m in NUM_RE.findall(prose)} - allowed)
    # The response JSON does not carry the retrieved block, so when retrieval
    # was hit a number may be a legitimate restatement of retrieved text
    # (verified 2026-08-22: all Land Cruiser "invented" years appear verbatim
    # in NHTSA recall summaries). Strict only when nothing was retrieved;
    # otherwise unmatched numbers are a REVIEW QUEUE, not a failure.
    if sources_hit:
        row["no_invented_numbers"] = ""
    else:
        row["no_invented_numbers"] = int(not unmatched)
    row["invented_numbers"] = ";".join(unmatched[:8])

    row["no_oil_specs"] = int(not OIL_RE.search(prose))
    row["no_interval_claims"] = int(not INTERVAL_RE.search(prose))

    recall_talk = re.search(r"\brecall|technical service bulletin|\bTSB\b", prose, re.IGNORECASE)
    row["no_unsourced_recall_talk"] = int(not (recall_talk and not sources_hit))

    checks = [k for k in ("no_error", "verdict_consistent", "summary_present",
                          "service_sentence_exact", "known_fallback_exact",
                          "no_invented_numbers", "no_oil_specs", "no_interval_claims",
                          "no_unsourced_recall_talk") if row[k] != ""]
    row["passed"] = sum(row[k] for k in checks)
    row["applicable"] = len(checks)
    row["pass_fraction"] = round(row["passed"] / len(checks), 3) if checks else ""
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="directory of response JSONs, or one file")
    ap.add_argument("--csv", default=None, help="write per-file scores here")
    args = ap.parse_args()

    files = ([args.target] if os.path.isfile(args.target)
             else sorted(glob.glob(os.path.join(args.target, "*.json"))))
    files = [f for f in files if not f.endswith("summary.json")]
    if not files:
        print("no response JSONs found", file=sys.stderr)
        return 2

    rows = [score_one(f) for f in files]
    cols = list(rows[0])
    width = max(len(r["file"]) for r in rows) + 2
    print(f"{'file':<{width}} " + " ".join(f"{c:>22}" for c in cols if c not in ("file", "invented_numbers")))
    for r in rows:
        print(f"{r['file']:<{width}} " + " ".join(f"{str(r[c]):>22}" for c in cols
                                                  if c not in ("file", "invented_numbers"))
              + (f"   invented: {r['invented_numbers']}" if r["invented_numbers"] else ""))

    total = sum(r["passed"] for r in rows)
    applicable = sum(r["applicable"] for r in rows)
    print(f"\n{len(rows)} responses · {total}/{applicable} checks passed "
          f"({100 * total / applicable:.1f}%)")

    if args.csv:
        with open(args.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader(); w.writerows(rows)
        print(f"CSV: {args.csv}")

    return 0 if total == applicable else 1


if __name__ == "__main__":
    sys.exit(main())
