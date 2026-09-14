"""The three assertion modules, exercised on hand-built view-models — no orchestrator needed."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from scout.contract.viewmodels import (
    CardVM,
    CitationVM,
    ClaimVM,
    CommuteRowVM,
    ExplanationVM,
    LocalityGroupVM,
    ShortlistVM,
)

from evals.assertions.commute import assert_three_layers_agree, assert_your_commute_absent
from evals.assertions.grounding import (
    _supports,
    assert_every_claim_cites,
    assert_explanation_was_produced,
)
from evals.assertions.order import assert_untouched_identical

ROUTED_LABEL = "[OSM routing — precomputed 2026-09-07]"
STRAIGHT_LABEL = "[Straight-line — computed live]"


def row(what: str, method: str, **over) -> CommuteRowVM:
    base = {
        "ROUTED": {"value_text": "1.1 km", "badge": "by route", "full_label": ROUTED_LABEL},
        "STRAIGHT_LINE": {
            "value_text": "4.2 km",
            "badge": "straight-line",
            "full_label": STRAIGHT_LABEL,
        },
        "NULL": {"value_text": "not stated", "badge": "", "full_label": ""},
    }[method]
    spoken = {
        "ROUTED": f"{what} 1.1 km away by route",
        "STRAIGHT_LINE": f"{what} 4.2 km in a straight line; road distance will be longer",
        "NULL": f"{what} distance not stated",
    }[method]
    return CommuteRowVM(**{"what": what, "spoken": spoken, **base, **over})


def card(listing_id: str = "kor-001", rank: int = 1, transit=None, your_commute=None) -> CardVM:
    return CardVM(
        listing_id=listing_id,
        rank=rank,
        locality="Koramangala",
        society_name="Sobha Iris",
        rent="₹26,000",
        deposit="not stated",
        maintenance="not stated",
        bhk_type="2BHK",
        square_footage="1100 sq ft (carpet)",
        floor="not stated",
        parking="not stated",
        furnishing="semi-furnished",
        amenities=[],
        available_from="not stated",
        transit=transit or row("Metro", "ROUTED"),
        your_commute=your_commute,
    )


def explanation(opener: str, claims: list[ClaimVM], sources: list[CitationVM], gaps=()):
    return ExplanationVM(
        listing_id="kor-001", opener=opener, claims=claims, gaps=list(gaps), sources=sources
    )


# ---------------------------------------------------------------- commute


def test_three_layers_agree_passes_when_all_three_name_the_route():
    exp = explanation(
        "The metro is 1.1 km away by route.",
        [ClaimVM(text="Metro 1.1 km by route", citation_refs=["osm:kor-001:nearest_metro"])],
        [CitationVM(ref="osm:kor-001:nearest_metro", label=ROUTED_LABEL)],
    )
    assert_three_layers_agree(card(), exp, "ROUTED")


def test_three_layers_agree_fails_when_badge_says_the_other_method():
    c = card(transit=row("Metro", "ROUTED", badge="straight-line"))
    with pytest.raises(AssertionError, match="badge 'straight-line' != 'by route'"):
        assert_three_layers_agree(c, None, "ROUTED")


def test_three_layers_agree_fails_when_the_full_label_is_a_bare_osm_tag():
    c = card(transit=row("Metro", "ROUTED", full_label="[OSM]"))
    with pytest.raises(AssertionError, match="does not resolve to method \\+ timing"):
        assert_three_layers_agree(c, None, "ROUTED")


def test_three_layers_agree_fails_when_speech_names_the_other_method():
    exp = explanation("It is about 1.1 km in a straight line.", [], [])
    with pytest.raises(AssertionError, match="names the OTHER method"):
        assert_three_layers_agree(card(), exp, "ROUTED")


def test_three_layers_agree_fails_when_the_explanation_never_names_the_method():
    exp = explanation("It is 1.1 km away.", [], [])
    with pytest.raises(AssertionError, match="explanation never says 'by route'"):
        assert_three_layers_agree(card(), exp, "ROUTED")


def test_straight_line_work_row_needs_the_caveat_in_the_same_breath():
    ok = card(your_commute=row("Work", "STRAIGHT_LINE"))
    assert_three_layers_agree(ok, None, "STRAIGHT_LINE", row="your_commute")
    bad = card(your_commute=row("Work", "STRAIGHT_LINE", spoken="Work 4.2 km straight-line"))
    with pytest.raises(AssertionError, match="caveat missing"):
        assert_three_layers_agree(bad, None, "STRAIGHT_LINE", row="your_commute")


def test_not_stated_row_must_carry_no_badge_and_nothing_else_is_checked():
    assert_three_layers_agree(card(transit=row("Metro", "NULL")), None, "ROUTED")
    with pytest.raises(AssertionError, match="'not stated' row must carry no badge"):
        assert_three_layers_agree(
            card(transit=row("Metro", "NULL", badge="by route")), None, "ROUTED"
        )


def test_missing_row_is_named():
    with pytest.raises(AssertionError, match="has no your_commute row"):
        assert_three_layers_agree(card(), None, "ROUTED", row="your_commute")


def test_your_commute_absent():
    assert_your_commute_absent(card())
    with pytest.raises(AssertionError, match="absent, not empty"):
        assert_your_commute_absent(card(your_commute=row("Work", "ROUTED")))


# ---------------------------------------------------------------- order


def shortlist(cards: list[CardVM]) -> ShortlistVM:
    return ShortlistVM(
        order=[c.listing_id for c in cards],
        groups=[LocalityGroupVM(locality="Koramangala", count=len(cards), cards=cards)],
    )


def test_untouched_identical_accepts_a_rerank_that_changes_only_rank():
    before = shortlist([card("a", 1), card("b", 2), card("c", 3)])
    after = shortlist([card("a", 1), card("c", 2)])  # b removed; a and c keep their order
    assert_untouched_identical(before, after, touched={"b"})


def test_untouched_identical_detects_a_changed_untouched_card():
    before = shortlist([card("a", 1), card("b", 2)])
    after = shortlist([card("a", 1), card("b", 2, transit=row("Metro", "STRAIGHT_LINE"))])
    with pytest.raises(AssertionError, match="listing b changed although it was not mentioned"):
        assert_untouched_identical(before, after, touched=set())


def test_untouched_identical_detects_a_reordering():
    before = shortlist([card("a", 1), card("b", 2), card("c", 3)])
    after = shortlist([card("c", 1), card("a", 2), card("b", 3)])
    with pytest.raises(AssertionError, match="relative order of untouched listings changed"):
        assert_untouched_identical(before, after, touched=set())


# ---------------------------------------------------------------- grounding

KOR_TEXT = (
    "Koramangala is divided into eight blocks spread over approximately 1,800 acres. "
    "Blocks 1-4 are separated from blocks 5-8 by the Inner Ring Road."
)
HSR_TEXT = "HSR Layout is divided into seven sectors which have main roads and cross roads."


def fake_store():
    chunks = {
        "koramangala-0-1": SimpleNamespace(locality="Koramangala", text=KOR_TEXT),
        "hsr-layout-0-2": SimpleNamespace(locality="HSR Layout", text=HSR_TEXT),
    }
    listings = {
        "kor-001": SimpleNamespace(locality="Koramangala"),
        "hsr-001": SimpleNamespace(locality="HSR Layout"),
    }
    return SimpleNamespace(chunks=chunks, listings=listings)


def test_supports_passes_on_a_shared_three_word_run_or_on_content_words():
    assert _supports("The locality is divided into eight blocks.", KOR_TEXT)  # verbatim run
    assert _supports("Eight blocks over roughly 1,800 acres.", KOR_TEXT)  # paraphrase
    assert not _supports("There is a large lake with boating.", KOR_TEXT)


def test_grounding_accepts_a_supported_same_locality_claim():
    exp = explanation(
        "Here is the area.",
        [
            ClaimVM(
                text="The area is laid out in eight blocks.",
                citation_refs=["guide:koramangala-0-1"],
            ),
            ClaimVM(
                text="The metro is 4.6 km by route.", citation_refs=["osm:kor-001:nearest_metro"]
            ),
        ],
        [
            CitationVM(ref="guide:koramangala-0-1", label="[Wikipedia — Koramangala]"),
            CitationVM(ref="osm:kor-001:nearest_metro", label=ROUTED_LABEL),
        ],
    )
    assert_every_claim_cites(exp, fake_store(), "Koramangala")


def test_grounding_rejects_a_cross_locality_guide_citation():
    exp = explanation(
        "Here is the area.",
        [ClaimVM(text="It is divided into seven sectors.", citation_refs=["guide:hsr-layout-0-2"])],
        [CitationVM(ref="guide:hsr-layout-0-2", label="[Wikipedia — HSR Layout]")],
    )
    with pytest.raises(AssertionError, match="cross-locality citation"):
        assert_every_claim_cites(exp, fake_store(), "Koramangala")


def test_grounding_rejects_a_cross_locality_osm_citation():
    exp = explanation(
        "Here is the area.",
        [
            ClaimVM(
                text="The metro is 1.7 km by route.", citation_refs=["osm:hsr-001:nearest_metro"]
            )
        ],
        [CitationVM(ref="osm:hsr-001:nearest_metro", label=ROUTED_LABEL)],
    )
    with pytest.raises(AssertionError, match="cross-locality citation osm:hsr-001"):
        assert_every_claim_cites(exp, fake_store(), "Koramangala")


def test_grounding_rejects_an_uncited_claim_and_an_unsupported_one():
    store = fake_store()
    uncited = explanation("x", [ClaimVM(text="Great schools nearby.", citation_refs=[])], [])
    with pytest.raises(AssertionError, match="uncited claim reached the renter"):
        assert_every_claim_cites(uncited, store, "Koramangala")
    unsupported = explanation(
        "x",
        [
            ClaimVM(
                text="There is a large lake with boating.",
                citation_refs=["guide:koramangala-0-1"],
            )
        ],
        [CitationVM(ref="guide:koramangala-0-1", label="[Wikipedia — Koramangala]")],
    )
    with pytest.raises(AssertionError, match="does not support the claim"):
        assert_every_claim_cites(unsupported, store, "Koramangala")


def test_grounding_rejects_a_bare_osm_label():
    exp = explanation(
        "x",
        [
            ClaimVM(
                text="The metro is 4.6 km by route.", citation_refs=["osm:kor-001:nearest_metro"]
            )
        ],
        [CitationVM(ref="osm:kor-001:nearest_metro", label="[OSM]")],
    )
    with pytest.raises(AssertionError, match="bare \\[OSM\\] citation"):
        assert_every_claim_cites(exp, fake_store(), "Koramangala")


def test_grounding_rejects_a_ref_missing_from_sources_and_an_unknown_kind():
    store = fake_store()
    not_in_sources = explanation(
        "x", [ClaimVM(text="Eight blocks.", citation_refs=["guide:koramangala-0-1"])], []
    )
    with pytest.raises(AssertionError, match="not in Sources"):
        assert_every_claim_cites(not_in_sources, store, "Koramangala")
    unknown = explanation(
        "x",
        [ClaimVM(text="Eight blocks.", citation_refs=["web:somewhere"])],
        [CitationVM(ref="web:somewhere", label="[web]")],
    )
    with pytest.raises(AssertionError, match="unknown citation kind"):
        assert_every_claim_cites(unknown, store, "Koramangala")


# --- the hole the 2026-09-10 pass fell through -------------------------------------------


def test_a_case_needing_an_explanation_fails_when_none_was_produced():
    # Suite C used to guard its whole grounding block with `if vm.explanation is not None`,
    # so five cases asserting gaps and contamination passed without an explanation existing.
    with pytest.raises(AssertionError) as e:
        assert_explanation_was_produced(None, {"must_not_mention": ["Forum Mall"]}, "c-019")
    assert "c-019" in str(e.value) and "must_not_mention" in str(e.value)


def test_a_case_with_no_explanation_expectations_is_allowed_to_have_none():
    # Commute cases assert on the card, not on prose. They may legitimately answer in lane A.
    assert_explanation_was_produced(None, {"commute_method": "ROUTED"}, "c-001")


def test_an_explanation_that_exists_satisfies_the_check():
    assert_explanation_was_produced(object(), {"gaps_declared": ["deposit"]}, "c-008")


# --- the ref kind the 2026-09-15 pass met for the first time --------------------------------


def test_grounding_accepts_the_tenants_own_straight_line_commute_ref():
    # "computed:<listing>:straight_line" is the one place the straight-line method occurs
    # (Task 2.7). Job 2 first cited it on 2026-09-15 (c-013) and the kind table ended at
    # "osm", so a correct citation failed as "unknown citation kind".
    exp = explanation(
        "x",
        [
            ClaimVM(
                text="Your commute is 12.3 km in a straight line.",
                citation_refs=["computed:kor-001:straight_line"],
            )
        ],
        [CitationVM(ref="computed:kor-001:straight_line", label=STRAIGHT_LABEL)],
    )
    assert_every_claim_cites(exp, fake_store(), "Koramangala")


def test_grounding_rejects_a_cross_locality_computed_ref():
    exp = explanation(
        "x",
        [
            ClaimVM(
                text="Your commute is 12.3 km in a straight line.",
                citation_refs=["computed:hsr-001:straight_line"],
            )
        ],
        [CitationVM(ref="computed:hsr-001:straight_line", label=STRAIGHT_LABEL)],
    )
    with pytest.raises(AssertionError, match="cross-locality citation computed:hsr-001"):
        assert_every_claim_cites(exp, fake_store(), "Koramangala")


def test_an_unsupported_claim_names_the_chunk_and_every_ref_it_cited():
    exp = explanation(
        "x",
        [
            ClaimVM(
                text="There is a large lake with boating.",
                citation_refs=["guide:koramangala-0-1", "dataset:kor-001:rent"],
            )
        ],
        [
            CitationVM(ref="guide:koramangala-0-1", label="[Wikipedia — Koramangala]"),
            CitationVM(ref="dataset:kor-001:rent", label="[Listing]"),
        ],
    )
    with pytest.raises(AssertionError) as e:
        assert_every_claim_cites(exp, fake_store(), "Koramangala")
    msg = str(e.value)
    assert "guide:koramangala-0-1 does not support" in msg
    assert "dataset:kor-001:rent" in msg  # the other ref is in the message, for the diagnosis
