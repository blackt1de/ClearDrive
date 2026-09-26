#!/usr/bin/env python3
"""Build the frozen eval set (Brief 2a, steps 3-5) from committed sources.

Inputs (all committed, so the build is reproducible without the network):
  eval/sources/adjudication.json   NHTSA complaints read and ruled on, one by one
  eval/sources/recalls.json        NHTSA recalls per vehicle (written by --fetch)
  eval/taxonomy.json               label space

Outputs: eval/eval_set.json, eval/codeless_set.json.

Rulings that shape this file (notes/decisions.md, 2026-09-25/26):
  - Reconstructed cases carry the vehicle and the stated DTCs only. Every
    measurement is null and the capability profile says live data was not
    captured; nothing is constructed from the ground-truth label.
  - P codes only; OBD era by model year (pre-CAN < 2008 <= CAN); OBDonUDS is
    not represented because no sourced vehicle list exists.
  - Synthetic cases are built from diagnostics.py rules, and each one is
    checked against the real rule engine before it is written.

Run:
    .venv/bin/python scripts/eval_build.py --fetch   # refresh eval/sources/recalls.json
    .venv/bin/python scripts/eval_build.py           # write the two set files
"""

import argparse
import asyncio
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import diagnostics  # noqa: E402
from schemas import OBDSnapshot  # noqa: E402

EVAL = ROOT / "eval"
CREATED = "2026-09-26"
SNAPSHOT_TIME = "2026-09-26T00:00:00"
TARGET_TOTAL = 102          # >= 100 cases (2a acceptance 3)
MIN_PER_LABEL = 5           # 2a step 4.1
MAX_SYNTHETIC_SHARE = 0.40  # 2a step 4.3

# Recall components that count as vehicle-specific evidence for a label (H2).
# Only labels with an unambiguous NHTSA component group are mapped.
LABEL_RECALL_COMPONENTS = {
    "fuel_delivery": "FUEL SYSTEM",
    "fuel_injector": "FUEL SYSTEM",
    "evap_system": "FUEL SYSTEM",
    "transmission": "POWER TRAIN",
}

# Drawn deterministically from NHTSA's own model names in the 2026-09-25 sweep
# (sha256-seeded, per make and era), excluding the replay-pilot and fixture cars.
SYNTHETIC_VEHICLES = [
    (2002, "Ford", "MUSTANG"), (2014, "Ford", "F-150 SUPERCAB"), (2010, "Ford", "F-250 SUPERCAB"),
    (2003, "Chevrolet", "CAVALIER"), (2013, "Chevrolet", "MALIBU ECO EASSIST"), (2009, "Chevrolet", "HHR"),
    (2002, "Toyota", "AVALON"), (2012, "Toyota", "FJ CRUISER"), (2009, "Toyota", "YARIS"),
    (2003, "Honda", "PILOT"), (2022, "Honda", "ACCORD"), (2008, "Honda", "RIDGELINE"),
    (2005, "Nissan", "TITAN"), (2019, "Nissan", "ALTIMA"), (2017, "Nissan", "MAXIMA"),
    (2003, "Jeep", "LAREDO"), (2022, "Jeep", "WRANGLER"), (2021, "Jeep", "WRANGLER UNLIMITED"),
    (2022, "Ram", "3500"), (2011, "Ram", "1500 CREW"), (2003, "GMC", "YUKON"),
    (2018, "GMC", "YUKON XL 1500"), (2021, "GMC", "SIERRA 3500"), (2007, "Hyundai", "TUCSON"),
    (2022, "Hyundai", "TUCSON"), (2017, "Hyundai", "SONATA"), (2004, "Kia", "AMANTI"),
    (2022, "Kia", "K5"), (2010, "Kia", "SPORTAGE"), (2007, "Subaru", "OUTBACK"),
    (2019, "Subaru", "FORESTER"), (2020, "Subaru", "LEGACY"), (2002, "Volkswagen", "GOLF/GTI"),
    (2009, "Volkswagen", "ROUTAN"), (2018, "Volkswagen", "GOLF GTI"), (2002, "Audi", "S4"),
    (2015, "Audi", "A8"), (2011, "Audi", "Q7"), (2001, "Volvo", "S60"),
    (2016, "Volvo", "XC90 T6"), (2016, "Volvo", "S60I"),
]
CODELESS_VEHICLES = [
    (2001, "Ford", "F-350"), (2014, "Ford", "F-150 SUPER CREW"), (2015, "Ford", "F-250 SUPER CREW"),
    (2001, "Chevrolet", "MALIBU"), (2010, "Chevrolet", "EXPRESS 2500 12 PASSENGER"), (2014, "Chevrolet", "SS"),
    (2005, "Toyota", "CAMRY"), (2011, "Toyota", "TUNDRA"), (2021, "Toyota", "TUNDRA"),
    (2003, "Honda", "INSIGHT"), (2018, "Honda", "PILOT"), (2021, "Honda", "RIDGELINE"),
    (2007, "Nissan", "XTERRA"), (2015, "Nissan", "MURANO"), (2019, "Nissan", "TITAN XD"),
    (2002, "Jeep", "LAREDO"), (2011, "Jeep", "GRAND CHEROKEE"), (2022, "Jeep", "WRANGLER UNLIMITED 392"),
    (2019, "Ram", "2500"), (2018, "Ram", "1500"), (2004, "GMC", "ENVOY XL"),
    (2018, "GMC", "TERRAIN"), (2011, "GMC", "SIERRA 2500"), (2005, "Hyundai", "ELANTRA"),
    (2018, "Hyundai", "SONATA"), (2012, "Hyundai", "SONATA"), (2007, "Kia", "RIO"),
    (2019, "Kia", "SORENTO"), (2020, "Kia", "RIO"), (2003, "Subaru", "IMPREZA"),
    (2018, "Subaru", "CROSSTREK"), (2008, "Subaru", "IMPREZA"), (2006, "Volkswagen", "NEW BEETLE"),
    (2012, "Volkswagen", "JETTA"), (2015, "Volkswagen", "GOLF GTI"), (2002, "Audi", "A6"),
    (2014, "Audi", "A6"), (2011, "Audi", "A5 COUPE"), (2003, "Volvo", "S60"),
    (2008, "Volvo", "XC90"), (2021, "Volvo", "XC60 T8 POLESTAR ENGINEERED"),
]

# A warm, idling, fault-free engine. Synthetic and codeless payloads start here;
# every value is invented, which is what "synthetic" means (fixtures.py does the same).
_FULL_CAPABILITY = {"protocol": "ISO 15765-4 (CAN)", "freeze_frame_available": True,
                    "mode06_available": True, "pending_codes_available": True,
                    "permanent_codes_available": True, "fuel_trim_available": True}
_NEUTRAL = {"rpm": 720.0, "speed_mph": 0.0, "coolant_temp_f": 195.0, "engine_load_pct": 22.0,
            "intake_air_temp_f": 82.0, "control_module_voltage": 14.1,
            "fuel_trims": [{"condition": "idle", "stft_bank1": 1.0, "ltft_bank1": 2.0,
                            "stft_bank2": 0.5, "ltft_bank2": 1.5}]}


def _ff(code, rpm=2400.0, load=45.0, coolant=195.0):
    return {"dtc": code, "rpm": rpm, "engine_load_pct": load, "coolant_temp_f": coolant, "speed_mph": 38.0}


def _trims(idle, loaded=None):
    out = [{"condition": "idle", "stft_bank1": idle[0], "ltft_bank1": idle[1],
            **({"stft_bank2": idle[2], "ltft_bank2": idle[3]} if len(idle) == 4 else {})}]
    if loaded:
        out.append({"condition": "loaded", "stft_bank1": loaded[0], "ltft_bank1": loaded[1],
                    **({"stft_bank2": loaded[2], "ltft_bank2": loaded[3]} if len(loaded) == 4 else {})})
    return out


def _t(id_, primary, codes, expect, labels=None, snapshot=None, rule=None):
    return {"id": id_, "primary": primary, "fault_labels": labels or [primary], "codes": codes,
            "expect": expect, "snapshot": snapshot or {}, "rule": rule or "rule_unmatched_codes"}


# expect: ("finding", <substring of the intended rule conclusion>) or ("no_rule", <code>).
SYNTHETIC_TEMPLATES = [
    _t("vacuum_leak_idle_heavy", "vacuum_intake_leak", ["P0171"],
       ("finding", "Air is entering the engine after the mass airflow sensor"),
       snapshot={"fuel_trims": _trims((5.0, 13.0), (2.0, 2.0))}, rule="rule_fuel_trim_triage"),
    _t("vacuum_leak_idle_severe", "vacuum_intake_leak", ["P0171"],
       ("finding", "Air is entering the engine after the mass airflow sensor"),
       snapshot={"fuel_trims": _trims((6.0, 14.0), (3.0, 4.0))}, rule="rule_fuel_trim_triage"),
    _t("lean_all_loads", "fuel_delivery", ["P0171"],
       ("finding", "running lean across the whole load range"), labels=["fuel_delivery", "maf_sensor"],
       snapshot={"fuel_trims": _trims((4.0, 10.0), (5.0, 12.0))}, rule="rule_fuel_trim_triage"),
    _t("lean_one_bank_worse_loaded", "fuel_delivery", ["P0171"],
       ("finding", "runs leaner under load than at idle"),
       snapshot={"fuel_trims": _trims((5.0, 10.0, 1.0, 1.0), (6.0, 14.0, 1.0, 1.0))},
       rule="rule_fuel_trim_triage"),
    _t("maf_low_with_lean", "maf_sensor", ["P0102", "P0171"],
       ("finding", "running lean across the whole load range"), labels=["maf_sensor", "fuel_delivery"],
       snapshot={"fuel_trims": _trims((4.0, 11.0), (5.0, 12.0))}, rule="rule_fuel_trim_triage"),
    _t("maf_range_performance", "maf_sensor", ["P0101"], ("no_rule", "P0101")),
    _t("maf_circuit_low", "maf_sensor", ["P0102"], ("no_rule", "P0102")),
    _t("single_cylinder_misfire", "ignition_component", ["P0302"],
       ("finding", "confined to one cylinder"), labels=["ignition_component", "fuel_injector"],
       snapshot={"freeze_frames": [_ff("P0302")]}, rule="rule_misfire_triage"),
    _t("coil_circuit_misfire", "ignition_component", ["P0304", "P0351"],
       ("finding", "confined to one cylinder"),
       snapshot={"freeze_frames": [_ff("P0304")]}, rule="rule_misfire_triage"),
    _t("injector_circuit_misfire", "fuel_injector", ["P0202", "P0302"],
       ("finding", "confined to one cylinder"),
       snapshot={"freeze_frames": [_ff("P0302")]}, rule="rule_misfire_triage"),
    _t("injector_circuit_only", "fuel_injector", ["P0202"], ("no_rule", "P0202")),
    _t("catalyst_well_past_limit", "catalytic_converter", ["P0420"],
       ("finding", "well past its limit"),
       snapshot={"mode06": [{"mid": "21", "tid": "80", "name": "Catalyst monitor bank 1",
                             "value": 0.9, "max_limit": 0.5, "passed": False}]},
       rule="rule_catalyst_assessment"),
    _t("o2_heater_bank1", "oxygen_sensor", ["P0135"], ("finding", "reporting an electrical fault"),
       rule="rule_oxygen_sensor"),
    _t("o2_heater_bank2", "oxygen_sensor", ["P0155"], ("finding", "reporting an electrical fault"),
       rule="rule_oxygen_sensor"),
    _t("o2_slow_response", "oxygen_sensor", ["P0133"], ("finding", "responding more slowly"),
       rule="rule_oxygen_sensor"),
    _t("evap_large_leak", "evap_system", ["P0455"], ("finding", "classified as large"), rule="rule_evap"),
    _t("evap_very_small_leak", "evap_system", ["P0456"], ("finding", "classified as very small"),
       rule="rule_evap"),
    _t("thermostat_below_regulating", "air_fuel_metering_other", ["P0128"], ("no_rule", "P0128"),
       snapshot={"coolant_temp_f": 158.0}),
    _t("iat_circuit_high", "air_fuel_metering_other", ["P0113"], ("no_rule", "P0113")),
    _t("cam_timing_over_advanced", "valve_timing_air_aux", ["P0011"], ("no_rule", "P0011")),
    _t("crank_cam_correlation", "valve_timing_air_aux", ["P0016"], ("no_rule", "P0016")),
    _t("crank_sensor_circuit", "ignition_system_sensor", ["P0335"], ("no_rule", "P0335")),
    _t("cam_sensor_circuit", "ignition_system_sensor", ["P0340"], ("no_rule", "P0340")),
    _t("egr_flow_insufficient", "emissions_control_other", ["P0401"], ("no_rule", "P0401")),
    _t("secondary_air_injection", "emissions_control_other", ["P0410"], ("no_rule", "P0410")),
    _t("idle_air_control", "idle_speed_auxiliary", ["P0505"], ("no_rule", "P0505")),
    _t("system_voltage_low", "idle_speed_auxiliary", ["P0562"], ("no_rule", "P0562"),
       snapshot={"control_module_voltage": 11.6}),
    _t("pcm_processor", "control_module", ["P0606"], ("no_rule", "P0606")),
    _t("pcm_checksum", "control_module", ["P0601"], ("no_rule", "P0601")),
    _t("tcc_stuck_off", "transmission", ["P0741"], ("no_rule", "P0741")),
    _t("input_speed_sensor", "transmission", ["P0715"], ("no_rule", "P0715")),
]


def obd_era(year: int) -> str:
    return "pre-CAN" if year < 2008 else "CAN"


def _vehicle(year, make, model):
    """Top-level case vehicle, plus the vehicle dict the backend consumes. Unknown facts are null."""
    top = {"year": year, "make": make, "model": model, "full_name": f"{year} {make} {model}",
           "engine": None, "obd_era": obd_era(year)}
    backend = {"year": str(year), "make": make, "model": model, "full_name": top["full_name"],
               "engine": None, "displacement": None, "cylinders": None, "transmission": None,
               "drive": None, "fuel_type": None, "turbocharged": None, "supercharged": None,
               "horsepower": None}
    return top, backend


def _snapshot(**fields) -> dict:
    snap = OBDSnapshot(**fields).model_dump(mode="json")
    snap["timestamp"] = SNAPSHOT_TIME
    return snap


def _codes(codes):
    return [{"code": c, "description": ""} for c in codes]


def _recall_issue(r):
    return f"{r.get('Component', '').strip()}: {' '.join((r.get('Summary') or '').split())}"


def _specificity(top, label, recalls):
    out = [f"{top['year']} {top['make']} {top['model']}"]
    component = LABEL_RECALL_COMPONENTS.get(label)
    for r in recalls:
        if component and component in (r.get("Component") or "").upper():
            out.append(f"NHTSA recall {r['NHTSACampaignNumber']} ({r.get('Component', '').strip()})")
    return out


def reconstructed_case(case_id, row, recalls):
    top, backend = _vehicle(row["year"], row["make"], row["model"])
    snap = _snapshot(dtc_codes=_codes(row["codes"]), capability={"limitations": [
        "Reconstructed from an NHTSA complaint narrative: only the stated trouble codes are "
        "known. No live data, freeze frame, fuel trims or Mode 06 were captured."]})
    return {
        "case_id": case_id, "case_type": "reconstructed", "vehicle": top,
        "payload": {"vehicle": backend, "trim": "", "snapshot": snap},
        "ground_truth": {"fault_labels": row["fault_labels"], "primary_label": row["primary_label"],
                         "confirmed_repair": row["repair_quote"], "source_url": row["source_url"],
                         "source_type": "nhtsa_complaint"},
        "h2_expected_specificity": _specificity(top, row["primary_label"], recalls),
        "provenance": {"created": CREATED, "created_by": "brief-2a",
                       "notes": f"NHTSA ODI {row['odi_number']}; DTCs as stated in the narrative; "
                                f"all measurements null by ruling. {row.get('note', '')}".strip()},
    }


def synthetic_case(case_id, template, vehicle, recalls):
    top, backend = _vehicle(*vehicle)
    fields = {**copy.deepcopy(_NEUTRAL), **copy.deepcopy(template["snapshot"])}
    snap = _snapshot(dtc_codes=_codes(template["codes"]), capability=_FULL_CAPABILITY, **fields)
    return {
        "case_id": case_id, "case_type": "synthetic", "vehicle": top,
        "payload": {"vehicle": backend, "trim": "", "snapshot": snap},
        "ground_truth": {"fault_labels": template["fault_labels"], "primary_label": template["primary"],
                         "confirmed_repair": f"synthetic: {template['id']}",
                         "source_url": f"diagnostics.py:{template['rule']}",
                         "source_type": f"synthetic_from:{template['primary']}"},
        "h2_expected_specificity": _specificity(top, template["primary"], recalls),
        "provenance": {"created": CREATED, "created_by": "brief-2a",
                       "notes": f"Synthetic template '{template['id']}': live data invented to trip "
                                f"{template['rule']}; checked against the rule engine at build time."},
    }


def check_synthetic(case, template):
    """Assert the real rule engine reaches the template's intended outcome on this payload."""
    snap = OBDSnapshot(**case["payload"]["snapshot"])
    result = diagnostics.analyze(snap, case["payload"]["vehicle"])
    kind, value = template["expect"]
    if kind == "finding":
        assert any(value in f.conclusion for f in result.findings), \
            f"{case['case_id']} ({template['id']}): no finding containing {value!r}"
    else:
        assert any(a.rule_id == "no_rule_for_code" and value in a.reason for a in result.abstentions), \
            f"{case['case_id']} ({template['id']}): {value} was not reported as uncovered"


def allocate_synthetic(recon_counts, labels, total_synthetic):
    """Top every label up to MIN_PER_LABEL first, then spread the rest to the thinnest labels."""
    plan = {label: 0 for label in labels}
    left = total_synthetic
    for label in labels:
        need = max(0, MIN_PER_LABEL - recon_counts.get(label, 0))
        take = min(need, left)
        plan[label] += take
        left -= take
    while left > 0:
        label = min(labels, key=lambda lb: (recon_counts.get(lb, 0) + plan[lb], labels.index(lb)))
        plan[label] += 1
        left -= 1
    return plan


def codeless_profile(case_id, vehicle, recalls):
    if not recalls:
        return None
    top, backend = _vehicle(*vehicle)
    snap = _snapshot(capability=_FULL_CAPABILITY, **copy.deepcopy(_NEUTRAL))
    issues = [{"issue": _recall_issue(r), "campaign": r["NHTSACampaignNumber"],
               "component": (r.get("Component") or "").strip(),
               "source_url": "https://api.nhtsa.gov/recalls/recallsByVehicle?"
                             f"make={backend['make']}&model={backend['model']}&modelYear={top['year']}"
                             f"#campaign={r['NHTSACampaignNumber']}",
               "source_type": "nhtsa_recall"} for r in recalls]
    return {
        "case_id": case_id, "case_type": "codeless", "vehicle": top,
        "payload": {"vehicle": backend, "trim": "", "snapshot": snap},
        "ground_truth": {"documented_issues": issues},
        "h2_expected_specificity": [f"{top['year']} {top['make']} {top['model']}"]
                                   + [f"NHTSA recall {i['campaign']}" for i in issues],
        "provenance": {"created": CREATED, "created_by": "brief-2a",
                       "notes": "No codes; warm idle within normal ranges (invented). Documented issues "
                                "are the recalls the backend's own retrieval returns for this vehicle."},
    }


def _key(v):
    return f"{v[0]}|{v[1]}|{v[2]}"


def build(adjudication, recalls, taxonomy):
    labels = [lb["label"] for lb in taxonomy["labels"]]
    accepted = sorted((d for d in adjudication["decisions"] if d["accept"]), key=lambda d: d["odi_number"])
    cases, n = [], 0
    for row in accepted:
        n += 1
        v = (row["year"], row["make"], row["model"])
        cases.append(reconstructed_case(f"EV-{n:03d}", row, recalls.get(_key(v), [])))
    recon_counts = {lb: sum(c["ground_truth"]["primary_label"] == lb for c in cases) for lb in labels}
    total_synthetic = TARGET_TOTAL - len(cases)
    assert total_synthetic <= MAX_SYNTHETIC_SHARE * TARGET_TOTAL, "synthetic share over the cap"
    plan = allocate_synthetic(recon_counts, labels, total_synthetic)
    vehicles = iter(SYNTHETIC_VEHICLES * 3)
    for label in labels:
        templates = [t for t in SYNTHETIC_TEMPLATES if t["primary"] == label]
        for i in range(plan[label]):
            n += 1
            t = templates[i % len(templates)]
            v = next(vehicles)
            case = synthetic_case(f"EV-{n:03d}", t, v, recalls.get(_key(v), []))
            check_synthetic(case, t)
            cases.append(case)
    profiles, m = [], 0
    for v in CODELESS_VEHICLES:
        p = codeless_profile(f"CL-{m + 1:03d}", v, recalls.get(_key(v), []))
        if p:
            m += 1
            profiles.append(p)
    return cases, profiles


H4_RULE = ("A hit is when the model's output names at least one documented issue for the profile: "
           "its NHTSA campaign number, or at least two distinctive words of its recall component "
           "(scripts/eval_score.py:h4_hit). Threshold: 50% of profiles. Pinned; do not change.")


async def fetch(vehicles):
    import httpx
    import knowledge
    out = {}
    async with httpx.AsyncClient():
        for v in vehicles:
            # The backend's own retrieval call, so documented issues match what it can see.
            out[_key(v)] = await knowledge.search_nhtsa_recalls(v[1], v[2], str(v[0]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="refresh eval/sources/recalls.json from NHTSA")
    args = ap.parse_args()
    adjudication = json.loads((EVAL / "sources" / "adjudication.json").read_text())
    taxonomy = json.loads((EVAL / "taxonomy.json").read_text())
    if args.fetch:
        wanted = sorted({(d["year"], d["make"], d["model"]) for d in adjudication["decisions"] if d["accept"]}
                        | set(SYNTHETIC_VEHICLES) | set(CODELESS_VEHICLES))
        recalls = asyncio.run(fetch(wanted))
        (EVAL / "sources" / "recalls.json").write_text(json.dumps(
            {"source": "knowledge.search_nhtsa_recalls (api.nhtsa.gov/recalls/recallsByVehicle), top 5 "
                       "per vehicle as the backend retrieves them",
             "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "recalls": recalls}, indent=1))
        print(f"fetched recalls for {len(recalls)} vehicles")
        return
    recalls = json.loads((EVAL / "sources" / "recalls.json").read_text())["recalls"]
    cases, profiles = build(adjudication, recalls, taxonomy)
    (EVAL / "eval_set.json").write_text(json.dumps(
        {"version": "eval-v1", "created": CREATED, "cases": cases}, indent=1))
    (EVAL / "codeless_set.json").write_text(json.dumps(
        {"version": "eval-v1", "created": CREATED, "h4_rule": H4_RULE, "h4_threshold": 0.5,
         "profiles": profiles}, indent=1))
    print(f"{len(cases)} eval cases, {len(profiles)} codeless profiles")


if __name__ == "__main__":
    main()
