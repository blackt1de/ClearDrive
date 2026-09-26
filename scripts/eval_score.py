#!/usr/bin/env python3
"""Score an eval run, deterministic parts only (Brief 2a, step 11).

Model arm (a run directory from eval_run.py):
  H1  labels predicted from the model's own LIKELY CAUSES text, using the same
      component table the adjudication used (COMPONENT_LABELS). Per-label
      precision/recall/F1 and macro-F1 over the taxonomy, plus top-1 accuracy
      (first label named vs the primary label). Unmapped predictions are logged.
  H4  hit/miss per codeless profile (h4_hit, pinned in codeless_set.json).
  Latency from run_meta.json: mean, p50, p95, warm-up and failed calls excluded.
  Truncation gate: refuses to score a run whose truncated share is over 5%.
Rule-based arm (--rule-based): DTC lookup only, no model. Each code maps to a label
  by code range (RULE_BASED_RANGES); manufacturer (P1xxx, P3xxx) codes stay unmapped.

H2 needs the judge and is NOT computed here. The scorer writes h2_pending.jsonl
(case_id, response text, expected specificity) for the judge step.

Run:
    .venv/bin/python scripts/eval_score.py --run-id base-qwen3-14b-2026-09-26
    .venv/bin/python scripts/eval_score.py --rule-based --run-id rulebased-2026-09-26
"""

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
EVAL = ROOT / "eval"

# Component phrase -> label. Derived from the component table that shortlisted the
# complaint narratives; the ground-truth labels themselves came from reading each
# narrative in full (eval/sources/adjudication.json), not from this table.
COMPONENT_LABELS = [
    (r"ignition coils?|coil packs?|coil-on-plug|spark plugs?|plug wires?", "ignition_component"),
    (r"fuel injectors?|injectors?", "fuel_injector"),
    (r"fuel pumps?|fuel filters?|fuel pressure regulators?|fuel pressure sensors?|fuel rails?|fuel delivery|fuel pressure", "fuel_delivery"),
    (r"mass[ -]?air[ -]?flow(?: sensor)?|\bmaf\b(?: sensor)?|air ?flow sensor|airflow meter", "maf_sensor"),
    (r"vacuum (?:leak|hoses?|lines?)|intake (?:manifold )?gaskets?|pcv (?:valve|hose)s?|intake boot|unmetered air|air leak", "vacuum_intake_leak"),
    (r"catalytic converters?|cat(?:alytic)? converters?|\bcatalysts?\b", "catalytic_converter"),
    (r"o2 sensors?|\b(?:upstream|downstream) o2\b|oxygen sensors?|air[ /-]?fuel (?:ratio )?sensors?|a/f sensors?", "oxygen_sensor"),
    (r"purge (?:valve|solenoid)s?|vent (?:valve|solenoid)s?|charcoal canister|\bevap(?:orative)?\b|gas caps?|fuel caps?|filler neck", "evap_system"),
    (r"(?:cam(?:shaft)?|crank(?:shaft)?) (?:position )?(?:\([a-z]{2,4}\) )?sensors?|\b(?:ckp|cmp) sensors?|knock sensors?", "ignition_system_sensor"),
    (r"variable valve timing|\bvvt\b|cam phasers?|timing chains?|oil control valves?|turbochargers?|\bturbo\b|wastegates?|boost (?:pressure|control|leak)|underboost|overboost", "valve_timing_air_aux"),
    (r"thermostats?|coolant temp(?:erature)? sensors?|\bmap sensors?|manifold absolute pressure(?: sensors?)?|throttle bod(?:y|ies)|throttle position sensors?|intake air temp(?:erature)? sensors?", "air_fuel_metering_other"),
    (r"\begr\b|exhaust gas recirculation|secondary air", "emissions_control_other"),
    (r"idle air control|\biac\b|vehicle speed sensors?|alternators?|charging system|oil pressure (?:sensor|switch)(?:es)?", "idle_speed_auxiliary"),
    (r"\bpcm\b|\becm\b|\becu\b|engine control module|powertrain control module|engine computer|control module software", "control_module"),
    (r"transmissions?|\btcm\b|torque converters?|valve bod(?:y|ies)|shift solenoids?|solenoid packs?", "transmission"),
]
_COMPILED = [(re.compile(rx, re.I), label) for rx, label in COMPONENT_LABELS]

# DTC lookup arm: code range -> label (inclusive hex-number ranges on the 4 digits).
# Base ranges span each SAE group to its hex end (P00FF, not P0099); narrower
# overrides follow and win. A code the table does not define still has a group,
# which is all a lookup-only reader can know about it.
RULE_BASED_RANGES = [
    ("P0000", "P00FF", "valve_timing_air_aux"),
    ("P0100", "P01FF", "air_fuel_metering_other"),
    ("P0200", "P02FF", "fuel_injector"),
    ("P0300", "P03FF", "ignition_system_sensor"),
    ("P0400", "P04FF", "emissions_control_other"),
    ("P0500", "P05FF", "idle_speed_auxiliary"),
    ("P0600", "P06FF", "control_module"),
    ("P0700", "P09FF", "transmission"),
    ("P2000", "P20FF", "emissions_control_other"),
    ("P2100", "P22FF", "air_fuel_metering_other"),
    ("P2400", "P24FF", "emissions_control_other"),
    ("P2500", "P25FF", "idle_speed_auxiliary"),
    ("P2600", "P26FF", "control_module"),
    ("P2700", "P27FF", "transmission"),
    ("P2A00", "P2AFF", "oxygen_sensor"),
    # overrides
    ("P0100", "P0104", "maf_sensor"),
    ("P0130", "P0167", "oxygen_sensor"),
    ("P0170", "P019F", "fuel_delivery"),
    ("P0230", "P0233", "fuel_delivery"),
    ("P0234", "P0260", "valve_timing_air_aux"),
    ("P0300", "P0312", "ignition_component"),
    ("P0350", "P0362", "ignition_component"),
    ("P0420", "P043F", "catalytic_converter"),
    ("P0440", "P045F", "evap_system"),
    ("P0496", "P049F", "evap_system"),
    ("P2195", "P2199", "oxygen_sensor"),
    ("P2400", "P2422", "evap_system"),
    ("P2450", "P2451", "evap_system"),
]
H4_STOPWORDS = {"AND", "THE", "OF", "SYSTEM", "EQUIPMENT", "OTHER", "UNKNOWN", "VEHICLE", "WITH", "FOR"}


def predicted_labels(text):
    """Labels in order of first mention in the text."""
    hits = []
    for rx, label in _COMPILED:
        m = rx.search(text or "")
        if m:
            hits.append((m.start(), label))
    seen, out = set(), []
    for _, label in sorted(hits):
        if label not in seen:
            seen.add(label)
            out.append(label)
    return out


def rule_based_labels(codes):
    out = []
    for code in codes:
        n = int(code[1:], 16)
        # Later, narrower ranges override earlier, wider ones (P2195-P2199 inside P2100-P2199).
        label = None
        for lo, hi, lb in RULE_BASED_RANGES:
            if code[0] == lo[0] and int(lo[1:], 16) <= n <= int(hi[1:], 16):
                label = lb
        if label and label not in out:
            out.append(label)
    return out


def prf(cases_true, cases_pred, labels):
    per = {}
    for lb in labels:
        tp = sum(lb in t and lb in p for t, p in zip(cases_true, cases_pred))
        fp = sum(lb not in t and lb in p for t, p in zip(cases_true, cases_pred))
        fn = sum(lb in t and lb not in p for t, p in zip(cases_true, cases_pred))
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        per[lb] = {"precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4),
                   "support": tp + fn, "tp": tp, "fp": fp, "fn": fn}
    macro = round(sum(v["f1"] for v in per.values()) / len(labels), 4)
    return per, macro


# The fixed null response for H4: generic, vehicle-agnostic advice. Its hit rate is
# reported next to every H4 score (pre-registered 2026-09-26, notes/decisions.md).
H4_NULL_RESPONSE = ("Your air bags and seat belts are fine. Keep the engine cooling system topped up. "
                    "Check brake lights and automatic transmission fluid. Open recalls on air bags, "
                    "seat belts or service brakes are repaired free by the dealer.")


def h4_text(resp):
    """H4 reads the KNOWN ISSUES section only: the section meant to carry vehicle facts."""
    return resp.get("known_issues") or ""


def _leaf_words(component):
    """Distinctive words: the part level of NHTSA's component path, i.e. segments after
    the first two, which are system categories ("AIR BAGS:FRONTAL:DRIVER SIDE:INFLATOR
    MODULE" -> DRIVER SIDE INFLATOR MODULE; "POWER TRAIN:AUTOMATIC TRANSMISSION" -> none,
    so that recall can only be hit by its campaign number)."""
    segments = (component or "").upper().split(":")
    return {w for seg in segments[2:] for w in re.split(r"[^A-Z]+", seg)
            if len(w) > 2 and w not in H4_STOPWORDS}


def h4_hit(text, issues):
    up = (text or "").upper()
    for issue in issues:
        if issue.get("campaign") and issue["campaign"].upper() in up:
            return True
        words = _leaf_words(issue.get("component"))
        found = {w for w in words if re.search(rf"\b{w}\b", up)}
        # Pinned rule: two distinctive words, unconditionally. A one-word component
        # ("ENGINE") can only be hit through its campaign number.
        if len(found) >= 2:
            return True
    return False


def h4_null_rate(profiles, text=H4_NULL_RESPONSE):
    """H4 hit rate a fixed response would get if it were every profile's KNOWN ISSUES."""
    hits = [h4_hit(text, p["ground_truth"]["documented_issues"]) for p in profiles]
    return round(sum(hits) / len(hits), 4) if hits else 0.0


def check_gate(meta):
    """A run with more than 5% truncated (ruling 2026-09-25) or failed (review 2026-09-26)
    calls is reported, not scored."""
    if meta["truncation"]["gate"] == "FAIL":
        sys.exit(f"TRUNCATION GATE FAILED ({meta['truncation']}); stop and report before scoring")
    if meta["failure"]["gate"] == "FAIL":
        sys.exit(f"FAILURE GATE FAILED ({meta['failure']}); stop and report before scoring")


def latency(calls):
    secs = [c["seconds"] for c in calls if not c.get("warmup") and not c.get("error") and c.get("seconds")]
    if not secs:
        return {"n": 0}
    p95 = round(statistics.quantiles(secs, n=100, method="inclusive")[94], 2) if len(secs) >= 2 else None
    return {"n": len(secs), "mean": round(statistics.mean(secs), 2), "p50": round(statistics.median(secs), 2),
            "p95": p95}


NARRATIVE = ("dont_panic", "likely_causes", "symptoms", "if_ignored", "quick_checks", "diy_fix",
             "urgency", "repair_cost", "service_recommendations", "known_issues", "owner_reports")


def narrative(resp):
    return "\n\n".join(f"{k}: {resp[k]}" for k in NARRATIVE if isinstance(resp.get(k), str) and resp[k].strip())


def score(cases, profiles, labels, responses, rule_based=False):
    """responses: case_id -> response dict (model arm). Returns (scores, h2_rows, unmapped)."""
    truth, preds, top1, unmapped, h2_rows = [], [], [], [], []
    for c in cases:
        gt = c["ground_truth"]
        codes = [d["code"] for d in c["payload"]["snapshot"]["dtc_codes"]]
        if rule_based:
            pred = rule_based_labels(codes)
            text = "\n".join(f"{code}: {_definition(code)}" for code in codes)
        else:
            resp = responses.get(c["case_id"]) or {}
            pred = predicted_labels(resp.get("likely_causes", ""))
            text = narrative(resp)
            if (resp.get("likely_causes") or "").strip() and not pred:
                unmapped.append({"case_id": c["case_id"], "likely_causes": resp["likely_causes"][:400]})
        truth.append(set(gt["fault_labels"]))
        preds.append(set(pred))
        top1.append(bool(pred) and pred[0] == gt["primary_label"])
        h2_rows.append({"case_id": c["case_id"], "response_text": text,
                        "h2_expected_specificity": c["h2_expected_specificity"]})
    per, macro = prf(truth, preds, labels)
    hits = []
    for p in profiles:
        resp = {} if rule_based else (responses.get(p["case_id"]) or {})
        hits.append({"case_id": p["case_id"], "hit": h4_hit(h4_text(resp), p["ground_truth"]["documented_issues"])})
        h2_rows.append({"case_id": p["case_id"], "response_text": narrative(resp),
                        "h2_expected_specificity": p["h2_expected_specificity"]})
    rate = round(sum(h["hit"] for h in hits) / len(hits), 4) if hits else 0.0
    return ({"h1": {"macro_f1": macro, "top1_accuracy": round(sum(top1) / len(top1), 4),
                    "per_label": per, "cases": len(cases)},
             "h4": {"hit_rate": rate, "threshold": 0.5, "null_baseline": h4_null_rate(profiles),
                    "hits": hits}}, h2_rows, unmapped)


def _definition(code):
    import dtc_definitions
    return dtc_definitions.resolve(code)["description"] or "no definition"


def _markdown(run_id, s, lat, unmapped, missing, failed=None):
    lines = [f"# Scores: {run_id}\n", f"**H1 macro-F1: {s['h1']['macro_f1']}**; top-1 accuracy "
             f"{s['h1']['top1_accuracy']} over {s['h1']['cases']} cases.\n",
             f"**H4 hit rate: {s['h4']['hit_rate']}** (threshold {s['h4']['threshold']}).\n",
             f"H4 null baseline (fixed generic response, scored the same way): {s['h4']['null_baseline']}. "
             "Read H4 against this baseline, not against the threshold alone.\n"]
    if lat:
        lines.append(f"Latency (s, warm-up and failures excluded): {lat}\n")
    lines += ["| Label | P | R | F1 | Support |", "|---|---|---|---|---|"]
    for lb, v in s["h1"]["per_label"].items():
        lines.append(f"| {lb} | {v['precision']} | {v['recall']} | {v['f1']} | {v['support']} |")
    lines.append(f"\nUnmapped LIKELY CAUSES (text present, no taxonomy label): {len(unmapped)}")
    lines.append(f"Cases with no saved response: {len(missing)} {missing[:10]}")
    lines.append(f"Failed calls: {failed}")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--rule-based", action="store_true")
    args = ap.parse_args()
    cases = json.loads((EVAL / "eval_set.json").read_text())["cases"]
    profiles = json.loads((EVAL / "codeless_set.json").read_text())["profiles"]
    labels = [lb["label"] for lb in json.loads((EVAL / "taxonomy.json").read_text())["labels"]]
    out = EVAL / "runs" / args.run_id
    responses, lat, missing = {}, None, []
    if args.rule_based:
        out.mkdir(parents=True, exist_ok=True)
    else:
        meta = json.loads((out / "run_meta.json").read_text())
        check_gate(meta)
        for item in cases + profiles:
            f = out / f"{item['case_id']}.json"
            if f.exists():
                responses[item["case_id"]] = json.loads(f.read_text())
            else:
                missing.append(item["case_id"])
        lat = latency(meta["calls"])
    s, h2_rows, unmapped = score(cases, profiles, labels, responses, rule_based=args.rule_based)
    s.update(run_id=args.run_id, arm="rule-based" if args.rule_based else "model", latency=lat,
             unmapped_predictions=unmapped, missing_responses=missing)
    (out / "scores.json").write_text(json.dumps(s, indent=1))
    failed = meta["failure"] if not args.rule_based else "n/a (no model calls)"
    (out / "scores.md").write_text(_markdown(args.run_id, s, lat, unmapped, missing, failed))
    with open(out / "h2_pending.jsonl", "w") as f:
        for row in h2_rows:
            f.write(json.dumps(row) + "\n")
    print((out / "scores.md").read_text())


if __name__ == "__main__":
    main()
