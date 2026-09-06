"""Run the fixed OSM question set once for every listing. Null where OSM has nothing (spec §3.4).

``python -m scout.pipeline.precompute_osm`` -> ``data/bundle/osm_facts.json`` with exactly
``len(listings) x len(OSM_QUERY_SET)`` rows, and the manifest gains ``osm_query_set`` and
``osm_index_date``.

The MCP server needs ``uvx --with "mcp<2"`` and the User-Agent shim in
``scout/pipeline/osm_mcp_shim`` — both explained in ``scout.pipeline.osm_mcp``.

Why routed rows carry ``duration_min=None`` (decided 2026-09-06): the public OSRM demo server
behind the MCP ignores the requested profile — ``foot`` and ``car`` both returned
6126 m / 544 s for MG Road 12.9755,77.6068 -> Koramangala 12.935,77.62 (reproducible against
router.project-osrm.org: foot, driving and bike all give 6125.7 m / 544.3 s), a car speed. A
routed *distance* is still a real
road-network distance and is stored with ``method=ROUTED``; a routed *duration* would be a
driving time that ``scout.domain.commute_format.render_commute`` speaks as "about a N-minute
walk by route", which would be false. So ``duration_min`` stays None on every routed row and
the raw OSRM number is kept in ``raw["route"]["duration_s"]`` next to
``raw["route"]["mode_requested"]="foot"`` and ``raw["route"]["profile_honoured"]=False`` for the
sign-off record.

Resumable: ``data/raw/osm_cache.json`` caches every MCP response (find_nearby and route) keyed by
tool name + sorted arguments; it is consulted before any network call, saved every 50 new
entries and on abort, so a re-run after an outage picks up where it stopped. An outage
(``OsmUnavailable``) stops the run and never writes the output file: a null row may only come
from a successful response that contained nothing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scout.domain.listing import ListingRecord
from scout.domain.osm import OSM_QUERY_SET, OsmFactRecord, OsmQuerySpec
from scout.domain.provenance import Method
from scout.pipeline.dedupe import haversine_m

LISTINGS = Path("data/bundle/listings.json")
OUT = Path("data/bundle/osm_facts.json")
CACHE = Path("data/raw/osm_cache.json")
LOG = Path("data/raw/osm_precompute.log")
CACHE_SAVE_EVERY = 50
PROGRESS_EVERY_ROWS = 100

log = logging.getLogger("scout.pipeline.precompute_osm")


def _today_ist() -> date:
    # Every clock read in this codebase names its zone (spec §2.4, arch §10).
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


class JsonCache(dict[str, Any]):
    """The on-disk response cache: a dict that saves itself every CACHE_SAVE_EVERY new entries."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self._unsaved = 0
        if path.exists():
            self.update(json.loads(path.read_text(encoding="utf-8")))

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key, value)
        self._unsaved += 1
        if self._unsaved >= CACHE_SAVE_EVERY:
            self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self, separators=(",", ":")), encoding="utf-8")
        tmp.replace(self.path)
        self._unsaved = 0


async def resolve_query(
    mcp: Any, listing: ListingRecord, spec: OsmQuerySpec, today: date
) -> OsmFactRecord:
    null_row = OsmFactRecord(listing_id=listing.id, query=spec.query, retrieved_on=today)
    if listing.coordinates is None:
        return null_row
    lat, lng = listing.coordinates.lat, listing.coordinates.lng
    places = await mcp.find_nearby(lat, lng, spec.category, spec.radius_m)
    if spec.kind == "count":
        return OsmFactRecord(
            listing_id=listing.id,
            query=spec.query,
            count=len(places),
            retrieved_on=today,
            raw={"places": places},
        )
    if not places:
        return null_row
    nearest = min(places, key=lambda p: haversine_m(lat, lng, p["lat"], p["lng"]))
    routed = await mcp.route(lat, lng, nearest["lat"], nearest["lng"])
    if routed:
        return OsmFactRecord(
            listing_id=listing.id,
            query=spec.query,
            name=nearest["name"],
            distance_m=routed["distance_m"],
            duration_min=None,  # see the module docstring: OSRM's duration is a car time
            method=Method.ROUTED,
            retrieved_on=today,
            raw={
                "nearest": nearest,
                "route": {**routed, "mode_requested": "foot", "profile_honoured": False},
            },
        )
    return OsmFactRecord(
        listing_id=listing.id,
        query=spec.query,
        name=nearest["name"],
        distance_m=int(haversine_m(lat, lng, nearest["lat"], nearest["lng"])),
        method=Method.STRAIGHT_LINE,
        retrieved_on=today,
        raw={"nearest": nearest},
    )


def _setup_logging() -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in (logging.FileHandler(LOG, encoding="utf-8"), logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        root.addHandler(h)


def split_line(rows: list[OsmFactRecord]) -> str:
    routed = sum(1 for r in rows if r.method is Method.ROUTED)
    straight = sum(1 for r in rows if r.method is Method.STRAIGHT_LINE)
    null = sum(1 for r in rows if r.distance_m is None and r.count is None)
    return f"{len(rows)} rows; routed={routed}; straight-line={straight}; null={null}"


def routed_share_line(rows: list[OsmFactRecord]) -> str:
    """Of the listing-anchored 'nearest' rows where a place was found, how many were routed."""
    found = [r for r in rows if r.method is not None]
    routed = sum(1 for r in found if r.method is Method.ROUTED)
    pct = (100.0 * routed / len(found)) if found else 0.0
    return (
        f"nearest rows with a place found: {len(found)}; routed={routed}; "
        f"straight-line={len(found) - routed}; routed share={pct:.1f}%"
    )


async def main() -> None:
    from scout.pipeline.osm_mcp import OsmMcp

    _setup_logging()
    listings = [
        ListingRecord.model_validate(x) for x in json.loads(LISTINGS.read_text(encoding="utf-8"))
    ]
    today = _today_ist()
    cache = JsonCache(CACHE)
    total_rows = len(listings) * len(OSM_QUERY_SET)
    log.info(
        "start: %d listings x %d queries = %d rows; cache entries=%d; retrieved_on=%s",
        len(listings),
        len(OSM_QUERY_SET),
        total_rows,
        len(cache),
        today,
    )
    rows: list[OsmFactRecord] = []
    try:
        async with OsmMcp(cache=cache) as mcp:
            for i, lst in enumerate(listings, 1):
                for spec in OSM_QUERY_SET:
                    rows.append(await resolve_query(mcp, lst, spec, today))
                    # The 0.5 s pause after every real network call lives in OsmMcp;
                    # cache hits do not sleep.
                    if len(rows) % PROGRESS_EVERY_ROWS == 0:
                        log.info(
                            "rows %d/%d (listing %d/%d); cache hits=%d; network calls=%d",
                            len(rows),
                            total_rows,
                            i,
                            len(listings),
                            mcp.cache_hits,
                            mcp.network_calls,
                        )
    finally:
        cache.save()
        log.info("cache saved: %d entries", len(cache))
    assert len(rows) == total_rows, (len(rows), total_rows)
    OUT.write_text(
        json.dumps([r.model_dump(mode="json") for r in rows], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    from scout.pipeline.manifest import from_osm, save_manifest

    save_manifest(from_osm(today))
    log.info("wrote %s and updated the manifest", OUT)
    print(split_line(rows))
    print(routed_share_line(rows))


if __name__ == "__main__":
    asyncio.run(main())
