"""Selects a handful of chunks already in the index — from ONE collection (AD-9, arch §9.2)."""

from __future__ import annotations

from scout.domain.guides import GuideChunk
from scout.domain.provenance import Provenanced, Source, Timing
from scout.platform import telemetry


class Retrieval:
    def __init__(self, store) -> None:
        self._store = store

    def retrieve(self, locality: str, question: str, k: int = 4) -> list[Provenanced[GuideChunk]]:
        if locality not in self._store.manifest.localities:
            return []
        with telemetry.span(telemetry.RETRIEVAL):
            col = self._store.collection(locality)  # the other localities are not searched
            count = col.count()
            if count == 0:
                # A locality with no guide source has an empty partition. That is an
                # expected state, not an error: the explanation says so instead.
                return []
            res = col.query(query_texts=[question], n_results=min(k, count))
            out: list[Provenanced[GuideChunk]] = []
            for cid in res["ids"][0]:
                ch = self._store.chunks[cid]
                out.append(
                    Provenanced(
                        value=ch,
                        source=Source.GUIDE,
                        timing=Timing.PRECOMPUTED,
                        as_of=ch.fetched_on,
                        citation_ref=f"guide:{ch.id}",
                    )
                )
            return out
