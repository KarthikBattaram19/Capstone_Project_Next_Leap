from datetime import date

from scout.domain.constraints import CommutePoint
from scout.domain.listing import BhkType, Coordinates, Listing, ListingRecord
from scout.domain.osm import OsmFactRecord, OsmQuery
from scout.domain.provenance import Method
from scout.domain.shortlist import Shortlist, ShortlistEntry
from scout.engines.commute import CommuteService
from scout.presentation.viewmodel import ViewModelBuilder


class Store:
    def __init__(self):
        a = ListingRecord(
            id="a",
            source_url="u",
            scraped_on=date(2026, 9, 1),
            locality="Koramangala",
            rent=35000,
            deposit=None,
            bhk_type=BhkType.BHK2,
            coordinates=Coordinates(lat=12.93, lng=77.62),
        )
        b = ListingRecord(
            id="b",
            source_url="u",
            scraped_on=date(2026, 9, 1),
            locality="HSR Layout",
            rent=28000,
            deposit=200000,
            maintenance_included=True,
            coordinates=Coordinates(lat=12.91, lng=77.64),
        )
        self.listings = {"a": Listing.from_record(a), "b": Listing.from_record(b)}
        self.listing_records = {"a": a, "b": b}
        self._rows = {
            (lid, q): OsmFactRecord(listing_id=lid, query=q, retrieved_on=date(2026, 9, 2))
            for lid in ("a", "b")
            for q in OsmQuery
        }
        self._rows[("a", OsmQuery.NEAREST_METRO)] = OsmFactRecord(
            listing_id="a",
            query=OsmQuery.NEAREST_METRO,
            name="M",
            distance_m=1100,
            duration_min=14,
            method=Method.ROUTED,
            retrieved_on=date(2026, 9, 2),
        )

    def osm(self, lid, q):
        return self._rows[(lid, q)]


def builder() -> ViewModelBuilder:
    s = Store()
    return ViewModelBuilder(s, CommuteService(s))


def test_null_reads_not_stated_never_zero_and_badge_never_dropped():
    card = builder().card("a", 1, None)
    assert card.deposit == "not stated"
    assert card.maintenance == "not stated"
    assert card.transit.value_text == "1.1 km"
    assert card.transit.badge == "by route"
    assert card.your_commute is None


def test_null_transit_row_reads_not_stated_with_no_badge():
    card = builder().card("b", 1, None)
    assert card.transit.value_text == "not stated"
    assert card.transit.badge == ""


def test_your_commute_row_is_straight_line_and_visually_distinct_label():
    card = builder().card("a", 1, CommutePoint("Whitefield", 12.9698, 77.75))
    assert card.your_commute.badge == "straight-line"
    assert "computed now" in card.your_commute.full_label


def test_grouping_never_reorders():
    sl = Shortlist(matched=(ShortlistEntry("b", 1), ShortlistEntry("a", 2)))
    vm = builder().shortlist(sl, None)
    assert vm.order == ["b", "a"]
    assert [g.locality for g in vm.groups] == ["HSR Layout", "Koramangala"]
    assert vm.groups[0].count == 1


def test_indian_number_grouping():
    assert builder().card("b", 1, None).deposit == "₹2,00,000"
