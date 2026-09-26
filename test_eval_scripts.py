"""Offline tests for the eval-set builder, validator, runner and scorer (scripts/eval_*.py).

Run: .venv/bin/python -m pytest -q test_eval_scripts.py
"""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

import diagnostics
import main

ROOT = Path(__file__).parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


build = _load("eval_build")
validate = _load("eval_validate")

ADJ_ROW = {"odi_number": 10449313, "year": 2009, "make": "Toyota", "model": "COROLLA",
           "codes": ["P0121"], "accept": True, "primary_label": "air_fuel_metering_other",
           "fault_labels": ["air_fuel_metering_other"],
           "repair_quote": "FOUND CODE P0121 ... REPLACED THROTTLE BODY, RETESTED WORKING NORMAL",
           "note": "", "source_url": "https://api.nhtsa.gov/complaints/complaintsByVehicle?make=Toyota&model=COROLLA&modelYear=2009#odiNumber=10449313"}
RECALL = {"NHTSACampaignNumber": "15V001000", "Component": "FUEL SYSTEM, GASOLINE:DELIVERY:PUMP",
          "Summary": "The fuel pump may fail."}


def _eval_fixture(case):
    return main._eval_fixture({"case_id": case["case_id"], **case["payload"]})


# --- eval_build ---------------------------------------------------------------

@pytest.mark.parametrize("year,era", [(2000, "pre-CAN"), (2007, "pre-CAN"), (2008, "CAN"), (2022, "CAN")])
def test_obd_era_by_model_year(year, era):
    assert build.obd_era(year) == era


def test_reconstructed_case_carries_codes_only_and_is_a_valid_eval_payload():
    case = build.reconstructed_case("EV-001", ADJ_ROW, recalls=[])
    snap = case["payload"]["snapshot"]
    assert [c["code"] for c in snap["dtc_codes"]] == ["P0121"]
    # Missing is null (CLAUDE.md Never #2): no measurement is invented for a complaint.
    for field in ("rpm", "speed_mph", "coolant_temp_f", "engine_load_pct", "intake_air_temp_f",
                  "maf_rate_gs", "fuel_pressure_psi", "control_module_voltage", "mileage"):
        assert snap[field] is None
    assert snap["fuel_trims"] == [] and snap["freeze_frames"] == [] and snap["mode06"] == []
    assert snap["capability"]["freeze_frame_available"] is None
    assert any("NHTSA complaint" in lim for lim in snap["capability"]["limitations"])
    gt = case["ground_truth"]
    assert gt["primary_label"] == "air_fuel_metering_other" and gt["source_type"] == "nhtsa_complaint"
    assert gt["source_url"] == ADJ_ROW["source_url"]
    assert case["vehicle"]["obd_era"] == "CAN" and case["vehicle"]["engine"] is None
    _eval_fixture(case)


def test_h2_specificity_lists_vehicle_and_only_label_matched_recalls():
    fuel_row = dict(ADJ_ROW, primary_label="fuel_delivery", fault_labels=["fuel_delivery"])
    other = {"NHTSACampaignNumber": "15V999000", "Component": "AIR BAGS", "Summary": "x"}
    case = build.reconstructed_case("EV-001", fuel_row, recalls=[RECALL, other])
    assert case["h2_expected_specificity"][0] == "2009 Toyota COROLLA"
    assert "NHTSA recall 15V001000" in " ".join(case["h2_expected_specificity"])
    assert "15V999000" not in " ".join(case["h2_expected_specificity"])


@pytest.mark.parametrize("template", build.SYNTHETIC_TEMPLATES, ids=lambda t: t["id"])
def test_every_synthetic_template_trips_its_intended_rule(template):
    case = build.synthetic_case("EV-100", template, (2012, "Honda", "ACCORD"), recalls=[])
    build.check_synthetic(case, template)  # raises if the rule outcome is not the intended one
    assert case["ground_truth"]["source_type"] == f"synthetic_from:{template['primary']}"
    assert case["ground_truth"]["source_url"].startswith("diagnostics.py:")
    _eval_fixture(case)


def test_check_synthetic_rejects_a_template_that_does_not_trip_its_rule():
    t = copy.deepcopy(next(t for t in build.SYNTHETIC_TEMPLATES if t["id"] == "vacuum_leak_idle_heavy"))
    t["snapshot"]["fuel_trims"] = [{"condition": "idle", "stft_bank1": 1.0, "ltft_bank1": 1.0},
                                   {"condition": "loaded", "stft_bank1": 1.0, "ltft_bank1": 1.0}]
    case = build.synthetic_case("EV-100", t, (2012, "Honda", "ACCORD"), recalls=[])
    with pytest.raises(AssertionError):
        build.check_synthetic(case, t)


def test_synthetic_allocation_fills_short_labels_and_respects_the_cap():
    labels = ["a", "b", "c"]
    recon = {"a": 6, "b": 2, "c": 0}
    plan = build.allocate_synthetic(recon, labels, total_synthetic=9)
    assert sum(plan.values()) == 9
    assert recon["b"] + plan["b"] >= 5 and recon["c"] + plan["c"] >= 5


def test_codeless_profile_needs_a_recall_and_carries_no_codes():
    assert build.codeless_profile("CL-001", (2014, "Ford", "ESCAPE"), recalls=[]) is None
    p = build.codeless_profile("CL-001", (2014, "Ford", "ESCAPE"), recalls=[RECALL])
    assert p["payload"]["snapshot"]["dtc_codes"] == []
    issue = p["ground_truth"]["documented_issues"][0]
    assert issue["source_type"] == "nhtsa_recall" and issue["campaign"] == "15V001000"
    assert "15V001000" in issue["source_url"]
    _eval_fixture(p)


# --- eval_validate --------------------------------------------------------------

def _small_set():
    taxonomy = json.loads((ROOT / "eval" / "taxonomy.json").read_text())
    cases = [build.reconstructed_case("EV-001", ADJ_ROW, recalls=[])]
    codeless = [build.codeless_profile("CL-001", (2014, "Ford", "ESCAPE"), recalls=[RECALL])]
    return cases, codeless, taxonomy


def test_validator_accepts_a_well_formed_set():
    cases, codeless, taxonomy = _small_set()
    assert validate.validate(cases, codeless, taxonomy) == []


def test_validator_flags_duplicate_ids_unknown_labels_and_empty_sources():
    cases, codeless, taxonomy = _small_set()
    dup = copy.deepcopy(cases[0])
    bad = copy.deepcopy(cases[0])
    bad["case_id"] = "EV-002"
    bad["ground_truth"]["primary_label"] = "flux_capacitor"
    bad["ground_truth"]["source_url"] = ""
    errors = " | ".join(validate.validate(cases + [dup, bad], codeless, taxonomy))
    assert "duplicate case_id EV-001" in errors
    assert "flux_capacitor" in errors
    assert "source_url" in errors


def test_validator_flags_a_case_that_duplicates_a_fixture():
    cases, codeless, taxonomy = _small_set()
    leak = copy.deepcopy(cases[0])
    leak["case_id"] = "EV-003"
    leak["payload"]["vehicle"]["full_name"] = "2015 Ford F-150"
    leak["payload"]["snapshot"]["dtc_codes"] = [{"code": "P0301", "description": ""}]
    errors = " | ".join(validate.validate(cases + [leak], codeless, taxonomy))
    assert "fixture" in errors


# --- the frozen artifacts --------------------------------------------------------

def test_frozen_set_is_exactly_what_the_builder_produces_from_committed_sources():
    """A rebuild from eval/sources/* must reproduce the frozen files byte for byte."""
    import hashlib
    manifest = json.loads((ROOT / "eval" / "MANIFEST.json").read_text())
    adjudication = json.loads((ROOT / "eval" / "sources" / "adjudication.json").read_text())
    recalls = json.loads((ROOT / "eval" / "sources" / "recalls.json").read_text())["recalls"]
    taxonomy = json.loads((ROOT / "eval" / "taxonomy.json").read_text())
    cases, profiles = build.build(adjudication, recalls, taxonomy)
    frozen = json.loads((ROOT / "eval" / "eval_set.json").read_text())
    assert frozen["cases"] == cases
    assert json.loads((ROOT / "eval" / "codeless_set.json").read_text())["profiles"] == profiles
    for rel, digest in manifest["sha256"].items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == digest, rel


def test_no_payload_names_its_ground_truth():
    """Labels and repair text live only in ground_truth; the model input never carries them."""
    def values(x):  # string values only; field names such as control_module_voltage are schema
        if isinstance(x, dict):
            return " ".join(values(v) for v in x.values())
        if isinstance(x, list):
            return " ".join(values(v) for v in x)
        return x if isinstance(x, str) else ""
    frozen = json.loads((ROOT / "eval" / "eval_set.json").read_text())["cases"]
    for case in frozen:
        payload = values(case["payload"]).lower()
        for label in case["ground_truth"]["fault_labels"]:
            assert label not in payload and label.replace("_", " ") not in payload, case["case_id"]
        if case["case_type"] == "reconstructed":
            assert case["ground_truth"]["confirmed_repair"].lower()[:40] not in payload, case["case_id"]
