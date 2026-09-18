from datetime import date

from scout.conversation.job2 import Job2Sentence
from scout.domain.provenance import Provenanced, Source, Timing
from scout.grounding.assembler import ClaimAssembler
from scout.grounding.resolvers import FactBundle


def bundle() -> FactBundle:
    b = FactBundle(listing_id="a", locality="Koramangala")
    b.facts["dataset:a:rent"] = Provenanced(
        35000,
        Source.DATASET,
        Timing.PRECOMPUTED,
        as_of=date(2026, 9, 1),
        citation_ref="dataset:a:rent",
    )
    b.facts["dataset:a:deposit"] = Provenanced(
        None,
        Source.DATASET,
        Timing.PRECOMPUTED,
        as_of=date(2026, 9, 1),
        citation_ref="dataset:a:deposit",
    )
    return b


def test_sentence_with_resolvable_refs_is_kept():
    c = ClaimAssembler(bundle()).bind(Job2Sentence("Rent is ₹35,000 a month.", ["dataset:a:rent"]))
    assert c is not None and c.refs == ["dataset:a:rent"]


def test_sentence_citing_unknown_ref_is_dropped():
    assert (
        ClaimAssembler(bundle()).bind(Job2Sentence("The area is very safe.", ["guide:made-up"]))
        is None
    )


def test_uncited_sentence_is_dropped():
    assert ClaimAssembler(bundle()).bind(Job2Sentence("Everyone loves it here.", [])) is None


def test_sentence_asserting_a_value_for_a_gap_is_dropped():
    assert (
        ClaimAssembler(bundle()).bind(
            Job2Sentence("The deposit is ₹1,00,000.", ["dataset:a:deposit"])
        )
        is None
    )


def test_sentence_denying_a_gap_is_kept():
    # Declaring a gap is a correct answer and must survive the assembler.
    assert (
        ClaimAssembler(bundle()).bind(
            Job2Sentence(
                "There is no deposit figure stated for this listing.", ["dataset:a:deposit"]
            )
        )
        is not None
    )


def test_gap_is_rendered_as_an_open_gap_line():
    lines = ClaimAssembler(bundle()).render_gaps()
    assert any("deposit" in line for line in lines)


def test_the_assembler_counts_what_it_drops_and_why():
    # JOB2_SCORES.md: the drop count is what says whether Job 2 is being fenced or is
    # simply writing uncitable prose. Silent drops cannot answer that question.
    a = ClaimAssembler(bundle())
    a.bind(Job2Sentence("Everyone loves it here.", []))
    a.bind(Job2Sentence("The area is very safe.", ["guide:made-up"]))
    a.bind(Job2Sentence("The deposit is ₹1,00,000.", ["dataset:a:deposit"]))

    assert a.drops == {"no_refs": 1, "unknown_ref": 1, "gap_assertion": 1, "unsupported": 0}
    assert a.dropped == 3
    assert a.bound == 0


def test_a_bound_sentence_is_counted_as_bound_not_dropped():
    a = ClaimAssembler(bundle())
    a.bind(Job2Sentence("Rent is ₹35,000 a month.", ["dataset:a:rent"]))

    assert a.dropped == 0
    assert a.bound == 1
    assert a.drops == {"no_refs": 0, "unknown_ref": 0, "gap_assertion": 0, "unsupported": 0}


def bundle_with_a_chunk() -> FactBundle:
    from scout.domain.guides import GuideChunk

    b = bundle()
    b.chunks.append(
        Provenanced(
            GuideChunk(
                id="koramangala-0-1",
                locality="Koramangala",
                title="Koramangala",
                url="fixture://guide",
                text="Blocks 1-4 are separated from blocks 5-8 by the Inner Ring Road.",
                position=1,
                fetched_on=date(2026, 9, 7),
            ),
            Source.GUIDE,
            Timing.PRECOMPUTED,
            as_of=date(2026, 9, 7),
            citation_ref="guide:koramangala-0-1",
        )
    )
    return b


def test_a_sentence_about_what_the_documents_do_not_say_is_dropped_as_a_gap():
    # c-018, 2026-09-15: a gap spoken as prose, citing two passages that say nothing of it.
    a = ClaimAssembler(bundle_with_a_chunk())
    for text in (
        (
            "The neighbourhood guides themselves don't actually discuss deposit amounts at all, "
            "they focus on the area's blocks, traffic and distances."
        ),
        "The guide does not mention a deposit.",
        "These documents never say anything about parking.",
        "The source is not specific about the maintenance charge.",
    ):
        assert a.bind(Job2Sentence(text, ["guide:koramangala-0-1"])) is None, text
    assert a.drops["gap_assertion"] == 4 and a.bound == 0


def test_a_sentence_restating_a_passage_still_binds_when_it_contains_a_denial():
    a = ClaimAssembler(bundle_with_a_chunk())
    kept = a.bind(
        Job2Sentence(
            "The guide says blocks 1-4 are separated from blocks 5-8 by the Inner Ring Road, "
            "not by the Outer Ring Road.",
            ["guide:koramangala-0-1"],
        )
    )
    assert kept is not None and a.bound == 1


def test_a_sentence_whose_cited_passage_does_not_support_it_is_dropped():
    # c-008, twice on 2026-09-15: the words of one HSR Layout passage, the ref of another.
    a = ClaimAssembler(bundle_with_a_chunk())
    assert (
        a.bind(
            Job2Sentence(
                "HSR Layout is home to several small parks maintained by BBMP.",
                ["guide:koramangala-0-1"],
            )
        )
        is None
    )
    assert a.drops["unsupported"] == 1 and a.bound == 0


def test_a_paraphrase_of_the_cited_passage_binds():
    a = ClaimAssembler(bundle_with_a_chunk())
    kept = a.bind(
        Job2Sentence(
            "The Inner Ring Road separates blocks 1-4 from blocks 5-8.",
            ["guide:koramangala-0-1"],
        )
    )
    assert kept is not None and a.drops["unsupported"] == 0


# --- §6 walkthrough rows: guards that were read but not executed (Task 4.2) ---

DISCLAIMER = "Limited neighbourhood data available for this locality."


def test_a_locality_with_no_guide_chunks_carries_the_limited_data_disclaimer():
    """Spec §6.2 - partial info plus the disclaimer, never partial info alone. This is the
    common case, not an edge one: 337 of the 464 localities have no guide source at all,
    so the line has to fire on an empty chunk list rather than on a retrieval failure."""
    b = bundle()
    assert not b.chunks

    lines = ClaimAssembler(b).render_gaps()

    assert DISCLAIMER in lines
    # It is additional to the per-fact gaps, not a replacement for them: the missing
    # deposit is still declared in its own line.
    assert any("deposit" in ln for ln in lines)


def test_the_disclaimer_is_absent_when_the_locality_does_have_a_guide_chunk():
    """The other half of §6.2: a disclaimer that always appeared would say nothing."""
    assert DISCLAIMER not in ClaimAssembler(bundle_with_a_chunk()).render_gaps()


def _nulls(b: FactBundle, *names: str) -> FactBundle:
    for n in names:
        ref = f"dataset:a:{n}"
        b.facts[ref] = Provenanced(
            None, Source.DATASET, Timing.PRECOMPUTED, as_of=date(2026, 9, 1), citation_ref=ref
        )
    return b


def test_maintenance_is_one_gap_not_two():
    """E1: "I don't have a maintenance charge figure ... I don't have a maintenance figure"."""
    lines = ClaimAssembler(
        _nulls(bundle(), "maintenance_charges", "maintenance_included")
    ).render_gaps()
    assert sum("maintenance" in ln for ln in lines) == 1, lines


def test_job2_gaps_in_field_names_become_words_and_are_not_repeated():
    a = ClaimAssembler(_nulls(bundle(), "maintenance_charges", "maintenance_included", "lift"))
    lines = a.all_gaps(["maintenance_charges", "dataset:a:lift", "restaurants_within_500m", "lift"])
    assert all("_" not in ln for ln in lines), lines
    assert sum("maintenance" in ln for ln in lines) == 1, lines
    assert sum("lift" in ln for ln in lines) == 1, lines
    assert any("restaurants" in ln for ln in lines), lines


def test_the_spoken_gap_summary_is_one_sentence_naming_at_most_two():
    a = ClaimAssembler(_nulls(bundle(), "maintenance_charges", "maintenance_included", "parking"))
    line = a.gap_summary("why this one?")
    assert line == "I don't have some details for this listing, like the deposit and maintenance."
    assert a.gap_summary("is there a lift?", extra=["lift"]).startswith(
        "I don't have some details for this listing, like the lift"
    )
    assert ClaimAssembler(FactBundle(listing_id="a", locality="K")).gap_summary("why?") is None


def test_a_raw_field_name_is_never_speakable():
    from scout.grounding.assembler import speakable

    assert not speakable("maintenance_charges maintenance_included parking lift")
    assert speakable("It's ₹42,000 a month.")


def test_nothing_bound_names_what_is_held_and_never_offers_a_gap():
    """0 bound: the renter heard only the opener on production (2026-09-18).

    The offer is built from facts the listing actually has a value for. A field that is
    null is a gap, and offering to tell her a gap would be inventing.
    """
    b = bundle()  # rent 35,000 (the opener already said it), deposit null
    for name, value in (("bedrooms", 2), ("square_footage", 950)):
        ref = f"dataset:a:{name}"
        b.facts[ref] = Provenanced(
            value, Source.DATASET, Timing.PRECOMPUTED, as_of=date(2026, 9, 1), citation_ref=ref
        )
    line = ClaimAssembler(b).nothing_bound_line("is there a lift?")

    assert "couldn't answer" in line, line
    assert "size" in line, line  # square_footage, in words
    assert "deposit" not in line, line  # null: it is a gap, not an offer
    assert "rent" not in line, line  # the opener already said it
    assert "bedrooms" not in line, line  # the opener's "2BHK" restated
    assert "_" not in line, line  # E1: never a raw field name
    assert len(line.split()) <= 30, line


def test_nothing_bound_with_nothing_to_offer_still_offers_a_search():
    line = ClaimAssembler(FactBundle(listing_id="a", locality="K")).nothing_bound_line("why?")

    assert "couldn't answer" in line and "search" in line, line
