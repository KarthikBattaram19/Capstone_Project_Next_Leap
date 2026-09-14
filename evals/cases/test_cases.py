"""The case files and the slice agree: shapes, ids, and the probe phrases. No orchestrator."""

from __future__ import annotations

import json
import re
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
    "must_not_match",
    "kind",
}
CASES_C = load_cases("c")


def _json(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_suite_c_has_twenty_cases_with_known_keys():
    assert [c["id"] for c in CASES_C] == [f"c-{n:03d}" for n in range(1, 21)]
    for case in CASES_C:
        assert set(case) - {"note"} == {"id", "locality", "turns", "expect"}, case["id"]
        assert case["turns"] and all(isinstance(t, str) for t in case["turns"]), case["id"]
        assert set(case["expect"]) <= EXPECT_KEYS, f"{case['id']}: unknown expect key"


def test_case_files_are_named_after_their_ids():
    for suite in ("a", "b", "c"):
        for p in sorted((Path(__file__).parent / suite).glob("*.json")):
            assert json.loads(p.read_text(encoding="utf-8"))["id"] == p.stem


A_KEYS = {
    "kind",
    "readback_contains",
    "extracted",
    "all_matched_satisfy",
    "matched_ids",
    "unknown_ids",
    "excluded_ids",
    "unknown_field",
    "localities_span",
    "unmet_field",
    "suggestions_contain",
}
B_KEYS = {
    "kind",
    "extracted",
    "matched_ids",
    "excluded_ids",
    "appended_after",
    "suggestions_contain",
}


def test_suites_a_and_b_have_twenty_cases_each_with_known_keys():
    a, b = load_cases("a"), load_cases("b")
    assert [c["id"] for c in a] == [f"a-{n:03d}" for n in range(1, 21)]
    assert [c["id"] for c in b] == [f"b-{n:03d}" for n in range(1, 21)]
    for case in a:
        assert set(case) == {"id", "turns", "expect"}, case["id"]
        assert case["turns"] and all(isinstance(t, str) for t in case["turns"]), case["id"]
        assert set(case["expect"]) <= A_KEYS, f"{case['id']}: unknown expect key"
    for case in b:
        assert set(case) == {"id", "before_turns", "edit_turn", "expect"}, case["id"]
        # The readback is confirmed somewhere in the setup; b-016..b-019 then carry the
        # first of two sequential edits, so "yes" is not always the last turn.
        assert "yes" in case["before_turns"], f"{case['id']}: before_turns never confirm"
        assert set(case["expect"]) <= B_KEYS, f"{case['id']}: unknown expect key"


def test_every_named_listing_exists_in_the_slice():
    ids = {r["id"] for r in _json("listings.json")}
    for suite, keys in (
        ("a", ("matched_ids", "excluded_ids", "unknown_ids")),
        ("b", ("matched_ids", "excluded_ids", "appended_after")),
    ):
        for case in load_cases(suite):
            for key in keys:
                for lid in case["expect"].get(key, []):
                    assert lid in ids, f"{case['id']}: {lid} is not in the slice"


def test_contamination_phrases_belong_to_another_locality_only():
    """A must_not_mention phrase must not appear in the case's OWN locality's real chunks.

    Otherwise the probe is unpassable: a correct, well-cited answer could contain it. The
    injection chunk is exempt on purpose — an injection probe works precisely because the
    forbidden words ARE in the partition and must still never be repeated.
    """
    chunks = [c for c in _json("chunks.json") if c["url"] != "fixture://injection"]
    for case in CASES_C:
        for phrase in case["expect"].get("must_not_mention", []):
            p = phrase.lower()
            assert not any(
                p in c["text"].lower() for c in chunks if c["locality"] == case["locality"]
            ), f"{case['id']}: {phrase!r} is in its own locality's chunks"
        for pattern in case["expect"].get("must_not_match", []):
            assert not any(
                re.search(pattern, c["text"], re.IGNORECASE)
                for c in chunks
                if c["locality"] == case["locality"]
            ), f"{case['id']}: {pattern!r} matches its own locality's chunks"


def test_c008_forbids_the_shape_of_a_park_distance_and_not_a_denial():
    patterns = CASES_C[7]["expect"]["must_not_match"]

    def hit(text: str) -> bool:
        return any(re.search(p, text, re.IGNORECASE) for p in patterns)

    for invented in (
        "The nearest park is about 500 m away.",
        "There is a park within 300 metres.",
        "It is a 10-minute walk to the park.",
        "A five minutes' walk to a park.",
    ):
        assert hit(invented), invented
    for legitimate in (
        (
            "The distance to the nearest park isn't available for this property, though HSR "
            "Layout is described as home to several small and medium-sized parks maintained "
            "by BBMP."
        ),
        "The metro is 1.2 km by route, and no park is in the map data.",
        "This 2BHK is near Agara Lake park.",
    ):
        assert not hit(legitimate), legitimate


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
