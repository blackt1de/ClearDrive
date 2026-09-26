"""Offline tests for NHTSA model-name resolution in knowledge.py.

NHTSA answers HTTP 400 with an empty result set when the exact model string is
not how it files the vehicle, and complaints and recalls file models
differently. These tests replay those server behaviours (observed 2026-09-25)
without the network.

Run: .venv/bin/python -m pytest -q test_knowledge.py
"""

import asyncio
from urllib.parse import urlparse
from unittest.mock import patch

import knowledge

# NHTSA's own model names per (endpoint, year, make), as its products API
# returned them on 2026-09-25.
MODEL_LISTS = {
    ("c", "2015", "Ford"): ["F-150 REGULAR CAB", "F-150 SUPER CREW", "F-150 SUPERCAB", "F-250 SD"],
    ("c", "2014", "Toyota"): ["LANDCRUISER", "FJ CRUISER"],
    ("c", "2015", "Audi"): ["A4", "A5", "ALLROAD"],
    ("r", "2015", "Audi"): ["A4", "A5"],
    # A distinct model line that shares only a name prefix (review finding 2026-09-25).
    ("c", "2022", "Toyota"): ["COROLLA CROSS", "CAMRY"],
    ("c", "2016", "Toyota"): ["TACOMA 2WD", "TACOMA 4WD", "TACOMA DOUBLE CAB"],
    ("c", "2016", "Ford"): ["F-150 REGULAR CAB", "F-150 SUPER CREW"],
    ("c", "2017", "Ford"): ["CREW CAB", "F-150 SUPER CREW"],
}
# (endpoint, model) -> results. Anything absent is a 400 with empty results.
FILED = {
    ("complaints", "F-150 REGULAR CAB"): [{"odiNumber": 1}],
    ("complaints", "F-150 SUPER CREW"): [{"odiNumber": 2}, {"odiNumber": 1}],
    ("complaints", "F-150 SUPERCAB"): [{"odiNumber": 3}],
    ("complaints", "LANDCRUISER"): [{"odiNumber": 7}],
    ("complaints", "A4"): [{"odiNumber": 9}],
    ("recalls", "A4"): [{"NHTSACampaignNumber": "15V001"}],
    ("recalls", "Land Cruiser"): [{"NHTSACampaignNumber": "14V002"}],
    ("complaints", "COROLLA CROSS"): [{"odiNumber": 99}],
    ("complaints", "TACOMA 2WD"): [{"odiNumber": 20}],
    ("complaints", "TACOMA 4WD"): [{"odiNumber": 21}],
    ("complaints", "TACOMA DOUBLE CAB"): [{"odiNumber": 22}],
    # The same complaint filed under two cab variants, with a falsy id.
    ("complaints", "F-150 REGULAR CAB", "2016"): [{"odiNumber": 0, "summary": "as filed under REGULAR CAB"}],
    ("complaints", "F-150 SUPER CREW", "2016"): [{"odiNumber": 0, "summary": "as filed under SUPER CREW"}],
    # A name made only of body words: without the empty-key guard, "" would match it.
    ("complaints", "CREW CAB"): [{"odiNumber": 50}],
}


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _fake_nhtsa(calls):
    async def fake_get(self, url, params=None, **kw):
        calls.append((url, dict(params or {})))
        path = urlparse(url).path
        if path.endswith("/products/vehicle/models"):
            key = (params["issueType"], params["modelYear"], params["make"])
            return FakeResponse(200, {"results": [{"model": m} for m in MODEL_LISTS.get(key, [])]})
        endpoint = "complaints" if "complaints" in path else "recalls"
        if params["model"] == "SERVER-ERROR":
            return FakeResponse(500, {"message": "err"})
        results = FILED.get((endpoint, params["model"], params["modelYear"]),
                            FILED.get((endpoint, params["model"])))
        if results:
            return FakeResponse(200, {"results": results})
        return FakeResponse(400, {"count": 0, "message": "Results returned successfully", "results": []})
    return fake_get


def _run(coro_fn, *args):
    calls = []
    with patch("httpx.AsyncClient.get", _fake_nhtsa(calls)):
        return asyncio.run(coro_fn(*args)), calls


def test_f150_complaints_merge_nhtsa_cab_variants_without_duplicates():
    results, _ = _run(knowledge.search_nhtsa, "Ford", "F-150", "2015")
    assert [r["odiNumber"] for r in results] == [1, 2, 3]


def test_land_cruiser_complaints_resolve_to_nhtsa_spelling():
    results, _ = _run(knowledge.search_nhtsa, "Toyota", "Land Cruiser", "2014")
    assert [r["odiNumber"] for r in results] == [7]


def test_trim_word_is_stripped_before_matching():
    results, _ = _run(knowledge.search_nhtsa, "Audi", "A4 quattro", "2015")
    assert [r["odiNumber"] for r in results] == [9]


def test_exact_name_needs_no_model_list_lookup():
    results, calls = _run(knowledge.search_nhtsa, "Audi", "A4", "2015")
    assert [r["odiNumber"] for r in results] == [9]
    assert not any("products/vehicle/models" in url for url, _ in calls)


def test_recalls_use_their_own_model_list():
    results, calls = _run(knowledge.search_nhtsa_recalls, "Audi", "A4 quattro", "2015")
    assert [r["NHTSACampaignNumber"] for r in results] == ["15V001"]
    assert any(p.get("issueType") == "r" for _, p in calls)


def test_no_nhtsa_name_returns_empty_not_a_guess():
    results, _ = _run(knowledge.search_nhtsa, "Toyota", "Supra", "2014")
    assert results == []


def test_prefix_never_sweeps_in_a_different_model_line():
    # Corolla Cross is not a Corolla body style; its complaints are not Corolla evidence.
    results, _ = _run(knowledge.search_nhtsa, "Toyota", "Corolla", "2022")
    assert results == []


def test_drivetrain_variants_are_not_swept_in_as_body_styles():
    # An exact NHTSA name wins; a prefix match never crosses drivetrains (review 2026-09-25).
    exact, _ = _run(knowledge.search_nhtsa, "Toyota", "Tacoma 4WD", "2016")
    assert [r["odiNumber"] for r in exact] == [21]
    prefix, _ = _run(knowledge.search_nhtsa, "Toyota", "Tacoma", "2016")
    assert [r["odiNumber"] for r in prefix] == [22]


def test_dedupe_keeps_a_falsy_id_once():
    results, _ = _run(knowledge.search_nhtsa, "Ford", "F-150", "2016")
    assert [r["odiNumber"] for r in results] == [0]


def test_non_400_error_degrades_to_empty_without_model_lookup():
    results, calls = _run(knowledge.search_nhtsa, "Ford", "SERVER-ERROR", "2015")
    assert results == []
    assert not any("products/vehicle/models" in url for url, _ in calls)


def test_model_list_failure_is_an_error_not_an_absence(capsys):
    async def failing_list(self, url, params=None, **kw):
        if "products/vehicle/models" in url:
            return FakeResponse(500, {"message": "err"})
        return FakeResponse(400, {"count": 0, "results": []})
    with patch("httpx.AsyncClient.get", failing_list):
        assert asyncio.run(knowledge.search_nhtsa("Ford", "F-150", "2015")) == []
    assert "NHTSA search error" in capsys.readouterr().out


def test_empty_model_matches_nothing():
    results, _ = _run(knowledge.search_nhtsa, "Ford", "", "2017")
    assert results == []
