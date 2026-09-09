"""One resolver per kind of claim. Job 2 can reach no data except through here (A2, arch §9.3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from scout.domain.constraints import CommutePoint
from scout.domain.guides import GuideChunk
from scout.domain.osm import OSM_QUERY_SET
from scout.domain.provenance import Provenanced, Source, Timing

ClaimKind = Literal["listing_fact", "transit", "amenity", "neighbourhood", "other"]
FactRef = str

LISTING_FACTS = (
    "rent",
    "deposit",
    "maintenance_charges",
    "maintenance_included",
    "bhk_type",
    "bedrooms",
    "bathrooms",
    "furnishing",
    "parking",
    "lift",
    "floor",
    "total_floors",
    "square_footage",
    "area_basis",
    "available_from",
    "society_name",
    "property_type",
    "amenities",
)


@dataclass
class FactBundle:
    listing_id: str
    locality: str
    facts: dict[FactRef, Provenanced[Any]] = field(default_factory=dict)
    chunks: list[Provenanced[GuideChunk]] = field(default_factory=list)

    def gaps(self) -> list[FactRef]:
        return [ref for ref, f in self.facts.items() if f.value is None]

    def all_refs(self) -> set[FactRef]:
        return set(self.facts) | {c.citation_ref for c in self.chunks}


class DatasetResolver:
    def __init__(self, store) -> None:
        self._store = store

    def resolve(self, listing_id: str) -> dict[FactRef, Provenanced[Any]]:
        listing = self._store.listings[listing_id]
        out: dict[FactRef, Provenanced[Any]] = {}
        for name in LISTING_FACTS:
            f = listing.field(name)
            ref = f"dataset:{listing_id}:{name}"
            out[ref] = Provenanced(
                value=f.value,
                source=f.source,
                timing=f.timing,
                as_of=f.as_of,
                citation_ref=ref,
            )
        return out


class OsmResolver:
    def __init__(self, commute) -> None:
        self._commute = commute

    def resolve(
        self, listing_id: str, commute_point: CommutePoint | None
    ) -> dict[FactRef, Provenanced[Any]]:
        out: dict[FactRef, Provenanced[Any]] = {}
        for spec in OSM_QUERY_SET:
            if spec.kind == "nearest":
                f = self._commute.transit(listing_id, spec.query)
            else:
                f = self._commute.osm_fact(listing_id, spec.query)
            out[f.citation_ref] = f
        if commute_point is not None:
            f = self._commute.to_point(listing_id, commute_point)
            out[f.citation_ref or f"computed:{listing_id}:straight_line"] = f
        return out


class DocumentResolver:
    def __init__(self, retrieval) -> None:
        self._retrieval = retrieval

    def resolve(self, locality: str, question: str) -> list[Provenanced[GuideChunk]]:
        return self._retrieval.retrieve(locality, question, k=4)


class UnavailableResolver:
    def resolve(self) -> Provenanced[Any]:
        return Provenanced(value=None, source=Source.NONE, timing=Timing.LIVE)


class ResolverRegistry:
    def __init__(self, store, commute, retrieval) -> None:
        self._store = store
        self._dataset, self._osm = DatasetResolver(store), OsmResolver(commute)
        self._docs, self._none = DocumentResolver(retrieval), UnavailableResolver()

    def resolve_kind(self, kind: ClaimKind) -> Provenanced[Any]:
        # "anything else" is declared unavailable (spec §3.5).
        return self._none.resolve()

    def resolve(
        self, listing_id: str, question: str, commute_point: CommutePoint | None
    ) -> FactBundle:
        listing = self._store.listings[listing_id]
        b = FactBundle(listing_id=listing_id, locality=listing.locality)
        b.facts.update(self._dataset.resolve(listing_id))
        b.facts.update(self._osm.resolve(listing_id, commute_point))
        b.chunks = self._docs.resolve(listing.locality, question)
        return b
