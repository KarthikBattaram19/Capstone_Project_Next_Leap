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
