"""The artefact store: read-only at runtime, written only by the offline build (arch §6.3)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import chromadb

from scout.contract import CONTRACT_VERSION
from scout.domain.guides import GuideChunk
from scout.domain.listing import Listing, ListingRecord
from scout.domain.manifest import DatasetManifest
from scout.domain.osm import OSM_QUERY_SET, OsmFactRecord, OsmQuery
from scout.pipeline.build_index import collection_name
from scout.pipeline.embedding import EMBEDDING_MODEL, get_embedding_function, model_fingerprint
from scout.platform.boot import BootError


@dataclass
class ArtefactStore:
    manifest: DatasetManifest
    listing_records: dict[str, ListingRecord]
    listings: dict[str, Listing]
    _osm: dict[tuple[str, OsmQuery], OsmFactRecord]
    chunks: dict[str, GuideChunk]
    chroma: chromadb.ClientAPI
    places: dict[str, dict]

    @property
    def localities(self) -> list[str]:
        return sorted(self.manifest.localities)

    def place(self, name: str) -> "CommutePoint | None":  # noqa: F821, UP037 -- imported below
        """Resolve a named place to coordinates. No live geocoding inside a turn (A3)."""
        from scout.domain.constraints import CommutePoint

        key = next((k for k in self.places if k.lower() == name.strip().lower()), None)
        if key is None:
            return None
        return CommutePoint(
            name=key, lat=float(self.places[key]["lat"]), lng=float(self.places[key]["lng"])
        )

    def place_names(self) -> list[str]:
        return sorted(self.places)

    def osm(self, listing_id: str, query: OsmQuery) -> OsmFactRecord:
        # KeyError if absent, on purpose: load() proved every listing x query is present.
        return self._osm[(listing_id, query)]

    def collection(self, locality: str):
        # Signature verified against chromadb 1.5.9 on 2026-09-07:
        #   get_collection(name, embedding_function=DefaultEmbeddingFunction(), data_loader=None)
        # The embedding function is passed explicitly so a query embeds with the ONE model
        # the index was built with, never Chroma's default (AD-10).
        return self.chroma.get_collection(
            collection_name(locality), embedding_function=get_embedding_function()
        )

    @classmethod
    def load(cls, bundle_dir: str) -> "ArtefactStore":  # noqa: UP037 -- quoted in the addendum
        d = Path(bundle_dir)
        try:
            manifest = DatasetManifest.model_validate_json(
                (d / "manifest.json").read_text(encoding="utf-8")
            )
            records = [
                ListingRecord.model_validate(x)
                for x in json.loads((d / "listings.json").read_text(encoding="utf-8"))
            ]
            osm_rows = [
                OsmFactRecord.model_validate(x)
                for x in json.loads((d / "osm_facts.json").read_text(encoding="utf-8"))
            ]
            chunks = [
                GuideChunk.model_validate(x)
                for x in json.loads((d / "chunks.json").read_text(encoding="utf-8"))
            ]
            # The build-time commute-point table (Task 2.7). Required: a bundle without it
            # would make "I work in Whitefield" unanswerable mid-turn instead of at boot.
            places = json.loads((d / "places.json").read_text(encoding="utf-8"))
            # PersistentClient(path=...) verified against chromadb 1.5.9 on 2026-09-07.
            chroma = chromadb.PersistentClient(path=str(d / "chroma"))
        except Exception as e:
            # Any unreadable file is a boot failure, named.
            raise BootError(f"artefact bundle at {d} failed to load: {e}") from e

        if manifest.contract_version != CONTRACT_VERSION:
            raise BootError(
                f"bundle contract_version {manifest.contract_version} != backend {CONTRACT_VERSION}"
            )
        if manifest.total_listings != len(records):
            raise BootError(
                f"manifest says {manifest.total_listings} listings, "
                f"listings.json has {len(records)}"
            )

        osm = {(r.listing_id, r.query): r for r in osm_rows}
        missing = [
            (r.id, q.query.value)
            for r in records
            for q in OSM_QUERY_SET
            if (r.id, q.query) not in osm
        ]
        if missing:
            raise BootError(
                f"OSM facts do not cover every listing × query; first missing: {missing[:3]}"
            )

        # One read of the weights on disk (a sha256 over ~90 MB), used for both the test
        # and the message.
        fingerprint = model_fingerprint()
        if manifest.embedding_model != EMBEDDING_MODEL or (
            manifest.embedding_model_version != fingerprint
        ):
            raise BootError(
                f"embedding model on disk ({EMBEDDING_MODEL} {fingerprint}) != manifest "
                f"({manifest.embedding_model} {manifest.embedding_model_version})"
            )

        # Names only, never count(): with chromadb 1.5.9's default HNSW cache, count() on
        # more than ~40 populated collections in one process breaks later queries on the
        # first (Task 1.2 status). list_collections() -> Sequence[Collection], verified.
        names = {c.name for c in chroma.list_collections()}
        for loc in manifest.localities:
            if collection_name(loc) not in names:
                raise BootError(f"guide index has no collection for locality {loc!r}")

        return cls(
            manifest=manifest,
            listing_records={r.id: r for r in records},
            listings={r.id: Listing.from_record(r) for r in records},
            _osm=osm,
            chunks={c.id: c for c in chunks},
            chroma=chroma,
            places=places,
        )
