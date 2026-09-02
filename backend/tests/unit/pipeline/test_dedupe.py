from datetime import date

from scout.domain.listing import Coordinates, ListingRecord
from scout.pipeline.dedupe import dedupe


def rec(id, lat, lng, society=None, rent=None, deposit=None):
    return ListingRecord(
        id=id,
        source_url=f"u/{id}",
        scraped_on=date(2026, 9, 1),
        locality="Koramangala",
        coordinates=Coordinates(lat=lat, lng=lng),
        society_name=society,
        rent=rent,
        deposit=deposit,
    )


def test_within_50m_merges_and_most_detailed_wins():
    a = rec("a", 12.9350, 77.6200, rent=30000)  # 1 field
    b = rec("b", 12.9351, 77.6200, rent=30000, deposit=100000)  # 2 fields wins
    kept, merged = dedupe([a, b])
    assert [k.id for k in kept] == ["b"]
    assert merged == {"b": ["a"]}


def test_beyond_50m_stays_separate():
    a = rec("a", 12.9350, 77.6200)
    b = rec("b", 12.9360, 77.6200)  # ~110 m north
    kept, merged = dedupe([a, b])
    assert len(kept) == 2
    assert merged == {}


def test_exact_society_and_address_merges_without_coordinates():
    a = ListingRecord(
        id="a",
        source_url="u/a",
        scraped_on=date(2026, 9, 1),
        locality="X",
        society_name="Prestige Acropolis, 5th Block",
        rent=1,
    )
    b = ListingRecord(
        id="b",
        source_url="u/b",
        scraped_on=date(2026, 9, 1),
        locality="X",
        society_name="Prestige Acropolis, 5th Block",
        rent=1,
        deposit=2,
    )
    kept, _merged = dedupe([a, b])
    assert [k.id for k in kept] == ["b"]


def test_two_flats_in_one_tower_are_not_one_flat():
    # The same pin, the same building, different flats.
    a = rec("a", 12.9350, 77.6200, society="Prestige Acropolis", rent=30000)
    b = rec("b", 12.9350, 77.6200, society="Prestige Acropolis", rent=52000)
    kept, merged = dedupe([a, b])
    assert len(kept) == 2 and merged == {}


def test_same_society_in_two_localities_stays_separate():
    a = ListingRecord(
        id="a",
        source_url="u/a",
        scraped_on=date(2026, 9, 1),
        locality="Koramangala",
        society_name="Prestige Acropolis",
    )
    b = ListingRecord(
        id="b",
        source_url="u/b",
        scraped_on=date(2026, 9, 1),
        locality="HSR Layout",
        society_name="Prestige Acropolis",
    )
    assert len(dedupe([a, b])[0]) == 2
