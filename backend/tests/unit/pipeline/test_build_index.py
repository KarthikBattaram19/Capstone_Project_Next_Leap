from datetime import date

import chromadb
import pytest

from scout.domain.guides import GuideChunk
from scout.pipeline.build_index import build_index, collection_name


def chunk(loc, i, text):
    return GuideChunk(
        id=f"{loc[:3].lower()}-0-{i}",
        locality=loc,
        title=f"{loc} guide",
        url="u",
        text=text,
        position=i,
        fetched_on=date(2026, 9, 1),
    )


def test_a_locality_with_no_guides_still_gets_its_partition(tmp_path):
    # Without this, a locality with no usable guide source makes the backend refuse
    # to boot (Task 1.4's check that every manifest locality has a collection).
    counts = build_index(
        [chunk("Koramangala", 0, "pubs and nightlife")],
        str(tmp_path),
        localities=["Koramangala", "HSR Layout"],
    )
    assert counts == {"Koramangala": 1, "HSR Layout": 0}
    client = chromadb.PersistentClient(path=str(tmp_path))
    names = {c.name for c in client.list_collections()}
    assert collection_name("HSR Layout") in names
    assert client.get_collection(collection_name("HSR Layout")).count() == 0


def test_one_collection_per_locality_and_no_cross_talk(tmp_path):
    chunks = [
        chunk("Koramangala", 0, "pubs and nightlife"),
        chunk("Indiranagar", 0, "100 feet road shopping"),
    ]
    counts = build_index(chunks, str(tmp_path))
    assert counts == {"Koramangala": 1, "Indiranagar": 1}
    client = chromadb.PersistentClient(path=str(tmp_path))
    names = {c.name for c in client.list_collections()}
    assert names == {collection_name("Koramangala"), collection_name("Indiranagar")}
    kor = client.get_collection(collection_name("Koramangala"))
    assert kor.count() == 1
    assert kor.get()["metadatas"][0]["locality"] == "Koramangala"


def test_two_localities_sharing_a_collection_name_is_refused(tmp_path):
    # A silent merge of two localities into one collection would be cross-locality
    # contamination by construction, so the build must stop and name both.
    assert collection_name("HSR Layout") == collection_name("HSR-Layout")
    with pytest.raises(ValueError, match=r"HSR Layout.*HSR-Layout|HSR-Layout.*HSR Layout"):
        build_index([], str(tmp_path), localities=["HSR Layout", "HSR-Layout"])
    client = chromadb.PersistentClient(path=str(tmp_path))
    assert client.list_collections() == []


def test_collection_name_is_a_valid_chroma_name():
    name = collection_name("Assetz Earth & Essence")
    assert name == "loc_assetz_earth_essence"
    long = collection_name("x" * 80)
    assert long.startswith("loc_") and len(long) == 54
