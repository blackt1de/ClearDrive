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
