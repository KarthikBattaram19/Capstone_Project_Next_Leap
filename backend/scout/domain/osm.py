"""The fixed OpenStreetMap question set, run for every listing at build time (spec §3.4)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel

from scout.domain.provenance import Method


class OsmQuery(str, Enum):
    NEAREST_METRO = "nearest_metro"
    NEAREST_BUS_STOP = "nearest_bus_stop"
    NEAREST_SUPERMARKET = "nearest_supermarket"
    NEAREST_HOSPITAL = "nearest_hospital"
    NEAREST_PHARMACY = "nearest_pharmacy"
    NEAREST_SCHOOL = "nearest_school"
    NEAREST_PARK = "nearest_park"
    RESTAURANTS_WITHIN_500M = "restaurants_within_500m"


@dataclass(frozen=True)
class OsmQuerySpec:
    query: OsmQuery
    label: str  # how the card names it: "Metro", "Bus stop", …
    category: str  # the MCP category / OSM tag family used
    radius_m: int
    kind: str  # "nearest" (distance to one place) | "count" (how many within radius)


OSM_QUERY_SET: tuple[OsmQuerySpec, ...] = (
    OsmQuerySpec(OsmQuery.NEAREST_METRO, "Metro", "subway_station", 3000, "nearest"),
    OsmQuerySpec(OsmQuery.NEAREST_BUS_STOP, "Bus stop", "bus_stop", 1500, "nearest"),
    OsmQuerySpec(OsmQuery.NEAREST_SUPERMARKET, "Supermarket", "supermarket", 2000, "nearest"),
    OsmQuerySpec(OsmQuery.NEAREST_HOSPITAL, "Hospital", "hospital", 5000, "nearest"),
    OsmQuerySpec(OsmQuery.NEAREST_PHARMACY, "Pharmacy", "pharmacy", 2000, "nearest"),
    OsmQuerySpec(OsmQuery.NEAREST_SCHOOL, "School", "school", 3000, "nearest"),
    OsmQuerySpec(OsmQuery.NEAREST_PARK, "Park", "park", 2000, "nearest"),
    OsmQuerySpec(OsmQuery.RESTAURANTS_WITHIN_500M, "Restaurants", "restaurant", 500, "count"),
)


class OsmFactRecord(BaseModel):
    """One row of {listing, question, answer}. Always present; null where OSM had nothing."""

    listing_id: str
    query: OsmQuery
    name: str | None = None
    distance_m: int | None = None
    duration_min: int | None = None
    count: int | None = None
    method: Method | None = None  # required whenever distance_m is not None
    retrieved_on: date
    raw: dict[str, Any] | None = None  # the MCP response, kept for the sign-off record

    def model_post_init(self, __context: Any) -> None:  # noqa: PYI063 -- __context per addendum
        if self.distance_m is not None and self.method is None:
            raise ValueError(f"{self.listing_id}/{self.query}: distance without method")
