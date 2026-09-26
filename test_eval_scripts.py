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


# --- eval_run / eval_score --------------------------------------------------------

run = None
score = None


def _run_score():
    global run, score
    if run is None:
        run, score = _load("eval_run"), _load("eval_score")
    return run, score


def test_request_body_is_the_eval_case_transport():
    r, _ = _run_score()
    case = build.reconstructed_case("EV-001", ADJ_ROW, recalls=[])
    body = r.request_body(case)
    assert body == {"eval_case": {"case_id": "EV-001", **case["payload"]}}
    main._eval_fixture(body["eval_case"])


def test_run_refuses_a_serving_condition_it_was_not_told_to_measure():
    r, _ = _run_score()
    assert r.check_condition({"model": "cleardrive-qwen", "think": "default"}, "cleardrive-qwen", "default") == []
    problems = r.check_condition({"model": "gemma4:e4b", "think": "off"}, "cleardrive-qwen", "default")
    assert len(problems) == 2


def test_transport_error_is_retried_once_then_recorded():
    import httpx
    r, _ = _run_score()
    class Flaky:
        def __init__(self, fails):
            self.fails, self.calls = fails, 0
        def post(self, url, json=None, timeout=None):
            self.calls += 1
            if self.calls <= self.fails:
                raise httpx.ConnectError("down")
            return type("R", (), {"status_code": 200, "json": lambda s: {"finish_reason": "stop"}})()
    once = Flaky(1)
    status, body, error, _ = r.post_with_retry(once, "u", {}, 1, sleep=lambda s: None)
    assert (status, body["finish_reason"], error, once.calls) == (200, "stop", None, 2)
    twice = Flaky(2)
    status, body, error, _ = r.post_with_retry(twice, "u", {}, 1, sleep=lambda s: None)
    assert status is None and body is None and "ConnectError" in error and twice.calls == 2


def test_truncation_gate_fails_over_five_percent_and_ignores_the_warmup():
    r, _ = _run_score()
    calls = [{"case_id": "warmup", "warmup": True, "finish_reason": "length"}] + \
            [{"case_id": f"EV-{i:03d}", "finish_reason": "stop"} for i in range(95)] + \
            [{"case_id": f"EV-{i:03d}", "finish_reason": "length"} for i in range(95, 100)]
    assert r.truncation_summary(calls)["gate"] == "PASS"          # 5/100 is not over 5%
    calls.append({"case_id": "EV-100", "finish_reason": "length"})
    s = r.truncation_summary(calls)
    assert s["gate"] == "FAIL" and s["truncated"] == 6 and s["calls"] == 101


def test_model_labels_come_from_likely_causes_in_order_of_mention():
    _, s = _run_score()
    text = "1. A failing oxygen sensor ... 2. a vacuum leak at the intake boot ... 3. the O2 sensor wiring"
    assert s.predicted_labels(text) == ["oxygen_sensor", "vacuum_intake_leak"]
    assert s.predicted_labels("") == []


@pytest.mark.parametrize("codes,labels", [
    (["P0171"], ["fuel_delivery"]), (["P0302"], ["ignition_component"]), (["P0335"], ["ignition_system_sensor"]),
    (["P0420"], ["catalytic_converter"]), (["P0455"], ["evap_system"]), (["P2196"], ["oxygen_sensor"]),
    (["P2135"], ["air_fuel_metering_other"]), (["P0700"], ["transmission"]), (["P1450"], []),
    (["P0A7A"], []), (["P0302", "P0304"], ["ignition_component"])])
def test_rule_based_arm_maps_codes_by_range(codes, labels):
    _, s = _run_score()
    assert s.rule_based_labels(codes) == labels


def test_precision_recall_f1_and_macro():
    _, s = _run_score()
    per, macro = s.prf([{"a"}, {"a"}, {"b"}], [{"a"}, {"b"}, {"b"}], ["a", "b"])
    assert per["a"] == {"precision": 1.0, "recall": 0.5, "f1": 0.6667, "support": 2, "tp": 1, "fp": 0, "fn": 1}
    assert per["b"]["precision"] == 0.5 and per["b"]["recall"] == 1.0
    assert macro == round((0.6667 + 0.6667) / 2, 4)


def test_h4_hit_by_campaign_or_two_component_words():
    _, s = _run_score()
    issue = {"campaign": "15V001000", "component": "FUEL SYSTEM, GASOLINE:DELIVERY:FUEL PUMP"}
    assert s.h4_hit("There is an open recall 15V001000 for this car.", [issue])
    assert s.h4_hit("A recall covers the fuel pump.", [issue])   # part-level words FUEL + PUMP
    assert not s.h4_hit("Check the fuel cap.", [issue])       # one word is not enough
    assert not s.h4_hit("", [issue])


def test_latency_excludes_warmup_and_failed_calls():
    _, s = _run_score()
    calls = [{"case_id": "warmup", "warmup": True, "seconds": 90.0, "error": None},
             {"case_id": "a", "seconds": 10.0, "error": None},
             {"case_id": "b", "seconds": 20.0, "error": None},
             {"case_id": "c", "seconds": 500.0, "error": "HTTP 500"}]
    lat = s.latency(calls)
    assert lat["n"] == 2 and lat["mean"] == 15.0 and lat["p50"] == 15.0


def test_scoring_reads_the_model_text_not_the_rule_engine():
    _, s = _run_score()
    taxonomy = json.loads((ROOT / "eval" / "taxonomy.json").read_text())
    labels = [lb["label"] for lb in taxonomy["labels"]]
    case = build.reconstructed_case("EV-001", ADJ_ROW, recalls=[])
    profile = build.codeless_profile("CL-001", (2014, "Ford", "ESCAPE"), recalls=[RECALL])
    responses = {"EV-001": {"likely_causes": "The throttle body is failing.",
                            "differential": [{"conclusion": "oxygen sensor"}]},
                 "CL-001": {"known_issues": "Recall 15V001000 covers the fuel pump."}}
    scores, h2, unmapped = s.score([case], [profile], labels, responses)
    assert scores["h1"]["top1_accuracy"] == 1.0
    assert scores["h1"]["per_label"]["oxygen_sensor"]["fp"] == 0
    assert scores["h4"]["hit_rate"] == 1.0
    assert [row["case_id"] for row in h2] == ["EV-001", "CL-001"] and unmapped == []


def test_scorer_refuses_a_run_that_failed_the_truncation_gate():
    _, s = _run_score()
    with pytest.raises(SystemExit):
        s.check_gate({"truncation": {"gate": "FAIL", "share": 0.08}, "failure": {"gate": "PASS"}})
    s.check_gate({"truncation": {"gate": "PASS", "share": 0.01}, "failure": {"gate": "PASS"}})


def test_h4_single_word_component_hits_only_by_campaign():
    # Pinned rule: two distinctive words, unconditionally (review finding 2026-09-26).
    _, s = _run_score()
    issue = {"campaign": "18V934000", "component": "ENGINE"}
    assert not s.h4_hit("The engine seems to run fine overall.", [issue])
    assert s.h4_hit("Recall 18V934000 applies to this engine.", [issue])


def test_latency_with_a_single_call_does_not_crash():
    _, s = _run_score()
    lat = s.latency([{"case_id": "a", "seconds": 12.0, "error": None}])
    assert lat == {"n": 1, "mean": 12.0, "p50": 12.0, "p95": None}


@pytest.mark.parametrize("status,body,expected_error", [
    (500, {"error": "boom"}, "HTTP 500"), (200, ValueError, "HTTP 200: non-JSON body")])
def test_non_200_and_non_json_are_recorded_without_retry(status, body, expected_error):
    r, _ = _run_score()
    calls = []
    class Resp:
        status_code = status
        def json(self):
            if body is ValueError:
                raise ValueError("not json")
            return body
    class Client:
        def post(self, url, json=None, timeout=None):
            calls.append(url)
            return Resp()
    got_status, _, error, _ = r.post_with_retry(Client(), "u", {}, 1, sleep=lambda s: None)
    assert got_status == status and error == expected_error and len(calls) == 1


def test_run_refuses_to_reuse_a_run_id(tmp_path, monkeypatch):
    r, _ = _run_score()
    monkeypatch.setattr(r, "EVAL", tmp_path)
    (tmp_path / "runs" / "taken").mkdir(parents=True)
    monkeypatch.setattr("sys.argv", ["eval_run.py", "--run-id", "taken", "--expect-model", "m",
                                     "--expect-think", "default"])
    with pytest.raises(SystemExit, match="used once"):
        r.main()


# --- review round 2 (2026-09-26): H4 null baseline, silent failures, spellings, hex ranges ---

GENERIC_TEXTS = [
    "Your air bags and seat belts are fine.",
    "Keep the engine cooling system topped up. Check brake lights and automatic transmission fluid.",
    "Open recalls on air bags, seat belts or service brakes are repaired free by the dealer.",
]


def test_h4_null_baseline_stays_far_below_threshold():
    """A response that knows nothing about the vehicle must not clear H4."""
    _, s = _run_score()
    profiles = json.loads((ROOT / "eval" / "codeless_set.json").read_text())["profiles"]
    for text in GENERIC_TEXTS + [" ".join(GENERIC_TEXTS)]:
        rate = s.h4_null_rate(profiles, text)
        assert rate <= 0.1, (text, rate)


def test_h4_null_baseline_is_a_fixed_published_text():
    _, s = _run_score()
    assert s.H4_NULL_RESPONSE.strip() and s.H4_NULL_RESPONSE == " ".join(GENERIC_TEXTS)


def test_h4_reads_only_the_known_issues_section():
    _, s = _run_score()
    issue = {"campaign": "15V001000", "component": "FUEL SYSTEM, GASOLINE:DELIVERY:PUMP"}
    assert s.h4_hit(s.h4_text({"known_issues": "Recall 15V001000 covers this car."}), [issue])
    assert not s.h4_hit(s.h4_text({"service_recommendations": "Recall 15V001000 covers this car."}), [issue])


def test_h4_component_words_come_from_the_leaf_not_the_category_head():
    _, s = _run_score()
    issue = {"campaign": "20V100000", "component": "AIR BAGS:FRONTAL:DRIVER SIDE:INFLATOR MODULE"}
    assert not s.h4_hit("air bags", [issue])
    assert s.h4_hit("the driver air bag inflator module can rupture", [issue])


@pytest.mark.parametrize("body,reason", [
    ({"dont_panic": "ERROR: Request timed out.", "finish_reason": None}, "model error"),
    ({"likely_causes": "x"}, "no finish_reason"),
    ({"error": "Invalid eval_case 'EV-1': bad"}, "backend error"),
])
def test_model_failures_behind_http_200_are_failures(body, reason):
    r, _ = _run_score()
    assert reason in r.call_error(200, body, None)


def test_a_clean_200_is_not_a_failure():
    r, _ = _run_score()
    assert r.call_error(200, {"finish_reason": "stop", "dont_panic": "fine"}, None) is None


def test_failure_gate_fails_over_five_percent_and_scorer_refuses_it():
    r, s = _run_score()
    calls = [{"case_id": "warmup", "warmup": True, "error": "x"}] + \
            [{"case_id": f"EV-{i:03d}", "error": None} for i in range(94)] + \
            [{"case_id": f"EV-{i:03d}", "error": "model error"} for i in range(94, 100)]
    g = r.failure_summary(calls)
    assert g["gate"] == "FAIL" and g["failed"] == 6
    with pytest.raises(SystemExit):
        s.check_gate({"truncation": {"gate": "PASS"}, "failure": g})


def test_runner_waits_longer_than_the_backend_model_timeout():
    # Ruling 2026-09-26: backend 300 s, runner 330 s, so the backend's timeout fires first
    # and comes back as a classified model error rather than a transport error.
    import ollama_client
    r, _ = _run_score()
    assert ollama_client.MODEL_TIMEOUT_S == 300.0
    assert r.DEFAULT_TIMEOUT_S == 330.0 > ollama_client.MODEL_TIMEOUT_S


@pytest.mark.parametrize("text,label", [
    ("a failing air-fuel ratio sensor", "oxygen_sensor"), ("the air/fuel ratio sensor", "oxygen_sensor"),
    ("upstream O2 sensor heater", "oxygen_sensor"), ("mass-air-flow sensor", "maf_sensor"),
    ("manifold absolute pressure sensor", "air_fuel_metering_other"),
    ("crankshaft position (CKP) sensor", "ignition_system_sensor"),
    ("camshaft position (CMP) sensor", "ignition_system_sensor")])
def test_common_spellings_map_to_labels(text, label):
    _, s = _run_score()
    assert s.predicted_labels(text) == [label]


@pytest.mark.parametrize("codes,labels", [
    (["P219B"], ["air_fuel_metering_other"]), (["P04F1"], ["emissions_control_other"]),
    (["P00A0"], ["valve_timing_air_aux"]), (["P2196"], ["oxygen_sensor"]), (["P0A7A"], []),
    (["P0444"], ["evap_system"]), (["P0351"], ["ignition_component"]), (["P0236"], ["valve_timing_air_aux"]),
    (["P245B"], ["emissions_control_other"]), (["P2450"], ["evap_system"]), (["P2401"], ["evap_system"])])
def test_rule_based_ranges_cover_hex_codes(codes, labels):
    _, s = _run_score()
    assert s.rule_based_labels(codes) == labels


def test_air_fuel_mixture_talk_is_not_an_oxygen_sensor():
    _, s = _run_score()
    assert s.predicted_labels("the air-fuel mixture is lean") == []


def test_gate_fails_closed_when_the_failure_record_is_missing():
    _, s = _run_score()
    with pytest.raises(SystemExit, match="failure record"):
        s.check_gate({"truncation": {"gate": "PASS"}})


# --- pre-registered 2026-09-26: two H4 null baselines; re-scoring never overwrites ---

PART_LEVEL_NULL = ("No verified issue history was available. A failing fuel pump is a common issue. "
                   "Have the brake master cylinder checked. The driver side or passenger side air bag "
                   "inflator should be inspected. The occupant classification sensor may need recalibration.")


def test_both_fixed_null_texts_are_published_in_the_scorer():
    _, s = _run_score()
    assert s.H4_NULL_RESPONSES == {"system_level": s.H4_NULL_RESPONSE, "part_level": PART_LEVEL_NULL}


def test_scores_report_both_null_baselines(tmp_path):
    _, s = _run_score()
    taxonomy = json.loads((ROOT / "eval" / "taxonomy.json").read_text())
    labels = [lb["label"] for lb in taxonomy["labels"]]
    profiles = json.loads((ROOT / "eval" / "codeless_set.json").read_text())["profiles"]
    scores, _, _ = s.score([], profiles, labels, {})
    nulls = scores["h4"]["null_baselines"]
    assert nulls["system_level"] == s.h4_null_rate(profiles, s.H4_NULL_RESPONSE)
    assert nulls["part_level"] == s.h4_null_rate(profiles, PART_LEVEL_NULL)
    md = s._markdown("r", {**scores, "h1": {"macro_f1": 0, "top1_accuracy": 0, "cases": 0, "per_label": {}}},
                     None, [], [], None)
    assert "system-level null" in md and "part-level null" in md


def _fake_run(tmp_path, s, monkeypatch):
    out = tmp_path / "runs" / "r1"
    out.mkdir(parents=True)
    (out / "run_meta.json").write_text(json.dumps({"truncation": {"gate": "PASS"}, "failure": {"gate": "PASS"},
                                                    "calls": []}))
    monkeypatch.setattr(s, "EVAL", tmp_path)
    for name in ("eval_set.json", "codeless_set.json", "taxonomy.json"):
        (tmp_path / name).write_text((ROOT / "eval" / name).read_text())
    return out


def test_rescoring_never_overwrites_the_original_scores(tmp_path, monkeypatch):
    _, s = _run_score()
    out = _fake_run(tmp_path, s, monkeypatch)
    monkeypatch.setattr("sys.argv", ["eval_score.py", "--run-id", "r1"])
    s.main()
    original = (out / "scores.json").read_text()
    with pytest.raises(SystemExit, match="--rescore"):
        s.main()
    monkeypatch.setattr("sys.argv", ["eval_score.py", "--run-id", "r1", "--rescore", "v2",
                                     "--reason", "vocabulary fix after review"])
    s.main()
    assert (out / "scores.json").read_text() == original
    rescored = json.loads((out / "scores-v2.json").read_text())
    assert rescored["rescore"] == {"name": "v2", "reason": "vocabulary fix after review"}
    assert (out / "scores-v2.md").exists()


def test_rescore_requires_a_reason(tmp_path, monkeypatch):
    _, s = _run_score()
    _fake_run(tmp_path, s, monkeypatch)
    monkeypatch.setattr("sys.argv", ["eval_score.py", "--run-id", "r1", "--rescore", "v2"])
    with pytest.raises(SystemExit):
        s.main()


@pytest.mark.parametrize("name", ["../x", "a/b", "a\\b", "..", ""])
def test_rescore_name_cannot_leave_the_run_directory(tmp_path, monkeypatch, name):
    _, s = _run_score()
    _fake_run(tmp_path, s, monkeypatch)
    monkeypatch.setattr("sys.argv", ["eval_score.py", "--run-id", "r1", "--rescore", name, "--reason", "x"])
    with pytest.raises(SystemExit):
        s.main()
    assert not list(tmp_path.rglob("scores-*"))
