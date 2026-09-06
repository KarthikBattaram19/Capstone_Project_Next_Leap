"""Thin client over jagan-shanmugam/open-streetmap-mcp — BUILD TIME ONLY (P5).

How the server is started (all verified 2026-09-06 against PyPI ``osm-mcp-server`` 0.1.1):

* ``uvx --with "mcp<2" osm-mcp-server`` — the server imports ``mcp.server.fastmcp``, which only
  exists in mcp 1.x; our venv pins mcp==2.1.1, so uvx gives the server its own 1.x copy.
  Without ``--with "mcp<2"`` it crashes at import.
* ``PYTHONPATH=<backend/scout/pipeline/osm_mcp_shim>`` — that directory holds a
  ``sitecustomize.py`` that gives the server's aiohttp session a proper User-Agent (overpass-api.de
  answers 406 to anything mentioning "aiohttp") and honours ``$OVERPASS_URL`` as a mirror. See the
  shim's docstring.

mcp 2.1.1 client API (inspected with ``inspect.signature`` / ``model_fields``):
``Tool.input_schema`` (not ``inputSchema``); ``ClientSession.call_tool(name, arguments,
read_timeout_seconds=None, ...)`` returns ``CallToolResult`` with ``.is_error: bool`` and
``.content: list`` where a ``TextContent`` has ``.type == "text"`` and ``.text``. A tool exception
inside the server does NOT raise here: it comes back as ``is_error=True`` with the text
``"Error executing tool <name>: <message>"``.

The server's real input schemas, printed by its own ``list_tools`` on 2026-09-06:

find_nearby_places
  {"properties": {"latitude": {"title": "Latitude", "type": "number"},
                  "longitude": {"title": "Longitude", "type": "number"},
                  "radius": {"default": 1000, "title": "Radius", "type": "number"},
                  "categories": {"default": null, "items": {"type": "string"},
                                 "title": "Categories", "type": "array"},
                  "limit": {"default": 20, "title": "Limit", "type": "integer"}},
   "required": ["latitude", "longitude"], "title": "find_nearby_placesArguments",
   "type": "object"}
  NOT USED for nearest-X: it treats each category as an OSM tag *key*, returns nodes only, and
  applies ``limit`` to the raw element list before grouping by subcategory, so a hospital may
  never be among the first 20 amenities.

search_category   (the tool every nearest / count query uses)
  {"properties": {"category": {"title": "Category", "type": "string"},
                  "min_latitude": {"title": "Min Latitude", "type": "number"},
                  "min_longitude": {"title": "Min Longitude", "type": "number"},
                  "max_latitude": {"title": "Max Latitude", "type": "number"},
                  "max_longitude": {"title": "Max Longitude", "type": "number"},
                  "subcategories": {"default": null, "items": {"type": "string"},
                                    "title": "Subcategories", "type": "array"}},
   "required": ["category", "min_latitude", "min_longitude", "max_latitude", "max_longitude"],
   "title": "search_categoryArguments", "type": "object"}
  With ``subcategories`` the server builds ``node[("<key>"="<sub>" or ...)](bbox)``, which is
  NOT valid Overpass QL: every Overpass instance answers HTTP 400, "parse error: Key expected -
  '(' found" (verified 2026-09-06 with curl against overpass.openstreetmap.fr and
  maps.mail.ru; it is the same OSM3S parser overpass-api.de runs). Without ``subcategories`` it
  builds ``node["<category>"](bbox)`` with the ``category`` string interpolated verbatim, so this
  wrapper passes the whole tag expression as the category — ``category='amenity"="hospital'``
  becomes ``node["amenity"="hospital"](bbox)``, which parses and is the query we want. That is
  the only way to get a key=value search out of this server without patching it; the value
  is checked again client-side from ``tags`` so a surprise in the interpolation cannot pass.
  The server keeps only elements that have coordinates and never asks for ``out center``, so
  ways and relations are dropped — results are NODES ONLY (parks, schools and hospitals mapped
  as areas are invisible; a limitation of the server, recorded in the plan). Output:
  {"query": {...}, "results": [{"id", "type", "name" ("Unnamed" when untagged),
  "coordinates": {"latitude", "longitude"}, "category", "subcategory", "tags": {...}}, ...]}

get_route_directions
  {"properties": {"from_latitude": {"title": "From Latitude", "type": "number"},
                  "from_longitude": {"title": "From Longitude", "type": "number"},
                  "to_latitude": {"title": "To Latitude", "type": "number"},
                  "to_longitude": {"title": "To Longitude", "type": "number"},
                  "mode": {"default": "car", "title": "Mode", "type": "string"}},
   "required": ["from_latitude", "from_longitude", "to_latitude", "to_longitude"],
   "title": "get_route_directionsArguments", "type": "object"}
  Valid modes are "car", "bike", "foot" ("walking" is invalid and silently falls back to car).
  Output: {"summary": {"distance": <metres>, "duration": <seconds>, "mode": ...},
  "directions": [...], "geometry": ..., "waypoints": [...]} — distance and duration are NESTED
  under "summary". A missing route raises inside the server -> is_error with "No route found".
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any, Self

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from scout.pipeline.dedupe import haversine_m

log = logging.getLogger(__name__)

SHIM_DIR = Path(__file__).resolve().parent / "osm_mcp_shim"
SERVER_COMMAND = "uvx"
SERVER_ARGS = ("--with", "mcp<2", "osm-mcp-server")

# Waits between attempts; a 429 / 504 / timeout from Overpass or OSRM arrives as an is_error
# text, so it is retried like an exception. After the last wait the run STOPS (OsmUnavailable):
# an outage must never be written to the bundle as "OSM has nothing".
RETRY_WAITS_S: tuple[float, ...] = (5, 15, 45, 120)
# Overpass and OSRM behind the MCP are shared public services.
PAUSE_AFTER_NETWORK_CALL_S = 0.5
# The server's aiohttp session times out at 300 s; this lets it report first.
CALL_TIMEOUT_S = 330.0

# Our category names (scout.domain.osm.OSM_QUERY_SET) -> (OSM tag key, tag value).
# Sent to search_category as category='<key>"="<value>' (see the module docstring for why).
CATEGORY_TABLE: dict[str, tuple[str, str]] = {
    # Namma Metro stations carry railway=station + station=subway; see _keep_place for the
    # extra filter that drops suburban-rail stations sharing railway=station.
    "subway_station": ("railway", "station"),
    "bus_stop": ("highway", "bus_stop"),
    "supermarket": ("shop", "supermarket"),
    "hospital": ("amenity", "hospital"),
    "pharmacy": ("amenity", "pharmacy"),
    "school": ("amenity", "school"),
    "park": ("leisure", "park"),
    "restaurant": ("amenity", "restaurant"),
}


def category_expression(category: str) -> str:
    """The ``category`` argument that makes search_category emit ``node["key"="value"]``."""
    key, value = CATEGORY_TABLE[category]
    return f'{key}"="{value}'


_MISSING = object()


class OsmUnavailable(RuntimeError):
    """The MCP / Overpass / OSRM kept failing after every retry — stop the run, keep the cache."""


class _ToolError(RuntimeError):
    """The server reported is_error=True; the message is the server's text."""


def _keep_place(category: str, tags: dict[str, Any]) -> bool:
    if category != "subway_station":
        return True
    # Probed against MG Road (12.9755, 77.6068, 3 km) before the full run — see the
    # Task 1.3 status bullet in Docs/Implementation_Plan.md for what the tagging looked like.
    return (
        tags.get("station") in ("subway", "light_rail")
        or tags.get("subway") == "yes"
        or tags.get("light_rail") == "yes"
    )


def _bbox(lat: float, lng: float, radius_m: int) -> dict[str, float]:
    lat_delta = radius_m / 111_000
    lon_delta = radius_m / (111_000 * math.cos(math.radians(lat)))
    return {
        "min_latitude": lat - lat_delta,
        "min_longitude": lng - lon_delta,
        "max_latitude": lat + lat_delta,
        "max_longitude": lng + lon_delta,
    }


def cache_key(tool: str, args: dict[str, Any]) -> str:
    """Canonical string of (tool name, sorted args) — the key of the on-disk response cache."""
    return json.dumps([tool, args], sort_keys=True, separators=(",", ":"))


class OsmMcp:
    """Async context manager over ``uvx --with "mcp<2" osm-mcp-server`` (stdio).

    ``cache`` maps :func:`cache_key` -> the parsed result of ``find_nearby`` / ``route``; it is
    consulted before any network call, a hit does not sleep, and every new network result is
    written into it (the caller owns persistence — see precompute_osm.JsonCache).
    """

    def __init__(
        self,
        cache: MutableMapping[str, Any] | None = None,
        pause_s: float = PAUSE_AFTER_NETWORK_CALL_S,
        retry_waits_s: tuple[float, ...] = RETRY_WAITS_S,
    ) -> None:
        self._cache: MutableMapping[str, Any] = cache if cache is not None else {}
        self._pause_s = pause_s
        self._retry_waits_s = retry_waits_s
        self.cache_hits = 0
        self.network_calls = 0

    async def __aenter__(self) -> Self:
        env = dict(os.environ)
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(SHIM_DIR) + (os.pathsep + existing if existing else "")
        self._cm = stdio_client(
            StdioServerParameters(command=SERVER_COMMAND, args=list(SERVER_ARGS), env=env)
        )
        r, w = await self._cm.__aenter__()
        self._session_cm = ClientSession(r, w)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc: object) -> None:
        # Deliberately NOT forwarding *exc: mcp 2.1.1's ClientSession and stdio_client are
        # anyio task groups, and handing them an in-flight exception makes it come back out
        # wrapped in an ExceptionGroup (and stdio_client's generator complains about exiting a
        # cancel scope in another task). Closing them cleanly lets ``async with`` re-raise the
        # original — so OsmUnavailable stays catchable as itself. Verified 2026-09-07.
        try:
            await self._session_cm.__aexit__(None, None, None)
        finally:
            await self._cm.__aexit__(None, None, None)

    async def _call_once(self, tool: str, args: dict[str, Any]) -> Any:
        result = await self._session.call_tool(tool, args, read_timeout_seconds=CALL_TIMEOUT_S)
        text = "".join(c.text for c in result.content if getattr(c, "type", None) == "text")
        if result.is_error:
            raise _ToolError(text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}

    async def _call(self, tool: str, args: dict[str, Any]) -> Any:
        """One network call with retries; "No route found" is not an outage and is re-raised."""
        last: BaseException | None = None
        for attempt, wait in enumerate((*self._retry_waits_s, None)):
            try:
                out = await self._call_once(tool, args)
            except _ToolError as e:
                if "No route found" in str(e):
                    raise
                last = e
            except Exception as e:  # noqa: BLE001 - anything from the transport is retried
                last = e
            else:
                self.network_calls += 1
                await asyncio.sleep(self._pause_s)
                return out
            if wait is None:
                break
            log.warning(
                "%s failed (attempt %d): %s — retrying in %ss", tool, attempt + 1, last, wait
            )
            await asyncio.sleep(wait)
        raise OsmUnavailable(f"{tool} failed after {len(self._retry_waits_s) + 1} attempts: {last}")

    async def find_nearby(
        self, lat: float, lng: float, category: str, radius_m: int
    ) -> list[dict[str, Any]]:
        """Places of ``category`` within ``radius_m`` (a circle, filtered client-side from the bbox).

        Returns ``[{"name": str | None, "lat": float, "lng": float}, ...]``; "Unnamed" is None.
        """
        key_, value = CATEGORY_TABLE[category]
        args = {"category": category_expression(category), **_bbox(lat, lng, radius_m)}
        # The two "_" entries are not sent; they make the key specific to the client-side
        # filters (radius circle, metro tags) applied before caching.
        args = {"_category": category, "_radius_m": radius_m, **args}
        key = cache_key("search_category", args)
        hit = self._cache.get(key, _MISSING)
        if hit is not _MISSING:
            self.cache_hits += 1
            return list(hit)
        call_args = {k: v for k, v in args.items() if not k.startswith("_")}
        out = await self._call("search_category", call_args)
        results = out.get("results", []) if isinstance(out, dict) else []
        places: list[dict[str, Any]] = []
        for p in results:
            coords = p.get("coordinates") or {}
            plat, plng = coords.get("latitude"), coords.get("longitude")
            if plat is None or plng is None:
                continue
            tags = p.get("tags") or {}
            if tags.get(key_) != value or not _keep_place(category, tags):
                continue
            if haversine_m(lat, lng, float(plat), float(plng)) > radius_m:
                continue
            name = tags.get("name")
            places.append({"name": name if name else None, "lat": float(plat), "lng": float(plng)})
        self._cache[key] = places
        return places

    async def route(
        self, lat1: float, lng1: float, lat2: float, lng2: float, mode: str = "foot"
    ) -> dict[str, Any] | None:
        """Road-network route; ``None`` when OSRM has no route (the caller falls back to straight-line)."""
        args = {
            "from_latitude": lat1,
            "from_longitude": lng1,
            "to_latitude": lat2,
            "to_longitude": lng2,
            "mode": mode,
        }
        key = cache_key("get_route_directions", args)
        hit = self._cache.get(key, _MISSING)
        if hit is not _MISSING:
            self.cache_hits += 1
            return dict(hit) if hit is not None else None
        try:
            out = await self._call("get_route_directions", args)
        except _ToolError:  # "No route found"
            self._cache[key] = None
            return None
        summary = out.get("summary") if isinstance(out, dict) else None
        if not isinstance(summary, dict) or summary.get("distance") is None:
            self._cache[key] = None
            return None
        routed = {
            "distance_m": round(float(summary["distance"])),
            "duration_s": round(float(summary.get("duration") or 0)),
        }
        self._cache[key] = routed
        return routed
