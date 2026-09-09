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
