"""Offline tests for the eval-set transport and the served thinking mode.

`eval_case` lets the frozen eval set (eval/) reach /interpret over HTTP without
living in fixtures.py, and without ever being research-logged. CLEARDRIVE_THINK
is the server-side switch between the thinking-on and thinking-off conditions.

Run: .venv/bin/python -m pytest -q test_eval_case.py
"""

import asyncio
import importlib
import os
from unittest.mock import patch

import pytest

import fixtures
import main


def _eval_case(case_id="EV-TEST", **snapshot_overrides):
    """A payload in eval-case shape, built from a fixture so it is valid."""
    s = fixtures.get_scenario("f150-2015-p0301-coil")
    snap = s["snapshot"].model_dump(mode="json")
    snap.update({"is_mock": False, "fixture_name": None}, **snapshot_overrides)
    return {"case_id": case_id, "vehicle": s["vehicle"], "trim": "EVAL TRIM", "snapshot": snap}


def _interpret(**request):
    seen = {"research": [], "prompts": [], "carsxe": []}
    async def no_carsxe(codes):
        seen["carsxe"].append(codes)
        return {}
    async def fake_model(prompt, model=None):
        seen["prompts"].append(prompt)
        return "SAFETY LEVEL: STOP\nWHAT'S HAPPENING:\nx"
    async def no_retrieval(*a, **k):
        return '<retrieved_context source="none">\nNONE\n</retrieved_context>', []
    with patch.object(main, "ask_ollama", fake_model), \
         patch.object(main, "build_retrieval_block", no_retrieval), \
         patch.object(main, "log_scan", lambda *a, **k: -1), \
         patch.object(main, "log_research_scan", lambda **k: seen["research"].append(k) or -1), \
         patch.object(main, "decode_obd_codes_batch", no_carsxe):
        r = asyncio.run(main.interpret(main.InterpretRequest(**request)))
    return r, seen


def test_eval_case_runs_the_fixture_path_and_matches_the_scenario():
    via_eval, eval_seen = _interpret(eval_case=_eval_case())
    via_scenario, _ = _interpret(scenario="f150-2015-p0301-coil")
    assert via_eval["safety"] == via_scenario["safety"]
    assert via_eval["codes"] == via_scenario["codes"]
    assert via_eval["data_sources"] == via_scenario["data_sources"]
    # Like a scenario, an eval case never makes the live CarsXE decode call.
    assert eval_seen["carsxe"] == []


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_reading_is_an_error_not_a_crash(value):
    r, _ = _interpret(eval_case=_eval_case("EV-NAN", coolant_temp_f=value))
    assert "error" in r and "EV-NAN" in r["error"]


def test_eval_case_is_never_research_logged_even_if_payload_claims_live():
    _, seen = _interpret(eval_case=_eval_case(is_mock=False))
    assert seen["research"] == []


def test_eval_case_uses_its_own_trim():
    _, seen = _interpret(eval_case=_eval_case())
    assert "EVAL TRIM" in seen["prompts"][0]


def test_malformed_eval_case_is_an_error_not_a_crash():
    r, _ = _interpret(eval_case={"case_id": "EV-BAD", "vehicle": {}, "snapshot": {"rpm": "fast"}})
    assert "error" in r and "EV-BAD" in r["error"]


@pytest.mark.parametrize("vehicle", ["not-a-dict", None, [], {}])
def test_eval_case_without_a_vehicle_object_is_an_error(vehicle):
    # A missing vehicle must fail loudly, never fall through to the live lookup.
    case = _eval_case("EV-BADVEH")
    case["vehicle"] = vehicle
    r, _ = _interpret(eval_case=case)
    assert "error" in r and "EV-BADVEH" in r["error"]


@pytest.mark.parametrize("field,value", [("engine", 5), ("make", 5), ("make", None),
                                         ("model", ""), ("transmission", ["6AT"])])
def test_eval_vehicle_field_of_wrong_type_is_an_error(field, value):
    case = _eval_case("EV-BADFIELD")
    case["vehicle"] = {**case["vehicle"], field: value}
    r, _ = _interpret(eval_case=case)
    assert "error" in r and "EV-BADFIELD" in r["error"]


def test_eval_vehicle_null_engine_is_unknown_not_a_crash():
    # Missing is null (CLAUDE.md Never #2); it renders blank, as the replay fixtures do.
    case = _eval_case()
    case["vehicle"] = {**case["vehicle"], "engine": None, "transmission": None}
    r, _ = _interpret(eval_case=case)
    assert "error" not in r and r["safety"]["verdict"]


@pytest.mark.parametrize("case_id", [None, "", 7])
def test_eval_case_id_must_be_a_non_empty_string(case_id):
    case = _eval_case()
    case["case_id"] = case_id
    r, _ = _interpret(eval_case=case)
    assert "error" in r


def test_eval_trim_must_be_a_string():
    case = _eval_case("EV-BADTRIM")
    case["trim"] = 5
    r, _ = _interpret(eval_case=case)
    assert "error" in r and "EV-BADTRIM" in r["error"]


def test_request_fields_cannot_override_a_frozen_eval_case():
    r, seen = _interpret(eval_case=_eval_case(), trim="OVERRIDE", transmission="MANUAL-X",
                         client_mileage=999999)
    prompt = seen["prompts"][0]
    assert "EVAL TRIM" in prompt and "OVERRIDE" not in prompt
    assert "MANUAL-X" not in prompt and "999999" not in prompt and "999,999" not in prompt


def _reload_ollama_client(value):
    import ollama_client
    env = dict(os.environ)
    env.pop("CLEARDRIVE_THINK", None)
    if value is not None:
        env["CLEARDRIVE_THINK"] = value
    with patch.dict(os.environ, env, clear=True):
        return importlib.reload(ollama_client)


def _sent_body(client):
    sent = {}
    class FakeResponse:
        def raise_for_status(self): pass
        def json(self): return {"message": {"content": "x"}, "done_reason": "stop"}
    async def fake_post(self, url, json=None, **kw):
        sent.update(json)
        return FakeResponse()
    with patch("httpx.AsyncClient.post", fake_post):
        asyncio.run(client.ask_ollama("x"))
    return sent


def test_think_default_sends_no_think_key():
    try:
        client = _reload_ollama_client(None)
        assert client.THINK_MODE == "default"
        assert "think" not in _sent_body(client)
    finally:
        _reload_ollama_client(None)


def test_think_off_sends_think_false():
    try:
        client = _reload_ollama_client("off")
        assert _sent_body(client)["think"] is False
    finally:
        _reload_ollama_client(None)


def test_unknown_think_value_refuses_to_start():
    try:
        with pytest.raises(ValueError):
            _reload_ollama_client("sometimes")
    finally:
        _reload_ollama_client(None)


def test_health_reports_serving_model_and_think_mode():
    async def ok():
        return {"status": "ok"}
    with patch.object(main, "check_ollama", ok):
        h = asyncio.run(main.health())
    assert h["serving"] == {"model": "cleardrive-qwen", "think": "default"}
