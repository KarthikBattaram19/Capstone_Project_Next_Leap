from datetime import date

from scout.domain.constraints import ConstraintSet
from scout.domain.listing import BhkType, Coordinates, Listing, ListingRecord, Parking
from scout.engines.shortlist import build, refine


def L(
    id,
    locality="Koramangala",
    rent=30000,
    bhk=BhkType.BHK2,
    parking=Parking.BOTH,
    deposit=60000,
    lift=True,
):
    return Listing.from_record(
        ListingRecord(
            id=id,
            source_url="u",
            scraped_on=date(2026, 9, 1),
            locality=locality,
            rent=rent,
            bhk_type=bhk,
            parking=parking,
            deposit=deposit,
            lift=lift,
            availability_status=True,
            coordinates=Coordinates(lat=12.9, lng=77.6),
        )
    )


# Every listing here clears both soft checks (lift, and a deposit within three months'
# rent), so soft hits tie and rent decides the order — which is what these cases are about.
ALL = {
    "a": L("a", rent=30000),
    "b": L("b", rent=38000),
    "c": L("c", rent=45000),
    "d": L("d", rent=32000, parking=None),
    "e": L("e", locality="HSR Layout", rent=28000),
}

AVAIL = lambda lid: True


def test_three_groups():
    c = ConstraintSet(
        localities=("Koramangala",), rent_max=40000, parking_required=Parking.FOUR_WHEELER
    )
    s = build(list(ALL.values()), c, AVAIL)
    assert s.order == ["a", "b"]  # rent asc, both parking BOTH
    assert s.unknown == {"parking_required": ("d",)}  # null never satisfies, never dropped
    assert {x.listing_id: x.field for x in s.excluded} == {"c": "rent_max", "e": "localities"}


def test_null_on_a_must_have_is_unknown_not_a_match():
    s = build([ALL["d"]], ConstraintSet(parking_required=Parking.TWO_WHEELER), AVAIL)
    assert s.order == []
    assert s.unknown["parking_required"] == ("d",)


def test_refine_keeps_untouched_order_and_appends_new():
    c1 = ConstraintSet(localities=("Koramangala",), rent_max=50000)
    s1 = build(list(ALL.values()), c1, AVAIL)  # a, d, b, c — rent asc
    assert s1.order == ["a", "d", "b", "c"]

    c2 = c1.with_(rent_max=40000)  # "drop anything above 40k"
    s2 = refine(s1, list(ALL.values()), c2, AVAIL)
    assert s2.order == ["a", "d", "b"]  # c gone; the rest untouched, same order

    c3 = c2.with_(localities=("Koramangala", "HSR Layout"))  # "add HSR Layout"
    s3 = refine(s2, list(ALL.values()), c3, AVAIL)
    assert s3.order == ["a", "d", "b", "e"]  # e appended, not re-sorted into the middle


def test_more_soft_matches_outrank_a_lower_rent():
    # The stated rank is (-soft_hits, rent asc with null last, id): a cheaper listing with
    # no lift and a four-month deposit sits below a dearer one that clears both.
    cheap_but_poor = L("p", rent=20000, deposit=200000, lift=None)
    dearer_but_good = L("q", rent=30000, deposit=60000, lift=True)
    s = build([cheap_but_poor, dearer_but_good], ConstraintSet(), AVAIL)
    assert s.order == ["q", "p"]


def test_unavailable_is_excluded_with_the_reason():
    s = build([ALL["a"]], ConstraintSet(), lambda lid: False)
    assert s.excluded[0].reason == "no longer available"
    assert s.excluded[0].field == "availability"


def test_nearby_localities_are_the_closest_centres_not_the_first_names_alphabetically():
    """Production, 2026-09-17: an empty result in Indiranagar suggested "nearby 6th Block /
    A Adugodi" - the first two covered names in alphabetical order, stated as geography."""
    from scout.engines.shortlist import nearest_localities

    places = {
        "6th Block": {"lat": 13.10, "lng": 77.40},
        "A Adugodi": {"lat": 12.94, "lng": 77.61},
        "Indiranagar": {"lat": 12.971, "lng": 77.641},
        "Domlur": {"lat": 12.961, "lng": 77.638},
        "HAL 2nd Stage": {"lat": 12.965, "lng": 77.650},
        "Whitefield": {"lat": 12.970, "lng": 77.750},
    }
    covered = sorted(places)
    assert nearest_localities(["Indiranagar"], places, covered, k=2) == ["Domlur", "HAL 2nd Stage"]
    assert nearest_localities(["Nowhere"], places, covered, k=2) == [], "no centre, no claim"
    assert nearest_localities(["Indiranagar"], places, ["Indiranagar", "Whitefield"], k=2) == [
        "Whitefield"
    ], "only covered localities are offered"


def test_a_locality_relaxation_is_only_suggested_from_computed_neighbours():
    from scout.domain.shortlist import Exclusion, Shortlist
    from scout.engines.shortlist import suggest_relaxations

    s = Shortlist(excluded=(Exclusion("x", "locality HSR Layout", "localities"),))
    c = ConstraintSet(localities=("Indiranagar",))
    assert suggest_relaxations(s, c, nearby=["Domlur"]) == ["look nearby in Domlur"]
    assert suggest_relaxations(s, c, nearby=[]) == [], "never name a place as nearby unmeasured"


def test_nearby_names_each_place_once_and_never_another_spelling_of_the_chosen_one():
    """Production, 2026-09-17: "nearby Austin Town / Domluru" - and Domlur/Domluru are one
    place, so a search in Domlur must not offer Domluru as nearby, nor offer it twice."""
    from scout.engines.shortlist import nearest_localities

    places = {
        "Domlur": {"lat": 12.961, "lng": 77.638},
        "Domluru": {"lat": 12.9611, "lng": 77.6381},
        "T.C Palya": {"lat": 12.962, "lng": 77.639},
        "TC Palya": {"lat": 12.9621, "lng": 77.6391},
        "Indiranagar": {"lat": 12.971, "lng": 77.641},
        "Whitefield": {"lat": 12.970, "lng": 77.750},
    }
    covered = sorted(places)
    assert nearest_localities(["Domlur"], places, covered, k=2) == ["TC Palya", "Indiranagar"]


def test_a_not_stated_detail_is_offered_in_plain_words():
    """Production, 2026-09-17: "or include the listings where that detail is not stated"."""
    from scout.domain.shortlist import Shortlist
    from scout.engines.shortlist import suggest_relaxations

    s = Shortlist(unknown={"amenities_required": ("x", "y")})
    c = ConstraintSet(localities=("TC Palya",), amenities_required=frozenset({"hospital"}))
    tips = suggest_relaxations(s, c, nearby=[], not_stated={"amenities_required": 2})
    assert tips == ["leave out hospital - 2 listings there don't mention it"]
    assert suggest_relaxations(s, c, nearby=[]) == [], "offered only when it would show some"


def test_parking_is_read_from_whether_parking_is_available():
    """E2: `parking` (the kind) is null on all 2,370 listings; `parking_available` is set on
    every one. Reading only the kind matched no listing for any parking requirement."""
    from dataclasses import replace

    def with_available(id, available):
        listing = L(id, parking=None)
        facts = dict(listing.facts)
        facts["parking_available"] = replace(facts["parking_available"], value=available)
        return replace(listing, facts=facts)

    yes, no, unsaid = with_available("y", True), with_available("n", False), L("u", parking=None)
    for need in (True, Parking.FOUR_WHEELER):
        s = build([yes, no, unsaid], ConstraintSet(parking_required=need), AVAIL)
        assert s.order == ["y"], need
        assert s.unknown == {"parking_required": ("u",)}, need
        assert [(x.listing_id, x.field) for x in s.excluded] == [("n", "parking_required")]
    no_need = build([yes, no], ConstraintSet(parking_required=False), AVAIL)
    assert set(no_need.order) == {"y", "n"}, "parking not needed constrains nothing"
