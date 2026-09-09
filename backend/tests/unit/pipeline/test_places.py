from datetime import date

from scout.domain.listing import Coordinates, ListingRecord
from scout.pipeline.places import WORK_HUBS, build_places


def L(lid, locality, lat, lng):
    return ListingRecord(
        id=lid,
        source_url="u",
        scraped_on=date(2026, 9, 1),
        locality=locality,
        coordinates=Coordinates(lat=lat, lng=lng),
    )


def test_one_listing_in_the_wrong_place_does_not_move_the_locality():
    # The sheet's coordinates are not always right. The median holds; a mean would not.
    good = [L(f"k-{i}", "Koramangala", 12.935 + i / 10000, 77.625) for i in range(5)]
    stray = L("k-x", "Koramangala", 12.60, 77.20)  # ~50 km away
    places = build_places([*good, stray])
    assert 12.93 < places["Koramangala"]["lat"] < 12.94
    assert 77.62 < places["Koramangala"]["lng"] < 77.63


def test_a_sourced_work_hub_beats_a_computed_centre():
    # Whitefield has two listings in the real bundle and one of them is 22 km out, so its
    # computed centre landed in the middle of the city.
    places = build_places(
        [L("w-1", "Whitefield", 12.9698, 77.7499), L("w-2", "Whitefield", 12.9101, 77.5425)]
    )
    lat, lng = WORK_HUBS["Whitefield"]
    assert (places["Whitefield"]["lat"], places["Whitefield"]["lng"]) == (lat, lng)
    assert places["Whitefield"]["source"].startswith("https://www.openstreetmap.org/")


def test_every_hub_is_present_even_with_no_listings():
    places = build_places([])
    assert set(WORK_HUBS) <= set(places)


def test_a_listing_without_coordinates_is_skipped_not_counted():
    rec = ListingRecord(id="n-1", source_url="u", scraped_on=date(2026, 9, 1), locality="Nowhere")
    assert "Nowhere" not in build_places([rec])
