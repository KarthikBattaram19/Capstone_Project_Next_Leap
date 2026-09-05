from datetime import date

import pytest

from scout.domain.osm import OSM_QUERY_SET, OsmFactRecord, OsmQuery
from scout.domain.provenance import Method


def test_a_distance_without_a_method_is_refused():
    # A number on a card must always be able to say how it was measured.
    with pytest.raises(ValueError, match="distance without method"):
        OsmFactRecord(
            listing_id="kor-001",
            query=OsmQuery.NEAREST_METRO,
            name="Koramangala",
            distance_m=850,
            retrieved_on=date(2026, 9, 2),
        )


def test_a_distance_with_a_method_is_accepted():
    fact = OsmFactRecord(
        listing_id="kor-001",
        query=OsmQuery.NEAREST_METRO,
        name="Koramangala",
        distance_m=850,
        method=Method.STRAIGHT_LINE,
        retrieved_on=date(2026, 9, 2),
    )
    assert fact.distance_m == 850 and fact.method is Method.STRAIGHT_LINE


def test_a_null_answer_needs_no_method():
    # OSM found nothing within the radius: the row still exists, with nulls.
    fact = OsmFactRecord(
        listing_id="kor-001",
        query=OsmQuery.NEAREST_PARK,
        retrieved_on=date(2026, 9, 2),
    )
    assert fact.distance_m is None and fact.name is None


def test_every_query_in_the_enum_has_exactly_one_spec():
    assert [s.query for s in OSM_QUERY_SET] == list(OsmQuery)
    for spec in OSM_QUERY_SET:
        assert spec.kind in {"nearest", "count"}
        assert spec.radius_m > 0 and spec.label
