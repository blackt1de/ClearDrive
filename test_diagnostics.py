"""Regression tests for the deterministic layer.

Everything here runs offline with no model and no network — the point is that
the parts of a diagnosis with a right answer are testable, and only the
narration needs a language model.

Run: .venv/bin/python -m pytest test_diagnostics.py -q
     .venv/bin/python test_diagnostics.py     (no pytest required)
"""

import diagnostics
import dtc_definitions
import fixtures
from main import parse_guidance

# Every header the /interpret prompt asks the model to emit. If a header is
# added to the prompt without a matching entry in parse_guidance's section_map,
# that section silently parses as empty — which is how ESTIMATED REPAIR COST was
# lost after header matching was anchored.
PROMPT_HEADERS = [
    ("SAFETY LEVEL", "safety_level"),
    ("WHAT'S HAPPENING", "dont_panic"),
    ("LIKELY CAUSES", "likely_causes"),
    ("WHAT YOU MIGHT NOTICE", "symptoms"),
    ("IF YOU IGNORE THIS", "if_ignored"),
    ("QUICK CHECKS", "quick_checks"),
    ("DIY FIX", "diy_fix"),
    ("WHEN TO SEE A MECHANIC", "urgency"),
    ("ESTIMATED REPAIR COST", "repair_cost"),
    ("SERVICE RECOMMENDATIONS", "service_recommendations"),
    ("KNOWN ISSUES FOR THIS ENGINE", "known_issues"),
    ("OTHER OWNERS REPORT", "owner_reports"),
]


def test_every_prompt_header_parses():
    body = "\n\n".join(f"{h}:\ncontent for {key}" for h, key in PROMPT_HEADERS)
    parsed = parse_guidance(body)
    for header, key in PROMPT_HEADERS:
        assert parsed[key], f"header {header!r} did not populate {key!r}"


def test_prose_does_not_open_a_section():
    """The bug that contaminated the format-adherence metric."""
    body = (
        "SAFETY LEVEL: CAUTION\n\n"
        "WHAT'S HAPPENING:\n"
        "We checked several car databases for this code.\n"
        "This shortens the SERVICE life of the part, per the COMMUNITY consensus.\n"
    )
    parsed = parse_guidance(body)
    assert "databases" in parsed["dont_panic"]
    assert "SERVICE life" in parsed["dont_panic"]
    assert not parsed["service_recommendations"]
    assert not parsed["owner_reports"]
    assert not parsed["known_issues"]


def test_manufacturer_codes_are_never_given_a_meaning():
    for code in ("P1131", "P1497", "P1450", "C1234", "B1000", "P3055"):
        r = dtc_definitions.resolve(code)
        assert r["tier"] == dtc_definitions.TIER_STRUCTURAL, code
        assert "not been verified" in r["caveat"], code


def test_standardized_codes_resolve_with_an_unverified_tier():
    r = dtc_definitions.resolve("P0420")
    assert r["tier"] == dtc_definitions.TIER_STANDARDIZED
    assert "Catalyst" in r["description"]


def test_missing_capability_abstains_and_never_concludes():
    """The whole design in one assertion: no data means no diagnosis."""
    s = fixtures.get_scenario("sonata-2011-p0171-no-capability")
    a = diagnostics.analyze(s["snapshot"], s["vehicle"])
    assert not a.causes, "rules must not conclude without fuel trims"
    assert a.abstentions
    assert any("fuel trim" in x.reason.lower() for x in a.abstentions)


def test_vacuum_leak_pattern_detected():
    s = fixtures.get_scenario("accord-2012-p0171-vacuum-leak")
    a = diagnostics.analyze(s["snapshot"], s["vehicle"])
    assert a.derived["total_trim_bank1_at_idle_pct"] == 22.7
    assert any("after the mass airflow sensor" in f.conclusion for f in a.causes)


def test_bank_specific_fault_rules_out_shared_components():
    s = fixtures.get_scenario("bmw-550i-2013-p0171-bank-specific")
    a = diagnostics.analyze(s["snapshot"], s["vehicle"])
    assert a.derived["bank_asymmetry_at_idle_pct"] >= diagnostics.TRIM_BANK_ASYMMETRY
    assert any("one bank only" in f.conclusion for f in a.causes)


def test_catalyst_marginal_vs_dead_are_distinguished():
    marginal = diagnostics.analyze(fixtures.get_scenario("camry-2010-p0420-marginal")["snapshot"])
    dead = diagnostics.analyze(
        fixtures.get_scenario("silverado-2014-p0420-p0300-secondary")["snapshot"])
    assert any("only just" in f.conclusion for f in marginal.causes)
    assert any("well past its limit" in f.conclusion for f in dead.causes)


def test_catalyst_code_with_upstream_fault_orders_the_repair():
    a = diagnostics.analyze(
        fixtures.get_scenario("silverado-2014-p0420-p0300-secondary")["snapshot"])
    assert any("should not be replaced until the upstream fault is fixed" in f.conclusion
               for f in a.causes)


def test_turbo_only_checks_are_gated_on_forced_induction():
    turbo = fixtures.get_scenario("m6-2014-bank1-lean-misfire-hard")
    na = fixtures.get_scenario("accord-2012-p0171-vacuum-leak")
    t_checks = " ".join(diagnostics.analyze(turbo["snapshot"], turbo["vehicle"]).all_checks())
    n_checks = " ".join(diagnostics.analyze(na["snapshot"], na["vehicle"]).all_checks())
    assert "charge pipes" in t_checks
    assert "charge pipes" not in n_checks, "a naturally aspirated engine has no boost to leak"


def test_oxygen_sensor_corroborated_by_trims_is_not_blamed():
    """The expensive misdiagnosis: replacing a sensor that is telling the truth."""
    s = fixtures.get_scenario("m6-2014-bank1-lean-misfire-hard")
    a = diagnostics.analyze(s["snapshot"], s["vehicle"])
    assert any("replacing the sensor would not fix" in f.conclusion for f in a.causes)


def test_code_status_is_not_a_cause():
    s = fixtures.get_scenario("m6-2014-bank1-lean-misfire-hard")
    a = diagnostics.analyze(s["snapshot"], s["vehicle"])
    assert all("permanent codes" not in f.conclusion for f in a.causes)
    assert any("permanent codes" in f.conclusion for f in a.statuses)


def test_checks_are_deduplicated():
    s = fixtures.get_scenario("m6-2014-bank1-lean-misfire-hard")
    checks = diagnostics.analyze(s["snapshot"], s["vehicle"]).all_checks()
    assert len(checks) == len(set(checks))


def test_codes_with_no_rule_are_still_reported():
    s = fixtures.get_scenario("m6-2014-bank1-lean-misfire-hard")
    a = diagnostics.analyze(s["snapshot"], s["vehicle"])
    reasons = " ".join(x.reason for x in a.abstentions)
    assert "P052E" in reasons and "P1497" in reasons


def test_every_finding_carries_evidence():
    for name in fixtures.SCENARIOS:
        s = fixtures.get_scenario(name)
        for f in diagnostics.analyze(s["snapshot"], s["vehicle"]).causes:
            assert f.evidence, f"{name}: {f.rule_id} concluded with no evidence"


def test_fixtures_are_deterministic_and_marked_synthetic():
    a = fixtures.get_scenario("m6-2014-bank1-lean-misfire-hard")["snapshot"]
    b = fixtures.get_scenario("m6-2014-bank1-lean-misfire-hard")["snapshot"]
    assert a.model_dump(mode="json") == b.model_dump(mode="json")
    for name in fixtures.SCENARIOS:
        snap = fixtures.get_scenario(name)["snapshot"]
        assert snap.is_mock and snap.fixture_name == name


# --- Safety verdict (Brief 1b) ---------------------------------------------
#
# Hand-labelled ground truth. This table is reviewed, not fitted: if a verdict
# below looks wrong the fix is to argue the label, never to edit the fixture.
#
#   fixture                               | verdict           | why
#   accord-2012-p0171-vacuum-leak         | ok                | trims 22.7% < severe 25%; no misfire; coolant 196
#   f150-2015-p0301-coil                  | stop_driving      | misfire recorded at 68% load, 197°F
#   camry-2010-p0420-marginal             | ok                | cat finding is moderate, not high; trims normal
#   silverado-2014-p0420-p0300-secondary  | stop_driving      | P0300 at 72% load; cat dead (mfr limit, high) adds CAUTION floor
#   bmw-550i-2013-p0171-bank-specific     | ok                | bank1 trim 19.4% < 25%; no misfire
#   escape-2013-p1131-mfg-code            | ok                | no escalating measurement; P1131 structural only
#   sonata-2011-p0171-no-capability       | insufficient_data | lean code, trims unreported; nothing escalated
#   civic-2008-p0442-evap                 | ok                | evap leak, trims normal
#   rav4-2018-clean                       | ok                | no codes
#   m6-2014-bank1-lean-misfire-hard       | stop_driving      | misfires at 84% load, Mode 06 misfire counts over limit
#   tacoma-2009-p0171-severe-trim-synthetic | caution         | total trim 27.3% idle / 25.0% load ≥ severe 25%; no misfire
EXPECTED_VERDICTS = {
    "accord-2012-p0171-vacuum-leak": diagnostics.VERDICT_OK,
    "f150-2015-p0301-coil": diagnostics.VERDICT_STOP,
    "camry-2010-p0420-marginal": diagnostics.VERDICT_OK,
    "silverado-2014-p0420-p0300-secondary": diagnostics.VERDICT_STOP,
    "bmw-550i-2013-p0171-bank-specific": diagnostics.VERDICT_OK,
    "escape-2013-p1131-mfg-code": diagnostics.VERDICT_OK,
    "sonata-2011-p0171-no-capability": diagnostics.VERDICT_INSUFFICIENT,
    "civic-2008-p0442-evap": diagnostics.VERDICT_OK,
    "rav4-2018-clean": diagnostics.VERDICT_OK,
    "m6-2014-bank1-lean-misfire-hard": diagnostics.VERDICT_STOP,
    "tacoma-2009-p0171-severe-trim-synthetic": diagnostics.VERDICT_CAUTION,
}


def _verdict_for(name):
    s = fixtures.get_scenario(name)
    analysis = diagnostics.analyze(s["snapshot"], s["vehicle"])
    return diagnostics.compute_safety(analysis, s["snapshot"], s["vehicle"])


def _make_verdict_test(name, expected):
    def test():
        v = _verdict_for(name)
        assert v.verdict == expected, f"{name}: got {v.verdict}, label says {expected}"
    test.__name__ = f"test_verdict_{name.replace('-', '_')}"
    return test


for _name, _expected in EXPECTED_VERDICTS.items():
    globals()[f"test_verdict_{_name.replace('-', '_')}"] = _make_verdict_test(_name, _expected)


def test_verdict_table_covers_every_fixture():
    assert set(EXPECTED_VERDICTS) == set(fixtures.SCENARIOS)


def test_verdicts_are_not_degenerate():
    """The bug this brief retires: 8 of 10 model-prose verdicts were CAUTION."""
    seen = {_verdict_for(n).verdict for n in fixtures.SCENARIOS}
    assert seen == {diagnostics.VERDICT_OK, diagnostics.VERDICT_CAUTION,
                    diagnostics.VERDICT_STOP, diagnostics.VERDICT_INSUFFICIENT}, seen


def test_compute_safety_is_deterministic():
    import dataclasses
    for name in fixtures.SCENARIOS:
        a = dataclasses.asdict(_verdict_for(name))
        b = dataclasses.asdict(_verdict_for(name))
        assert a == b, name


def test_insufficient_when_codes_present_but_telemetry_nulled():
    from schemas import CapabilityProfile, DTCCode, OBDSnapshot
    snap = OBDSnapshot(
        dtc_codes=[DTCCode(code="P0300", description=""), DTCCode(code="P0171", description="")],
        rpm=None, coolant_temp_f=None, engine_load_pct=None,
        fuel_trims=[], freeze_frames=[], mode06=[],
        capability=CapabilityProfile(),
    )
    # P0300 still earns its CAUTION floor — the code itself is the evidence —
    # so to exercise the abstention path the misfire has to be absent.
    v = diagnostics.compute_safety(diagnostics.analyze(snap), snap)
    assert v.verdict == diagnostics.VERDICT_CAUTION
    snap.dtc_codes = [DTCCode(code="P0171", description="")]
    v = diagnostics.compute_safety(diagnostics.analyze(snap), snap)
    assert v.verdict == diagnostics.VERDICT_INSUFFICIENT
    missing = " ".join(r.statement for r in v.reasons if r.rule_id == "insufficient_data")
    assert "coolant temperature" in missing and "fuel trims" in missing


def _resolve_pointer(pointer, snapshot, analysis):
    """Resolve an evidence pointer into the captured payload. Raises if it cannot."""
    import re
    if pointer.startswith("derived."):
        return analysis.derived[pointer[len("derived."):]]
    m = re.fullmatch(r"(\w+)(?:\[([^\]]+)\])?(?:\.(\w+))?", pointer)
    assert m, pointer
    root, key, attr = m.groups()
    obj = getattr(snapshot, root)
    if key is not None:
        if root == "freeze_frames":
            obj = snapshot.freeze_frame_for(key)
        elif root == "fuel_trims":
            obj = snapshot.trims_at(key)
        elif root == "mode06":
            obj = next((t for t in obj if t.mid == key), None)
        else:
            raise AssertionError(f"unknown indexed root in {pointer}")
        assert obj is not None, pointer
    if attr is not None:
        if root == "fuel_trims" and attr.startswith("bank"):
            return (getattr(obj, f"stft_{attr}"), getattr(obj, f"ltft_{attr}"))
        assert hasattr(obj, attr), pointer
        return getattr(obj, attr)
    return obj


def test_every_safety_reason_pointer_resolves():
    for name in fixtures.SCENARIOS:
        s = fixtures.get_scenario(name)
        analysis = diagnostics.analyze(s["snapshot"], s["vehicle"])
        v = diagnostics.compute_safety(analysis, s["snapshot"], s["vehicle"])
        for r in v.reasons:
            assert r.evidence, f"{name}: reason {r.rule_id} has no evidence"
            for e in r.evidence:
                _resolve_pointer(e.pointer, s["snapshot"], analysis)


def _snap(**kw):
    from schemas import CapabilityProfile, DTCCode, OBDSnapshot
    kw["dtc_codes"] = [DTCCode(code=c, description="") for c in kw.pop("codes", [])]
    kw.setdefault("capability", CapabilityProfile(**fixtures.FULL_CAPABILITY))
    return OBDSnapshot(**kw)


def test_overheat_is_stop_and_null_coolant_is_not():
    hot = _snap(codes=["P0442"], coolant_temp_f=diagnostics.COOLANT_OVERHEAT_F + 1)
    assert diagnostics.compute_safety(diagnostics.analyze(hot), hot).verdict == diagnostics.VERDICT_STOP
    unknown = _snap(codes=["P0442"], coolant_temp_f=None)
    v = diagnostics.compute_safety(diagnostics.analyze(unknown), unknown)
    assert v.verdict == diagnostics.VERDICT_INSUFFICIENT
    assert all(r.rule_id != "coolant_overheat" for r in v.reasons)


def test_no_codes_still_escalates_on_overheat_but_not_on_missing_data():
    hot = _snap(codes=[], coolant_temp_f=diagnostics.COOLANT_OVERHEAT_F + 1)
    assert diagnostics.compute_safety(diagnostics.analyze(hot), hot).verdict == diagnostics.VERDICT_STOP
    unknown = _snap(codes=[], coolant_temp_f=None)
    v = diagnostics.compute_safety(diagnostics.analyze(unknown), unknown)
    assert v.verdict == diagnostics.VERDICT_OK
    assert any(r.rule_id == "no_codes" for r in v.reasons)


def test_interpret_no_codes_path_carries_safety():
    """A clean scan must carry the computed verdict, not the SAFE placeholder."""
    import asyncio
    from unittest.mock import patch
    async def fake_model(prompt, model=None):
        return "SUMMARY:\nclean"
    async def no_retrieval(*a, **k):
        return '<retrieved_context source="none">\nNONE\n</retrieved_context>', []
    import main
    with patch.object(main, "ask_ollama", fake_model), \
         patch.object(main, "build_retrieval_block", no_retrieval), \
         patch.object(main, "log_scan", lambda *a, **k: -1):
        r = asyncio.run(main.interpret(main.InterpretRequest(scenario="rav4-2018-clean")))
    assert r["safety"]["verdict"] == diagnostics.VERDICT_OK
    assert r["safety"]["reasons"][0]["rule"] == "no_codes"
    assert r["safety_level"] == "SAFE"
    # The no-codes path logs a scan (the patched log_scan returns -1); without
    # this the real-car arm of a replay comparison leaves no server-side record.
    assert r["scan_id"] == -1


def test_severe_trim_is_caution():
    from schemas import FuelTrim
    s = _snap(codes=["P0171"], coolant_temp_f=190.0,
              fuel_trims=[FuelTrim(condition="idle", stft_bank1=6.0, ltft_bank1=20.0)])
    v = diagnostics.compute_safety(diagnostics.analyze(s), s)
    assert v.verdict == diagnostics.VERDICT_CAUTION
    assert any(r.rule_id == "fuel_trim_severe" for r in v.reasons)


def test_misfire_without_freeze_frame_is_caution_not_stop():
    s = _snap(codes=["P0301"], coolant_temp_f=190.0)
    v = diagnostics.compute_safety(diagnostics.analyze(s), s)
    assert v.verdict == diagnostics.VERDICT_CAUTION
    assert any("freeze frame" in r.statement for r in v.reasons)


def test_code_status_never_raises_the_verdict():
    from schemas import DTCCode
    s = _snap(codes=["P0442"], coolant_temp_f=190.0,
              permanent_codes=[DTCCode(code="P0442", description="", status="permanent")])
    v = diagnostics.compute_safety(diagnostics.analyze(s), s)
    assert v.verdict == diagnostics.VERDICT_OK
    assert any(r.rule_id == "code_status_permanent" and r.raises_to is None for r in v.reasons)


def test_verdict_basis_names_the_deciding_rule():
    assert _verdict_for("silverado-2014-p0420-p0300-secondary").basis == "heuristic"
    # Dead catalyst with the misfire removed: the vehicle's own limit decides.
    s = fixtures.get_scenario("silverado-2014-p0420-p0300-secondary")["snapshot"]
    s.dtc_codes = [c for c in s.dtc_codes if c.code == "P0420"]
    v = diagnostics.compute_safety(diagnostics.analyze(s), s)
    assert v.verdict == diagnostics.VERDICT_CAUTION and v.basis == "manufacturer_limit"


def test_interpret_response_carries_safety_shape():
    """Fixture-scenario response has response_data['safety'] with the right shape."""
    import asyncio
    from unittest.mock import patch
    async def fake_model(prompt, model=None):
        assert "[SAFETY VERDICT" in prompt and "Pick ONE" not in prompt
        return "SAFETY LEVEL: CAUTION\n\nWHAT'S HAPPENING:\nnarration"
    async def no_retrieval(*a, **k):
        return '<retrieved_context source="none">\nNONE\n</retrieved_context>', []
    import main
    with patch.object(main, "ask_ollama", fake_model), \
         patch.object(main, "build_retrieval_block", no_retrieval), \
         patch.object(main, "log_scan", lambda *a, **k: -1):
        r = asyncio.run(main.interpret(main.InterpretRequest(scenario="f150-2015-p0301-coil")))
    assert r["safety"]["verdict"] == diagnostics.VERDICT_STOP
    assert r["safety"]["basis"] == "heuristic"
    assert {"rule", "statement", "raises_to", "evidence"} <= set(r["safety"]["reasons"][0])
    assert {"pointer", "restatement"} <= set(r["safety"]["reasons"][0]["evidence"][0])
    # The model wrote CAUTION; the computed STOP wins.
    assert r["safety_level"] == "STOP"


if __name__ == "__main__":
    passed = failed = 0
    for fn_name, fn in sorted(globals().items()):
        if not fn_name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            passed += 1
            print(f"  PASS  {fn_name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {fn_name}: {exc}")
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
