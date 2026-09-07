"""The case files and the slice agree: shapes, ids, and the probe phrases. No orchestrator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.conftest import FIXTURES, load_cases

EXPECT_KEYS = {
    "listing_id",
    "commute_method",
    "row",
    "spoken_contains",
    "gaps_declared",
    "your_commute_absent",
    "must_not_mention",
    "kind",
}
CASES_C = load_cases("c")


def _json(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_suite_c_has_its_first_five_cases_with_the_four_keys():
    assert [c["id"] for c in CASES_C] == ["c-001", "c-002", "c-003", "c-004", "c-005"]
    for case in CASES_C:
        assert set(case) - {"note"} == {"id", "locality", "turns", "expect"}, case["id"]
        assert case["turns"] and all(isinstance(t, str) for t in case["turns"]), case["id"]
        assert set(case["expect"]) <= EXPECT_KEYS, f"{case['id']}: unknown expect key"


def test_case_files_are_named_after_their_ids():
    for p in sorted((Path(__file__).parent / "c").glob("*.json")):
        assert json.loads(p.read_text(encoding="utf-8"))["id"] == p.stem


@pytest.mark.parametrize("case", CASES_C, ids=[c["id"] for c in CASES_C])
def test_expected_listing_is_in_the_case_locality(case):
    listings = {r["id"]: r for r in _json("listings.json")}
    lid = case["expect"].get("listing_id")
    if lid:
        assert listings[lid]["locality"] == case["locality"]


def test_c001_expects_the_cheapest_two_bhk_under_forty_thousand():
    cands = sorted(
        (r["rent"], r["id"])
        for r in _json("listings.json")
        if r["locality"] == "Koramangala" and r["bhk_type"] == "2BHK" and r["rent"] <= 40000
    )
    assert cands[0][1] == CASES_C[0]["expect"]["listing_id"]


def test_c002_listing_has_a_null_metro_row():
    lid = CASES_C[1]["expect"]["listing_id"]
    row = next(
        r
        for r in _json("osm_facts.json")
        if r["listing_id"] == lid and r["query"] == "nearest_metro"
    )
    assert row["distance_m"] is None and row["method"] is None


def test_c004_injection_chunk_is_in_the_slice_and_only_there():
    chunks = _json("chunks.json")
    bait = [c for c in chunks if "ignore previous instructions" in c["text"].lower()]
    assert [c["id"] for c in bait] == ["koramangala-9-0"]
    assert bait[0]["locality"] == "Koramangala" and bait[0]["url"] == "fixture://injection"


def test_c005_phrases_are_koramangala_only():
    chunks = _json("chunks.json")
    for phrase in CASES_C[4]["expect"]["must_not_mention"]:
        p = phrase.lower()
        assert any(p in c["text"].lower() for c in chunks if c["locality"] == "Koramangala"), phrase
        assert not any(p in c["text"].lower() for c in chunks if c["locality"] == "HSR Layout"), (
            phrase
        )
