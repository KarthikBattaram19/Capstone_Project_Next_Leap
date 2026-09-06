"""ChromaDB, embedded, persisted; one collection per locality — partition, not filter (AD-4, AD-9)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import chromadb

from scout.domain.guides import GuideChunk
from scout.pipeline.embedding import get_embedding_function

CHUNKS = Path("data/bundle/chunks.json")
PERSIST = Path("data/bundle/chroma")


def collection_name(locality: str) -> str:
    # Chroma names must be 3–63 chars of [a-z0-9._-]; "loc_" + up to 50 keeps that.
    return "loc_" + re.sub(r"[^a-z0-9]+", "_", locality.lower()).strip("_")[:50]


def build_index(
    chunks: list[GuideChunk], persist_dir: str, localities: list[str] | None = None
) -> dict[str, int]:
    # Signatures verified against chromadb 1.5.9 on 2026-09-06:
    #   PersistentClient(path=...); list_collections() -> Sequence[Collection] (use .name);
    #   delete_collection(name); create_collection(name, ..., metadata=, embedding_function=);
    #   Collection.add(ids=, metadatas=, documents=).
    client = chromadb.PersistentClient(path=persist_dir)
    ef = get_embedding_function()

    by_loc: dict[str, list[GuideChunk]] = {}
    for ch in chunks:
        by_loc.setdefault(ch.locality, []).append(ch)
    # A locality with no usable guide source still gets its partition; the gap is a
    # fact, not a missing file.
    for loc in localities or []:
        by_loc.setdefault(loc, [])

    # collection_name() truncates, so two localities could map to one collection. A
    # silent merge would be cross-locality contamination by construction: refuse
    # before touching the store.
    owner: dict[str, str] = {}
    for loc in by_loc:
        name = collection_name(loc)
        if name in owner:
            raise ValueError(
                f"localities {owner[name]!r} and {loc!r} both map to collection {name!r}"
            )
        owner[name] = loc

    for c in client.list_collections():
        if c.name.startswith("loc_"):
            client.delete_collection(c.name)

    counts: dict[str, int] = {}
    for locality, items in by_loc.items():
        col = client.create_collection(
            collection_name(locality),
            embedding_function=ef,
            metadata={"hnsw:space": "cosine", "locality": locality},
        )
        if items:  # Chroma rejects an empty add
            col.add(
                ids=[c.id for c in items],
                documents=[c.text for c in items],
                metadatas=[
                    {
                        "locality": c.locality,
                        "title": c.title,
                        "url": c.url,
                        "position": c.position,
                        "fetched_on": c.fetched_on.isoformat(),
                    }
                    for c in items
                ],
            )
        counts[locality] = len(items)
    return counts


if __name__ == "__main__":
    from scout.pipeline.manifest import from_index, load_manifest, save_manifest

    chunks = [GuideChunk.model_validate(x) for x in json.loads(CHUNKS.read_text(encoding="utf-8"))]
    m = load_manifest()
    assert m is not None, "run the import half first"
    counts = build_index(chunks, str(PERSIST), localities=list(m.localities))
    print(json.dumps(counts, indent=2))
    save_manifest(from_index(counts))
