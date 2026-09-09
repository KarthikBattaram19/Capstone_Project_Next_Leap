from datetime import date

from scout.domain.constraints import CommutePoint
from scout.domain.listing import Coordinates, Listing, ListingRecord
from scout.domain.osm import OsmFactRecord, OsmQuery
from scout.domain.provenance import Method, Source, Timing
from scout.engines.commute import CommuteService


class Store:
    def __init__(self):
        rec = ListingRecord(
            id="a",
            source_url="u",
            scraped_on=date(2026, 9, 1),
            locality="Koramangala",
            coordinates=Coordinates(lat=12.9352, lng=77.6245),
        )
        self.listings = {"a": Listing.from_record(rec)}
        self._rows = {
            ("a", OsmQuery.NEAREST_METRO): OsmFactRecord(
                listing_id="a",
                query=OsmQuery.NEAREST_METRO,
                name="M",
                distance_m=1100,
                duration_min=14,
                method=Method.ROUTED,
                retrieved_on=date(2026, 9, 2),
            ),
            ("a", OsmQuery.NEAREST_BUS_STOP): OsmFactRecord(
                listing_id="a",
                query=OsmQuery.NEAREST_BUS_STOP,
                retrieved_on=date(2026, 9, 2),
            ),
        }

    def osm(self, lid, q):
        return self._rows[(lid, q)]


def test_transit_reads_precomputed_with_method_and_date():
    f = CommuteService(Store()).transit("a")
    assert f.value.metres == 1100
    assert f.method is Method.ROUTED
    assert f.timing is Timing.PRECOMPUTED
    assert f.as_of == date(2026, 9, 2)
    assert f.citation_ref == "osm:a:nearest_metro"


def test_null_row_is_a_gap_with_osm_provenance():
    f = CommuteService(Store()).transit("a", OsmQuery.NEAREST_BUS_STOP)
    assert f.value is None
    assert f.source is Source.OSM


def test_to_point_is_live_straight_line_and_needs_no_network():
    f = CommuteService(Store()).to_point("a", CommutePoint("Whitefield", 12.9698, 77.7500))
    assert f.source is Source.COMPUTED
    assert f.method is Method.STRAIGHT_LINE
    assert f.timing is Timing.LIVE
    assert 13000 < f.value.metres < 15000
    assert f.value.minutes is None
