"""resolve_query against a faked MCP (routed, straight-line, the null row that still exists),
and the wrapper's own decisions against a faked MCP session."""

import json
from datetime import date

import pytest

from scout.domain.listing import Coordinates, ListingRecord
from scout.domain.osm import OSM_QUERY_SET, OsmQuery
from scout.domain.provenance import Method
from scout.pipeline import osm_mcp
from scout.pipeline.osm_mcp import OsmMcp, OsmUnavailable, category_expression
from scout.pipeline.precompute_osm import resolve_query


class FakeMcp:
    def __init__(self, places, route):
        self._places = places
        self._route = route

    async def find_nearby(self, lat, lng, category, radius_m):
        return self._places

    async def route(self, lat1, lng1, lat2, lng2, mode="foot"):
        return self._route


LISTING = ListingRecord(
    id="kor-001",
    source_url="u",
    scraped_on=date(2026, 9, 1),
    locality="Koramangala",
    coordinates=Coordinates(lat=12.935, lng=77.62),
)
METRO = next(q for q in OSM_QUERY_SET if q.query is OsmQuery.NEAREST_METRO)


async def test_routed_when_routing_succeeds():
    mcp = FakeMcp(
        [{"name": "Koramangala Metro", "lat": 12.94, "lng": 77.62}],
        {"distance_m": 1100, "duration_s": 840},
    )
    row = await resolve_query(mcp, LISTING, METRO, date(2026, 9, 2))
    assert row.distance_m == 1100
    assert row.method is Method.ROUTED
    # The public OSRM demo ignores the profile, so a routed duration would be a driving
    # time spoken as a walk; the distance is kept, the duration is not (see the module
    # comment in precompute_osm). The raw OSRM number stays in the sign-off record.
    assert row.duration_min is None
    assert row.raw["route"]["duration_s"] == 840


async def test_straight_line_when_routing_fails_and_says_so():
    mcp = FakeMcp([{"name": "X", "lat": 12.944, "lng": 77.62}], None)
    row = await resolve_query(mcp, LISTING, METRO, date(2026, 9, 2))
    assert row.method is Method.STRAIGHT_LINE
    assert 900 < row.distance_m < 1100
    assert row.duration_min is None


async def test_nothing_found_is_a_null_row_not_a_missing_row():
    row = await resolve_query(FakeMcp([], None), LISTING, METRO, date(2026, 9, 2))
    assert row.listing_id == "kor-001"
    assert row.query is OsmQuery.NEAREST_METRO
    assert row.distance_m is None
    assert row.method is None
    assert row.name is None


# --- the wrapper's own decisions, against a faked MCP session --------------------------------


class _Text:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Result:
    def __init__(self, text, is_error=False):
        self.content = [_Text(text)]
        self.is_error = is_error


class FakeSession:
    """Replays scripted CallToolResults; records every call it receives."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def call_tool(self, name, args, read_timeout_seconds=None):
        self.calls.append((name, args))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _mcp(replies, cache=None):
    m = OsmMcp(cache=cache, pause_s=0, retry_waits_s=(0, 0))
    m._session = FakeSession(replies)
    return m


def _place(name, lat, lng, **tags):
    tags = {**({"name": name} if name else {}), **tags}
    return {
        "id": 1,
        "type": "node",
        "name": name or "Unnamed",
        "coordinates": {"latitude": lat, "longitude": lng},
        "tags": tags,
    }


def test_category_expression_is_the_key_value_form_the_server_interpolates():
    assert category_expression("hospital") == 'amenity"="hospital'
    assert category_expression("subway_station") == 'railway"="station'


async def test_find_nearby_sends_the_expression_and_a_bbox_and_filters_to_the_circle():
    # 12.935/77.62 -> a point 1.9 km due north is inside the 2 km bbox but the corner is not.
    reply = {
        "results": [
            _place("Near", 12.9521, 77.62, amenity="hospital"),  # ~1.9 km north
            _place("Corner", 12.9521, 77.6375, amenity="hospital"),  # ~2.7 km, inside bbox
            _place(None, 12.936, 77.621, amenity="hospital"),  # Unnamed
            _place("Wrong value", 12.936, 77.62, amenity="clinic"),
        ]
    }
    m = _mcp([_Result(json.dumps(reply))])
    got = await m.find_nearby(12.935, 77.62, "hospital", 2000)
    name, args = m._session.calls[0]
    assert name == "search_category"
    assert args["category"] == 'amenity"="hospital'
    assert "subcategories" not in args
    assert args["min_latitude"] < 12.935 < args["max_latitude"]
    assert args["min_longitude"] < 77.62 < args["max_longitude"]
    assert [p["name"] for p in got] == ["Near", None]
    assert m.network_calls == 1


async def test_metro_keeps_namma_metro_and_drops_indian_railways_stations():
    reply = {
        "results": [
            _place("Bangalore Cantonment", 12.98, 77.61, railway="station", network="IR"),
            _place("Trinity", 12.973, 77.617, railway="station", station="subway", subway="yes"),
        ]
    }
    m = _mcp([_Result(json.dumps(reply))])
    got = await m.find_nearby(12.9755, 77.6068, "subway_station", 3000)
    assert [p["name"] for p in got] == ["Trinity"]


async def test_cache_hit_skips_the_network_and_a_miss_is_written_to_the_cache():
    cache = {}
    reply = {"results": [_place("A", 12.936, 77.62, amenity="pharmacy")]}
    m = _mcp([_Result(json.dumps(reply))], cache=cache)
    first = await m.find_nearby(12.935, 77.62, "pharmacy", 2000)
    again = await m.find_nearby(12.935, 77.62, "pharmacy", 2000)
    assert first == again == [{"name": "A", "lat": 12.936, "lng": 77.62}]
    assert m.network_calls == 1 and m.cache_hits == 1
    assert len(cache) == 1 and next(iter(cache.values())) == first


async def test_route_reads_the_nested_summary_and_no_route_is_none_not_a_retry():
    ok = {"summary": {"distance": 1099.6, "duration": 840.2, "mode": "foot"}, "directions": []}
    m = _mcp([_Result(json.dumps(ok))])
    assert await m.route(1, 2, 3, 4) == {"distance_m": 1100, "duration_s": 840}
    assert m._session.calls[0][1]["mode"] == "foot"

    m = _mcp([_Result("Error executing tool get_route_directions: No route found", True)])
    assert await m.route(1, 2, 3, 4) is None
    assert len(m._session.calls) == 1  # not retried


async def test_retries_then_raises_osm_unavailable_never_an_empty_answer():
    m = _mcp(
        [
            _Result("Error executing tool search_category: Failed ...: 504", True),
            RuntimeError("transport dropped"),
            _Result("Error executing tool search_category: Failed ...: 429", True),
        ]
    )
    with pytest.raises(OsmUnavailable):
        await m.find_nearby(12.935, 77.62, "hospital", 2000)
    assert len(m._session.calls) == 3  # one try per wait, plus the last
    assert m.network_calls == 0


def test_every_query_set_category_has_a_tag_mapping():
    assert set(osm_mcp.CATEGORY_TABLE) == {q.category for q in OSM_QUERY_SET}


# --- the manifest half ------------------------------------------------------------------------


def test_from_osm_adds_the_query_set_and_the_index_date_to_the_existing_manifest(
    tmp_path, monkeypatch
):
    from scout.domain.manifest import DatasetManifest
    from scout.pipeline import manifest as manifest_mod

    existing = DatasetManifest(
        bundle_version="1",
        contract_version="1",
        scraped_on=date(2026, 9, 1),
        localities={"Koramangala": 1},
        total_listings=1,
        availability_marker=None,
        curation_rule="r",
        fields_published=["rent"],
        fields_missing=[],
        chromadb_version="x",
    )
    path = tmp_path / "manifest.json"
    path.write_text(existing.model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setattr(manifest_mod, "MANIFEST", path)

    m = manifest_mod.from_osm(date(2026, 9, 7))

    assert m.osm_query_set == [q.query.value for q in OSM_QUERY_SET]
    assert len(m.osm_query_set) == 8
    assert m.osm_index_date == date(2026, 9, 7)
    assert m.chromadb_version == "x"  # the index half's fields survive
    assert path.read_text(encoding="utf-8") == existing.model_dump_json(indent=2)  # not saved
