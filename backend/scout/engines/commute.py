"""Two paths, never mixed up, because the answer is a wrapped fact that must name its method (arch §8.3)."""

from __future__ import annotations

from scout.domain.constraints import CommutePoint
from scout.domain.osm import OsmQuery
from scout.domain.provenance import Distance, Method, Provenanced, Source, Timing
from scout.pipeline.dedupe import haversine_m


class CommuteService:
    def __init__(self, store) -> None:
        self._store = store

    def transit(
        self, listing_id: str, query: OsmQuery = OsmQuery.NEAREST_METRO
    ) -> Provenanced[Distance]:
        row = self._store.osm(listing_id, query)  # no network call — precomputed (P5)
        ref = f"osm:{listing_id}:{query.value}"
        if row.distance_m is None:
            return Provenanced(
                value=None,
                source=Source.OSM,
                timing=Timing.PRECOMPUTED,
                as_of=row.retrieved_on,
                citation_ref=ref,
            )
        return Provenanced(
            value=Distance(metres=row.distance_m, minutes=row.duration_min),
            source=Source.OSM,
            timing=Timing.PRECOMPUTED,
            method=row.method,
            as_of=row.retrieved_on,
            citation_ref=ref,
        )

    def to_point(self, listing_id: str, point: CommutePoint) -> Provenanced[Distance]:
        listing = self._store.listings[listing_id]
        if listing.coordinates is None:
            return Provenanced(value=None, source=Source.COMPUTED, timing=Timing.LIVE)
        metres = int(
            haversine_m(listing.coordinates.lat, listing.coordinates.lng, point.lat, point.lng)
        )
        return Provenanced(
            value=Distance(metres=metres),
            source=Source.COMPUTED,
            timing=Timing.LIVE,
            method=Method.STRAIGHT_LINE,
            citation_ref=f"computed:{listing_id}:straight_line",
        )

    def osm_fact(self, listing_id: str, query: OsmQuery) -> Provenanced[dict]:
        row = self._store.osm(listing_id, query)
        ref = f"osm:{listing_id}:{query.value}"
        if row.count is None and row.name is None and row.distance_m is None:
            return Provenanced(
                value=None,
                source=Source.OSM,
                timing=Timing.PRECOMPUTED,
                as_of=row.retrieved_on,
                citation_ref=ref,
            )
        return Provenanced(
            value={"name": row.name, "count": row.count, "distance_m": row.distance_m},
            source=Source.OSM,
            timing=Timing.PRECOMPUTED,
            method=row.method,
            as_of=row.retrieved_on,
            citation_ref=ref,
        )
