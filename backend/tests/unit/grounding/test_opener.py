from datetime import date

from scout.domain.listing import BhkType
from scout.domain.provenance import Distance, Method, Provenanced, Source, Timing
from scout.grounding.opener import build_opener
from scout.grounding.resolvers import FactBundle


def bundle(with_commute=False, metro=True) -> FactBundle:
    b = FactBundle(listing_id="a", locality="Koramangala")

    def P(v, **k):
        return Provenanced(v, Source.DATASET, Timing.PRECOMPUTED, as_of=date(2026, 9, 1), **k)

    b.facts["dataset:a:rent"] = P(35000, citation_ref="dataset:a:rent")
    b.facts["dataset:a:bhk_type"] = P(BhkType.BHK2, citation_ref="dataset:a:bhk_type")
    b.facts["dataset:a:deposit"] = P(None, citation_ref="dataset:a:deposit")
    b.facts["osm:a:nearest_metro"] = Provenanced(
        Distance(1100, 14) if metro else None,
        Source.OSM,
        Timing.PRECOMPUTED,
        method=Method.ROUTED if metro else None,
        as_of=date(2026, 9, 2),
        citation_ref="osm:a:nearest_metro",
    )
    if with_commute:
        b.facts["computed:a:straight_line"] = Provenanced(
            Distance(6000),
            Source.COMPUTED,
            Timing.LIVE,
            method=Method.STRAIGHT_LINE,
            citation_ref="computed:a:straight_line",
        )
    return b


def test_opener_is_built_from_facts_and_names_methods():
    o = build_opener(bundle(with_commute=True), "Whitefield")
    for fragment in (
        "₹35,000",
        "2BHK",
        "by route",
        "straight-line",
        "road distance will be longer",
    ):
        assert fragment in o, f"opener never says {fragment!r}: {o}"
    assert "deposit" not in o.lower(), "the opener stated a fact it does not have"


def test_opener_never_states_a_null_distance():
    o = build_opener(bundle(metro=False), None)
    assert "metro" not in o.lower() or "don't have" in o.lower()


def test_opener_never_ends_on_a_heading():
    """E1: "On the neighbourhood —" is said only before a neighbourhood claim, by lane B."""
    from scout.domain.guides import GuideChunk

    b = bundle()
    b.chunks.append(
        Provenanced(
            GuideChunk(
                id="koramangala-0-1",
                locality="Koramangala",
                title="Koramangala",
                url="https://en.wikipedia.org/wiki/Koramangala",
                text="A neighbourhood in south Bengaluru.",
                position=1,
                fetched_on=date(2026, 9, 2),
            ),
            Source.GUIDE,
            Timing.PRECOMPUTED,
            citation_ref="guide:koramangala-0-1",
        )
    )
    o = build_opener(b, None)
    assert not o.rstrip().endswith("—"), o
    assert "On the neighbourhood" not in o, o
