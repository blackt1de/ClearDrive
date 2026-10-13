"""Brief 2c steps 2 and 3: exclude eval overlap, then draw the stratified sample.

Reads data/train/normalized.jsonl (scripts/distill_normalize.py). From eval/ it reads only
eval_set.json, codeless_set.json and taxonomy.json, for exclusion and label names.

Step 2 drops a record when any of these holds, checked in this order:
  url      its URL names an NHTSA complaint (ODI number) used by an eval case
  tuple    same (year, make, model) as an eval case and it shares a DTC with that case
  vehicle  same (year, make, model) as any eval case or codeless profile
`vehicle` is stricter than the brief's url/tuple rule: held-out splits are by platform
(root CLAUDE.md, Research integrity), so no training pair is built for an eval vehicle.

Step 3 samples one record per distinct model input. The prompt the backend builds depends
only on (year, make, model, DTC set), so two records with the same key would give the same
training input; one is kept. Caps: per label, per source, and for unmapped records.

    python scripts/distill_sample.py     # writes data/train/exclusions.json, sample.jsonl
"""
from __future__ import annotations

import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TRAIN = REPO / "data" / "train"
NORMALIZED = TRAIN / "normalized.jsonl"
EXCLUSIONS = TRAIN / "exclusions.json"
SAMPLE = TRAIN / "sample.jsonl"
COMPOSITION = TRAIN / "sample_composition.json"
EVAL = REPO / "eval"

SEED = 42
TARGET = 5500            # decisions.md 2026-09-25, ruling 7 (brief 2c said 4,000)
# Brief 2c step 3.2 caps a label at 400 of 4,000 records (10%). The target was raised to
# 5,500, so the cap is kept at the same 10% share rather than the absolute 400.
LABEL_CAP = TARGET // 10
SOURCE_CAP_FRAC = 0.15   # of the records actually sampled
UNMAPPED_CAP_FRAC = 0.10  # of TARGET
UNMAPPED = "unmapped"

# Text cues, used only where the DTC family does not settle the label.
TEXT_CUES = {
    "vacuum_intake_leak": r"vacuum (?:leak|hose|line)|intake (?:manifold )?gasket|intake boot|\bpcv\b",
    "fuel_delivery": r"fuel pump|fuel filter|fuel pressure|pressure regulator",
    "maf_sensor": r"\bmaf\b|mass air ?flow",
    "ignition_component": r"ignition coil|coil pack|\bcoils?\b|spark plug|plug wire",
    "fuel_injector": r"injector",
    "catalytic_converter": r"catalytic|\bcat(?:alyst)? converter|\bcatalyst\b",
    "oxygen_sensor": r"\bo2 sensor|oxygen sensor|air[- /]fuel(?: ratio)? sensor|a/f sensor",
    "evap_system": r"\bevap|purge valve|vent valve|gas cap|fuel cap|charcoal canister",
    "valve_timing_air_aux": r"\bvvt|cam phaser|timing chain|camshaft actuator|oil control valve|"
                            r"turbocharger|\bturbo\b|wastegate|\bboost\b",
    "air_fuel_metering_other": r"thermostat|throttle body|map sensor|coolant temp(?:erature)? sensor",
    "ignition_system_sensor": r"crank(?:shaft)? (?:position )?sensor|cam(?:shaft)? position sensor|knock sensor",
    "emissions_control_other": r"\begr\b|secondary air",
    "idle_speed_auxiliary": r"idle air|speed sensor|alternator|oil pressure (?:sensor|switch)",
    "control_module": r"\b(?:pcm|ecm|ecu)\b|reflash|reprogram|control module",
    "transmission": r"transmission|torque converter|shift solenoid|\btcm\b|valve body",
}
TEXT_RE = {k: re.compile(v, re.IGNORECASE) for k, v in TEXT_CUES.items()}


def norm(s) -> str:
    return re.sub(r"[\s\-]", "", str(s)).upper()


def vkey(v) -> tuple:
    return (int(v["year"]), norm(v["make"]), norm(v["model"]))


def by_text(rec, labels) -> str | None:
    for text in (rec.get("resolution") or "", rec.get("symptoms") or ""):
        for label in labels:
            if TEXT_RE[label].search(text):
                return label
    return None


def label_for(rec, all_labels) -> str:
    """eval/taxonomy.json label from the primary DTC's family, then from the text."""
    if not rec["dtcs"]:
        return by_text(rec, all_labels) or UNMAPPED
    c = rec["dtcs"][0]
    if not re.fullmatch(r"P0[0-9]{3}", c):
        return by_text(rec, all_labels) or UNMAPPED
    n = int(c[1:])
    if n in (171, 172, 174, 175):
        return by_text(rec, ("vacuum_intake_leak", "fuel_delivery", "maf_sensor")) or "air_fuel_metering_other"
    if 100 <= n <= 104:
        return "maf_sensor"
    if 300 <= n <= 312:
        return by_text(rec, ("ignition_component", "fuel_injector")) or "ignition_component"
    if 200 <= n <= 299:
        return "fuel_injector"
    if 420 <= n <= 439:
        return "catalytic_converter"
    if 130 <= n <= 167 or 30 <= n <= 64:
        return "oxygen_sensor"
    if 440 <= n <= 459:
        return "evap_system"
    family = {0: "valve_timing_air_aux", 1: "air_fuel_metering_other", 3: "ignition_system_sensor",
              4: "emissions_control_other", 5: "idle_speed_auxiliary", 6: "control_module",
              7: "transmission", 8: "transmission"}.get(n // 100)
    return family or by_text(rec, all_labels) or UNMAPPED


def main() -> int:
    taxonomy = json.loads((EVAL / "taxonomy.json").read_text(encoding="utf-8"))
    all_labels = [x["label"] for x in taxonomy["labels"]]
    assert set(all_labels) == set(TEXT_CUES), "taxonomy labels changed; update TEXT_CUES"
    cases = json.loads((EVAL / "eval_set.json").read_text(encoding="utf-8"))["cases"]
    profiles = json.loads((EVAL / "codeless_set.json").read_text(encoding="utf-8"))["profiles"]

    eval_odi, eval_codes, held_vehicles = set(), defaultdict(set), set()
    for c in cases:
        url = (c.get("ground_truth") or {}).get("source_url") or ""
        if m := re.search(r"odiNumber=(\d+)", url):
            eval_odi.add(m.group(1))
        k = vkey(c["vehicle"])
        held_vehicles.add(k)
        eval_codes[k].update(d["code"].upper() for d in c["payload"]["snapshot"]["dtc_codes"])
    for p in profiles:
        held_vehicles.add(vkey(p["vehicle"]))

    records, dropped, reasons = [], [], Counter()
    with NORMALIZED.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            k = vkey(r["vehicle"])
            m = re.search(r"odiNumber=(\d+)", r.get("url") or "")
            if m and m.group(1) in eval_odi:
                reason = "url"
            elif k in eval_codes and eval_codes[k] & set(r["dtcs"]):
                reason = "tuple"
            elif k in held_vehicles:
                reason = "vehicle"
            else:
                records.append(r)
                continue
            reasons[reason] += 1
            dropped.append({"record_id": r["record_id"], "reason": reason})
    EXCLUSIONS.write_text(json.dumps({
        "rule": "url (eval ODI number) | tuple (year, make, model, shared DTC) | vehicle "
                "(year, make, model of any eval case or codeless profile)",
        "eval_cases": len(cases), "codeless_profiles": len(profiles),
        "held_out_vehicles": len(held_vehicles),
        "dropped_by_reason": dict(reasons), "dropped_total": len(dropped), "dropped": dropped,
    }, indent=1), encoding="utf-8")
    print(f"step 2: {len(dropped)} records dropped {dict(reasons)}; {len(records)} remain")

    groups = defaultdict(list)
    for r in records:
        groups[(vkey(r["vehicle"]), tuple(sorted(r["dtcs"])))].append(r)
    rng = random.Random(SEED)
    keys = sorted(groups)
    rng.shuffle(keys)
    # Keys that have a record with a stated resolution are drawn first (brief 2c step 3.2).
    keys.sort(key=lambda k: not any(r["resolution"] for r in groups[k]))

    unmapped_cap = int(TARGET * UNMAPPED_CAP_FRAC)

    def draw(source_cap):
        n_label, n_source, chosen, skipped = Counter(), Counter(), [], Counter()
        for k in keys:
            if len(chosen) >= TARGET:
                break
            cands = sorted(groups[k], key=lambda r: (not r["resolution"], n_source[r["source"]], r["record_id"]))
            blocked = None
            for r in cands:
                label = label_for(r, all_labels)
                if n_source[r["source"]] >= source_cap:
                    blocked = "source_cap"
                elif n_label[label] >= (unmapped_cap if label == UNMAPPED else LABEL_CAP):
                    blocked = "unmapped_cap" if label == UNMAPPED else "label_cap"
                else:
                    n_label[label] += 1
                    n_source[r["source"]] += 1
                    chosen.append({**r, "label": label})
                    break
            else:
                skipped[blocked] += 1
        return n_label, n_source, chosen, skipped

    # The source cap is a share of what is actually drawn, so tighten it until it holds.
    source_cap = int(TARGET * SOURCE_CAP_FRAC)
    while True:
        n_label, n_source, chosen, skipped = draw(source_cap)
        allowed = int(len(chosen) * SOURCE_CAP_FRAC)
        if max(n_source.values()) <= allowed:
            break
        source_cap = allowed

    with SAMPLE.open("w", encoding="utf-8") as f:
        for r in chosen:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n = len(chosen)
    comp = {
        "target": TARGET, "sampled": n, "distinct_inputs_available": len(keys),
        "caps": {"label": LABEL_CAP, "source": source_cap, "unmapped": unmapped_cap},
        "by_label": dict(n_label.most_common()), "by_source": dict(n_source.most_common()),
        "with_resolution": sum(1 for r in chosen if r["resolution"]),
        "no_dtc": sum(1 for r in chosen if not r["dtcs"]),
        "multi_dtc": sum(1 for r in chosen if len(r["dtcs"]) > 1),
        "keys_skipped_by_cap": dict(skipped),
    }
    COMPOSITION.write_text(json.dumps(comp, indent=2), encoding="utf-8")
    print(f"step 3: sampled {n} of target {TARGET} from {len(keys)} distinct inputs")
    print(f"  with resolution {comp['with_resolution']}, no DTC {comp['no_dtc']}, multi-DTC {comp['multi_dtc']}")
    print(f"  keys skipped by cap: {dict(skipped)}")
    print(f"  {'label':<28}{'n':>6}{'share':>8}")
    for label, c in n_label.most_common():
        print(f"  {label:<28}{c:>6}{c / n:>8.1%}")
    print(f"  {'source':<28}{'n':>6}{'share':>8}")
    for s, c in n_source.most_common():
        print(f"  {s:<28}{c:>6}{c / n:>8.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
