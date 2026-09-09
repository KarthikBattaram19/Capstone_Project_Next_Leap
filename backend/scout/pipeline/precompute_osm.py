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
import math
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
# Rows land here one line at a time while the run is in flight; see RowSink.
ROWS_TMP = Path("data/raw/osm_rows.jsonl.tmp")
CACHE_SAVE_EVERY = 50
PROGRESS_EVERY_ROWS = 100
# How many of the nearest candidates are routed before the shortest road distance is chosen.
# See nearest_by_route for why 1 was wrong and what the cap does and does not guarantee.
ROUTE_CANDIDATES = 3
# Skip the extra candidates when the nearest already routes within this many metres of its own
# straight-line distance. 0 = always consider ROUTE_CANDIDATES.
RE_ROUTE_MIN_EXCESS_M = 0

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
        # Streamed, not `json.dumps(...)` into a string first. This runs every
        # CACHE_SAVE_EVERY entries, and by the end the cache is ~16 MB, so building the whole
        # document in memory each time is a repeated double-size spike. The run was killed for
        # low memory at row 7,400 on 2026-09-09; this is one of the two places that caused it.
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(self, fh, separators=(",", ":"))
        tmp.replace(self.path)
        self._unsaved = 0


async def nearest_by_route(
    mcp: Any, lat: float, lng: float, places: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, Any]]]:
    """The nearest place *to reach*, not the nearest as the crow flies.

    Until 2026-09-09 this picked the place with the shortest straight-line distance and then
    routed that one, whatever the road said. Measured consequence: `aecs-layout-05393` named a
    hospital 583 m away in a straight line that is **5,663 m by road**, while another 618 m away
    routed in 1,034 m. Adding area-mapped places (see AREA_CAPABLE) handed that rule many more
    candidates, so it fired more often — 334 of 1,696 changed rows came out worse.

    So the nearest few by straight line are routed and the shortest ROAD distance wins. Two
    things keep the cost down, and neither can change the answer:

    * A road route is never shorter than the straight line between the same two points, so once
      some candidate has routed in R metres, any candidate whose straight-line distance is
      already >= R cannot beat it and is never routed. This prune is exact.
    * ``ROUTE_CANDIDATES`` caps how many are tried at all. This one is a genuine approximation:
      the answer is the best of the nearest few, not of every place in the radius. It is
      recorded in ``raw.considered`` on every row so the choice can be audited.

    ``RE_ROUTE_MIN_EXCESS_M`` stops after the first candidate when that candidate already routes
    well (road distance within this many metres of its straight line), on the grounds that a
    well-connected nearest place is not worth two more route calls. 0 disables the shortcut.

    Returns (chosen place, its route or None, the candidates considered).
    """
    ranked = sorted(places, key=lambda p: haversine_m(lat, lng, p["lat"], p["lng"]))
    best_place: dict[str, Any] | None = None
    best_route: dict[str, Any] | None = None
    considered: list[dict[str, Any]] = []

    for i, p in enumerate(ranked[:ROUTE_CANDIDATES]):
        straight = haversine_m(lat, lng, p["lat"], p["lng"])
        if best_route is not None and straight >= best_route["distance_m"]:
            break  # exact prune: no road route can come in under its own straight line
        routed = await mcp.route(lat, lng, p["lat"], p["lng"])
        considered.append(
            {
                "name": p["name"],
                "straight_m": int(straight),
                "route_m": routed["distance_m"] if routed else None,
            }
        )
        if routed and (best_route is None or routed["distance_m"] < best_route["distance_m"]):
            best_place, best_route = p, routed
        if (
            i == 0
            and routed
            and RE_ROUTE_MIN_EXCESS_M
            and routed["distance_m"] - straight <= RE_ROUTE_MIN_EXCESS_M
        ):
            break

    if best_route is not None and best_place is not None:
        return best_place, best_route, considered
    # Nothing routed: fall back to the straight-line nearest, exactly as before.
    return ranked[0], None, considered


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
    chosen, routed, considered = await nearest_by_route(mcp, lat, lng, places)
    if routed:
        return OsmFactRecord(
            listing_id=listing.id,
            query=spec.query,
            name=chosen["name"],
            distance_m=routed["distance_m"],
            duration_min=None,  # see the module docstring: OSRM's duration is a car time
            method=Method.ROUTED,
            retrieved_on=today,
            raw={
                "nearest": chosen,
                "route": {**routed, "mode_requested": "foot", "profile_honoured": False},
                "considered": considered,
            },
        )
    return OsmFactRecord(
        listing_id=listing.id,
        query=spec.query,
        name=chosen["name"],
        distance_m=int(haversine_m(lat, lng, chosen["lat"], chosen["lng"])),
        method=Method.STRAIGHT_LINE,
        retrieved_on=today,
        raw={"nearest": chosen, "considered": considered},
    )


def listings_bbox(
    listings: list[ListingRecord], margin_m: int
) -> tuple[float, float, float, float]:
    """(south, west, north, east) covering every listing, plus ``margin_m`` on each side."""
    pts = [x.coordinates for x in listings if x.coordinates is not None]
    if not pts:
        raise ValueError("no listing has coordinates")
    lats = [p.lat for p in pts]
    lngs = [p.lng for p in pts]
    dlat = margin_m / 111_000
    # Widen longitude at the highest latitude in the set, so the margin holds everywhere.
    dlng = margin_m / (111_000 * math.cos(math.radians(max(abs(min(lats)), abs(max(lats))))))
    return (min(lats) - dlat, min(lngs) - dlng, max(lats) + dlat, max(lngs) + dlng)


async def prefetch_area_categories(mcp: Any, listings: list[ListingRecord]) -> None:
    """One Overpass query per area-capable category, covering every listing at once."""
    from scout.pipeline.osm_mcp import AREA_CAPABLE

    specs = [s for s in OSM_QUERY_SET if s.category in AREA_CAPABLE]
    if not specs:
        return
    bbox = listings_bbox(listings, margin_m=max(s.radius_m for s in specs))
    for spec in specs:
        places = await mcp.prefetch_area(spec.category, bbox)
        log.info(
            "prefetched %d %s places for the whole listing area in one query",
            len(places),
            spec.category,
        )


class RowSink:
    """Holds the tallies, not the rows.

    The run used to keep all 18,960 ``OsmFactRecord`` objects in a list and then build a
    SECOND full copy of them as dicts to dump. That peak is at the very end, which is why the
    2026-09-09 runs were killed for low memory later and later as the cache warmed — 7,400,
    then 8,000, then 16,500 of 18,960 — on a machine with 7.8 GB total and under 1 GB free.

    Each row is written to a JSONL scratch file the moment it exists and then dropped, so peak
    memory is flat in the number of rows. ``finalise`` streams that file into the real
    ``osm_facts.json`` one row at a time, producing the same ``indent=2`` array as before.
    """

    def __init__(self, tmp_path: Path, rows_per_listing: int, resume: bool = True) -> None:
        self.tmp_path = tmp_path
        self.tmp_path.parent.mkdir(parents=True, exist_ok=True)
        self.n = 0
        self.routed = 0
        self.straight = 0
        self.null = 0
        self.listings_done = 0
        if resume and tmp_path.exists():
            self._reopen_after_last_complete_listing(rows_per_listing)
        else:
            self._fh = tmp_path.open("w", encoding="utf-8")

    def _reopen_after_last_complete_listing(self, rows_per_listing: int) -> None:
        """Keep every row of every COMPLETE listing, drop a half-written one, append after it.

        The response cache already means an interrupted run costs no network calls twice, but
        it still had to re-derive every row from scratch, and on this machine the run kept being
        killed at ~17,000 of 18,960 before it could write anything. Keeping the rows too means
        each attempt only does listings nobody has done, so the work converges however often it
        is interrupted. A listing's rows are written together and in order, so "complete" is
        simply a whole multiple of the query-set size.
        """
        kept = self.tmp_path.with_suffix(".resume")
        with self.tmp_path.open(encoding="utf-8") as src, kept.open("w", encoding="utf-8") as dst:
            for line in src:
                row = json.loads(line)
                self.n += 1
                if row.get("method") == Method.ROUTED.value:
                    self.routed += 1
                elif row.get("method") == Method.STRAIGHT_LINE.value:
                    self.straight += 1
                if row.get("distance_m") is None and row.get("count") is None:
                    self.null += 1
                dst.write(line if line.endswith("\n") else line + "\n")
        complete = (self.n // rows_per_listing) * rows_per_listing
        if complete != self.n:
            # A partial listing is worse than none: re-derive it rather than reason about
            # which of its queries made it to disk.
            self._truncate(kept, complete, rows_per_listing)
        kept.replace(self.tmp_path)
        self.listings_done = self.n // rows_per_listing
        self._fh = self.tmp_path.open("a", encoding="utf-8")
        log.info("resuming: %d rows kept (%d complete listings)", self.n, self.listings_done)

    def _truncate(self, path: Path, keep: int, rows_per_listing: int) -> None:
        trimmed = path.with_suffix(".trim")
        self.n = self.routed = self.straight = self.null = 0
        with path.open(encoding="utf-8") as src, trimmed.open("w", encoding="utf-8") as dst:
            for i, line in enumerate(src):
                if i >= keep:
                    break
                row = json.loads(line)
                self.n += 1
                if row.get("method") == Method.ROUTED.value:
                    self.routed += 1
                elif row.get("method") == Method.STRAIGHT_LINE.value:
                    self.straight += 1
                if row.get("distance_m") is None and row.get("count") is None:
                    self.null += 1
                dst.write(line)
        trimmed.replace(path)

    def add(self, row: OsmFactRecord) -> None:
        self.n += 1
        if row.method is Method.ROUTED:
            self.routed += 1
        elif row.method is Method.STRAIGHT_LINE:
            self.straight += 1
        if row.distance_m is None and row.count is None:
            self.null += 1
        self._fh.write(json.dumps(row.model_dump(mode="json"), ensure_ascii=False) + "\n")

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    def finalise(self, out: Path) -> None:
        """JSONL scratch -> the committed indent=2 JSON array, one row in memory at a time."""
        self.close()
        with self.tmp_path.open(encoding="utf-8") as src, out.open("w", encoding="utf-8") as dst:
            dst.write("[\n")
            for i, line in enumerate(src):
                if i:
                    dst.write(",\n")
                # Re-indent one row so the file matches json.dumps(list, indent=2) exactly.
                body = json.dumps(json.loads(line), indent=2, ensure_ascii=False)
                dst.write("\n".join("  " + ln for ln in body.splitlines()))
            dst.write("\n]")
        self.tmp_path.unlink(missing_ok=True)

    def split_line(self) -> str:
        return (
            f"{self.n} rows; routed={self.routed}; straight-line={self.straight}; null={self.null}"
        )

    def routed_share_line(self) -> str:
        """Of the listing-anchored 'nearest' rows where a place was found, how many were routed."""
        found = self.routed + self.straight
        pct = (100.0 * self.routed / found) if found else 0.0
        return (
            f"nearest rows with a place found: {found}; routed={self.routed}; "
            f"straight-line={self.straight}; routed share={pct:.1f}%"
        )


def _setup_logging() -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in (logging.FileHandler(LOG, encoding="utf-8"), logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        root.addHandler(h)


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
    sink = RowSink(ROWS_TMP, rows_per_listing=len(OSM_QUERY_SET))
    try:
        async with OsmMcp(cache=cache) as mcp:
            await prefetch_area_categories(mcp, listings)
            for i, lst in enumerate(listings, 1):
                if i <= sink.listings_done:
                    continue  # already on disk from an interrupted run
                for spec in OSM_QUERY_SET:
                    sink.add(await resolve_query(mcp, lst, spec, today))
                    # The 0.5 s pause after every real network call lives in OsmMcp;
                    # cache hits do not sleep.
                    if sink.n % PROGRESS_EVERY_ROWS == 0:
                        log.info(
                            "rows %d/%d (listing %d/%d); cache hits=%d; network calls=%d",
                            sink.n,
                            total_rows,
                            i,
                            len(listings),
                            mcp.cache_hits,
                            mcp.network_calls,
                        )
    finally:
        cache.save()
        sink.close()
        log.info("cache saved: %d entries", len(cache))
    # Only a complete run may replace the bundle: a partial file would be a silent data loss,
    # and the boot checks would refuse it anyway (every listing x query must have a row).
    assert sink.n == total_rows, (sink.n, total_rows)
    sink.finalise(OUT)
    from scout.pipeline.manifest import from_osm, save_manifest

    save_manifest(from_osm(today))
    log.info("wrote %s and updated the manifest", OUT)
    print(sink.split_line())
    print(sink.routed_share_line())


if __name__ == "__main__":
    asyncio.run(main())
