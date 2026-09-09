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
    # Pharmacy, not hospital: hospitals moved to the direct-Overpass path on 2026-09-09
    # (AREA_CAPABLE). This test is about what the MCP path still does for the point features
    # left on it. 12.935/77.62 -> a point 1.9 km due north is inside the 2 km bbox, the corner
    # is not.
    reply = {
        "results": [
            _place("Near", 12.9521, 77.62, amenity="pharmacy"),  # ~1.9 km north
            _place("Corner", 12.9521, 77.6375, amenity="pharmacy"),  # ~2.7 km, inside bbox
            _place(None, 12.936, 77.621, amenity="pharmacy"),  # Unnamed
            _place("Wrong value", 12.936, 77.62, amenity="clinic"),
        ]
    }
    m = _mcp([_Result(json.dumps(reply))])
    got = await m.find_nearby(12.935, 77.62, "pharmacy", 2000)
    name, args = m._session.calls[0]
    assert name == "search_category"
    assert args["category"] == 'amenity"="pharmacy'
    assert "subcategories" not in args
    assert args["min_latitude"] < 12.935 < args["max_latitude"]
    assert args["min_longitude"] < 77.62 < args["max_longitude"]
    assert [p["name"] for p in got] == ["Near", None]
    assert m.network_calls == 1


async def test_metro_keeps_namma_metro_and_drops_indian_railways_stations():
    # Metro moved to the direct-Overpass path on 2026-09-09 (see AREA_CAPABLE); the tag
    # filter that separates Namma Metro from suburban rail has to survive the move.
    reply = _Resp(
        {
            "elements": [
                {
                    "type": "node",
                    "lat": 12.98,
                    "lon": 77.61,
                    "tags": {"name": "Bangalore Cantonment", "railway": "station", "network": "IR"},
                },
                {
                    "type": "node",
                    "lat": 12.973,
                    "lon": 77.617,
                    "tags": {
                        "name": "Trinity",
                        "railway": "station",
                        "station": "subway",
                        "subway": "yes",
                    },
                },
                # A station mapped as an area — invisible to the node-only MCP path.
                {
                    "type": "way",
                    "id": 3,
                    "center": {"lat": 12.9705, "lon": 77.6065},
                    "tags": {"name": "MG Road", "railway": "station", "station": "subway"},
                },
            ]
        }
    )
    m = _area_mcp([reply])
    got = await m.find_nearby(12.9755, 77.6068, "subway_station", 3000)
    assert [p["name"] for p in got] == ["Trinity", "MG Road"]


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
        await m.find_nearby(12.935, 77.62, "pharmacy", 2000)  # a category still on the MCP path
    assert len(m._session.calls) == 3  # one try per wait, plus the last
    assert m.network_calls == 0


def test_every_query_set_category_has_a_tag_mapping():
    assert set(osm_mcp.CATEGORY_TABLE) == {q.category for q in OSM_QUERY_SET}


def test_area_capable_categories_are_all_real_categories():
    assert osm_mcp.AREA_CAPABLE <= {q.category for q in OSM_QUERY_SET}


def test_metro_radius_reaches_past_the_core_but_still_describes_an_amenity():
    # 3 km left the metro row null on 1,411 of 2,370 listings; 10 km is the agreed line
    # (2026-09-09). A change here changes what every metro fact in the bundle means.
    assert METRO.radius_m == 10000


# --- the area-aware Overpass path -------------------------------------------------------------


class FakeHttp:
    """Replays scripted Overpass responses; records the query text it was asked."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.queries = []

    async def post(self, url, data=None, headers=None, timeout=None):
        self.queries.append(data["data"])
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class _Resp:
    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self._payload = payload
        self.text = payload if isinstance(payload, str) else json.dumps(payload)

    def json(self):
        return self._payload


def _area_mcp(replies, cache=None):
    m = OsmMcp(cache=cache, pause_s=0, retry_waits_s=(0, 0))
    m._http = FakeHttp(replies)
    return m


def test_the_query_asks_for_ways_and_relations_and_a_centre_point():
    q = osm_mcp.overpass_around_query("park", 12.935, 77.62, 2000)
    assert 'node["leisure"="park"](around:2000,12.935,77.62);' in q
    assert 'way["leisure"="park"](around:2000,12.935,77.62);' in q
    assert 'relation["leisure"="park"](around:2000,12.935,77.62);' in q
    # Without this the ways come back with no coordinates at all and are dropped again.
    assert q.rstrip().endswith("out center;")


async def test_a_park_mapped_as_a_way_is_found_where_the_node_only_path_saw_nothing():
    # This is the measured 2026-09-09 case: 0 nodes, a way 584 m away, inside the ORIGINAL
    # 2 km radius. The node-only path returned nothing here at any radius.
    reply = _Resp(
        {
            "elements": [
                {
                    "type": "way",
                    "id": 7,
                    "center": {"lat": 12.9403, "lon": 77.6215},
                    "tags": {"leisure": "park", "name": "Ward Park"},
                },
            ]
        }
    )
    m = _area_mcp([reply])
    got = await m.find_nearby(12.935, 77.62, "park", 2000)
    assert got == [{"name": "Ward Park", "lat": 12.9403, "lng": 77.6215}]
    assert m.network_calls == 1


async def test_a_park_whose_centre_is_outside_the_radius_is_dropped():
    # `around:` keeps a park whose EDGE is in range. We name and route to the centre, so a
    # centre out of range would be a distance we never measured.
    reply = _Resp(
        {
            "elements": [
                {
                    "type": "way",
                    "id": 8,
                    "center": {"lat": 12.99, "lon": 77.62},  # ~6 km north
                    "tags": {"leisure": "park", "name": "Far Park"},
                },
                {
                    "type": "relation",
                    "id": 9,
                    "center": {"lat": 12.9375, "lon": 77.62},
                    "tags": {"leisure": "park"},  # unnamed
                },
            ]
        }
    )
    got = await _area_mcp([reply]).find_nearby(12.935, 77.62, "park", 2000)
    assert got == [{"name": None, "lat": 12.9375, "lng": 77.62}]


async def test_the_area_path_caches_like_the_mcp_path_and_never_collides_with_it():
    cache = {}
    reply = _Resp(
        {"elements": [{"type": "node", "lat": 12.936, "lon": 77.62, "tags": {"leisure": "park"}}]}
    )
    m = _area_mcp([reply], cache=cache)
    first = await m.find_nearby(12.935, 77.62, "park", 2000)
    again = await m.find_nearby(12.935, 77.62, "park", 2000)
    assert first == again and m.network_calls == 1 and m.cache_hits == 1
    # A search_category key for the same place must not be answered from this entry.
    assert all("overpass_around" in k for k in cache)


async def test_prefetch_asks_once_for_the_whole_box_and_then_answers_without_the_network():
    reply = _Resp(
        {
            "elements": [
                {"type": "node", "lat": 12.936, "lon": 77.62, "tags": {"leisure": "park"}},
                # 6 km north of the listing below: in the box, out of the 2 km circle.
                {
                    "type": "way",
                    "id": 2,
                    "center": {"lat": 12.99, "lon": 77.62},
                    "tags": {"leisure": "park", "name": "Far"},
                },
            ]
        }
    )
    m = _area_mcp([reply])
    await m.prefetch_area("park", (12.8, 77.4, 13.2, 77.8))
    q = m._http.queries[0]
    assert 'way["leisure"="park"](12.8,77.4,13.2,77.8);' in q
    assert q.rstrip().endswith("out center;")

    # Every listing after this is answered from memory, and the circle still applies.
    got = await m.find_nearby(12.935, 77.62, "park", 2000)
    assert got == [{"name": None, "lat": 12.936, "lng": 77.62}]
    again = await m.find_nearby(12.9, 77.6, "park", 2000)
    assert again == []
    assert m.network_calls == 1  # one query for the whole city, not one per listing


def test_the_prefetch_box_covers_every_listing_plus_the_radius():
    from scout.pipeline.precompute_osm import listings_bbox

    def at(lat, lng):
        return ListingRecord(
            id=f"{lat}-{lng}",
            source_url="u",
            scraped_on=date(2026, 9, 1),
            locality="L",
            coordinates=Coordinates(lat=lat, lng=lng),
        )

    s, w, n, e = listings_bbox([at(12.9, 77.5), at(13.1, 77.7)], margin_m=2000)
    assert s < 12.9 and w < 77.5 and n > 13.1 and e > 77.7
    # 2 km is roughly 0.018 degrees of latitude; the margin must be real but not wild.
    assert 0.015 < 12.9 - s < 0.025


async def test_a_listing_with_no_coordinates_cannot_break_the_prefetch_box():
    from scout.pipeline.precompute_osm import listings_bbox

    with_coords = ListingRecord(
        id="a",
        source_url="u",
        scraped_on=date(2026, 9, 1),
        locality="L",
        coordinates=Coordinates(lat=12.9, lng=77.5),
    )
    without = ListingRecord(id="b", source_url="u", scraped_on=date(2026, 9, 1), locality="L")
    s, w, n, e = listings_bbox([with_coords, without], margin_m=1000)
    assert s < 12.9 < n and w < 77.5 < e


async def test_an_overpass_outage_stops_the_run_instead_of_becoming_no_parks_here():
    # The invariant the whole pipeline rests on: a null row may only come from a SUCCESSFUL
    # response that contained nothing (see precompute_osm's docstring).
    m = _area_mcp([_Resp("rate limited", 429), _Resp("gateway timeout", 504), OSError("dropped")])
    with pytest.raises(OsmUnavailable):
        await m.find_nearby(12.935, 77.62, "park", 2000)
    assert len(m._http.queries) == 3
    assert m.network_calls == 0


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
