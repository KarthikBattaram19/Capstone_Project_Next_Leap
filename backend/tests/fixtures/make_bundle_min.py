"""Build `bundle_min/`: a 2-locality, 3-listing bundle the unit tests boot against.

Run once from the repo root and commit the output (it is small):

    backend/.venv/Scripts/python.exe backend/tests/fixtures/make_bundle_min.py

Deterministic apart from the UUID directory names Chroma gives its HNSW segments. The dates
are fixed constants, not clock reads: a fixture that changed with the calendar would make
every test run a different bundle.

What the shape is for:
- three listings: kor-001 (deposit=None) and kor-002 in Koramangala, hsr-001 in HSR Layout
  (parking=None on kor-002 only) — all three carry coordinates and a rent;
- the full OSM row set, 3 x 8 = 24 rows: kor-002's nearest_metro row is null (OSM found
  nothing), hsr-001's nearest_park is STRAIGHT_LINE, the count row carries only `count`, and
  every other row is ROUTED with a distance;
- four chunks, two per locality. Both Koramangala chunks name "Forum Mall" and no HSR chunk
  does; one HSR chunk deliberately says "Koramangala" so a contamination probe that only
  matched on the locality's name would be fooled — the probe must go by the partition.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(
    0, str(HERE.parents[1])
)  # backend/, so `scout` imports without the editable install

import chromadb
import onnxruntime

from scout.domain.guides import GuideChunk
from scout.domain.listing import (
    BhkType,
    Coordinates,
    Furnishing,
    ListingRecord,
    Parking,
    PropertyType,
    SocietyType,
)
from scout.domain.manifest import DatasetManifest
from scout.domain.osm import OSM_QUERY_SET, OsmFactRecord, OsmQuery
from scout.domain.provenance import Method
from scout.pipeline.build_index import build_index
from scout.pipeline.embedding import EMBEDDING_MODEL, model_fingerprint

OUT = HERE / "bundle_min"
SCRAPED_ON = date(2026, 9, 5)
FETCHED_ON = date(2026, 9, 6)
OSM_ON = date(2026, 9, 7)

LISTINGS = [
    ListingRecord(
        id="kor-001",
        source_url="file://fixture#kor-001",
        scraped_on=SCRAPED_ON,
        locality="Koramangala",
        bhk_type=BhkType.BHK2,
        bedrooms=2,
        bathrooms=2,
        balconies=1,
        rent=42000,
        deposit=None,  # the deposit gap
        property_type=PropertyType.APARTMENT,
        furnishing=Furnishing.SEMI_FURNISHED,
        square_footage=1100,
        total_floors=6,
        parking=Parking.FOUR_WHEELER,
        parking_available=True,
        availability_status=True,
        society_name="Sobha Iris",
        society_type=SocietyType.GATED,
        coordinates=Coordinates(lat=12.9352, lng=77.6245),
    ),
    ListingRecord(
        id="kor-002",
        source_url="file://fixture#kor-002",
        scraped_on=SCRAPED_ON,
        locality="Koramangala",
        bhk_type=BhkType.BHK1,
        bedrooms=1,
        bathrooms=1,
        balconies=0,
        rent=24000,
        deposit=100000,
        property_type=PropertyType.BUILDER_FLOOR,
        furnishing=Furnishing.UNFURNISHED,
        square_footage=650,
        total_floors=3,
        parking=None,  # the parking gap
        parking_available=None,
        availability_status=True,
        society_name=None,
        society_type=SocietyType.NON_GATED,
        coordinates=Coordinates(lat=12.9279, lng=77.6271),
    ),
    ListingRecord(
        id="hsr-001",
        source_url="file://fixture#hsr-001",
        scraped_on=SCRAPED_ON,
        locality="HSR Layout",
        bhk_type=BhkType.BHK3,
        bedrooms=3,
        bathrooms=3,
        balconies=2,
        rent=55000,
        deposit=250000,
        property_type=PropertyType.APARTMENT,
        furnishing=Furnishing.FULLY_FURNISHED,
        square_footage=1650,
        total_floors=12,
        parking=Parking.BOTH,
        parking_available=True,
        availability_status=True,
        society_name="Prestige Ferns",
        society_type=SocietyType.GATED,
        coordinates=Coordinates(lat=12.9116, lng=77.6389),
    ),
]

# (listing, query) -> the fixed answer. Anything not listed here is ROUTED at 100 m steps.
NULL_ROWS = {("kor-002", OsmQuery.NEAREST_METRO)}
STRAIGHT_ROWS = {("hsr-001", OsmQuery.NEAREST_PARK): ("Agara Lake Park", 1180)}
COUNTS = {"kor-001": 14, "kor-002": 9, "hsr-001": 6}


def osm_rows() -> list[OsmFactRecord]:
    rows: list[OsmFactRecord] = []
    for li, listing in enumerate(LISTINGS):
        for qi, spec in enumerate(OSM_QUERY_SET):
            key = (listing.id, spec.query)
            if key in NULL_ROWS:
                rows.append(
                    OsmFactRecord(listing_id=listing.id, query=spec.query, retrieved_on=OSM_ON)
                )
            elif spec.kind == "count":
                rows.append(
                    OsmFactRecord(
                        listing_id=listing.id,
                        query=spec.query,
                        count=COUNTS[listing.id],
                        retrieved_on=OSM_ON,
                    )
                )
            elif key in STRAIGHT_ROWS:
                name, metres = STRAIGHT_ROWS[key]
                rows.append(
                    OsmFactRecord(
                        listing_id=listing.id,
                        query=spec.query,
                        name=name,
                        distance_m=metres,
                        method=Method.STRAIGHT_LINE,
                        retrieved_on=OSM_ON,
                    )
                )
            else:
                rows.append(
                    OsmFactRecord(
                        listing_id=listing.id,
                        query=spec.query,
                        name=f"{spec.label} near {listing.id}",
                        distance_m=300 + 100 * (li * len(OSM_QUERY_SET) + qi),
                        method=Method.ROUTED,
                        retrieved_on=OSM_ON,
                    )
                )
    return rows


CHUNKS = [
    GuideChunk(
        id="koramangala-0-0",
        locality="Koramangala",
        title="Koramangala",
        url="https://en.wikipedia.org/wiki/Koramangala",
        text=(
            "Koramangala is a residential locality in south-east Bengaluru, laid out in eight "
            "blocks along the Inner Ring Road and Hosur Road. Forum Mall on Hosur Road anchors "
            "the 7th Block end, and the 5th Block strip is lined with cafes, pubs and start-up "
            "offices that stay busy late into the evening."
        ),
        position=0,
        fetched_on=FETCHED_ON,
    ),
    GuideChunk(
        id="koramangala-0-1",
        locality="Koramangala",
        title="Koramangala",
        url="https://en.wikipedia.org/wiki/Koramangala",
        text=(
            "The blocks nearest Forum Mall and the Sony World junction are the noisiest at "
            "night; the 3rd and 4th Blocks behind the National Games Village are quieter, "
            "tree-lined and mostly independent houses. Koramangala has no Namma Metro "
            "station yet; the nearest are on the Pink Line, still under construction."
        ),
        position=1,
        fetched_on=FETCHED_ON,
    ),
    GuideChunk(
        id="hsr-layout-0-0",
        locality="HSR Layout",
        title="HSR Layout",
        url="https://en.wikipedia.org/wiki/HSR_Layout",
        text=(
            "HSR Layout (Hosur-Sarjapur Road Layout) is a planned residential suburb in "
            "south-east Bengaluru, divided into seven sectors around a central BDA complex "
            "and the 27th Main commercial strip. Agara Lake and its park lie on the northern "
            "edge; the sectors are quiet after dark and popular with families."
        ),
        position=0,
        fetched_on=FETCHED_ON,
    ),
    # Deliberate contamination bait: an HSR chunk that says "Koramangala". A probe that only
    # looked for the neighbour's name in the retrieved text would flag this passage even
    # though it belongs to HSR Layout; the real test is which collection answered.
    GuideChunk(
        id="hsr-layout-0-1",
        locality="HSR Layout",
        title="HSR Layout",
        url="https://en.wikipedia.org/wiki/HSR_Layout",
        text=(
            "HSR Layout borders Koramangala to the north-west across the Agara junction, "
            "and Bommanahalli and Sarjapur Road to the south and east. Buses on the Outer "
            "Ring Road connect it to Silk Board and the IT corridor; the nearest metro is "
            "Silk Board on the Yellow Line."
        ),
        position=1,
        fetched_on=FETCHED_ON,
    ),
]

LOCALITIES = ["Koramangala", "HSR Layout"]


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()

    (OUT / "listings.json").write_text(
        json.dumps([r.model_dump(mode="json") for r in LISTINGS], indent=1), encoding="utf-8"
    )
    rows = osm_rows()
    assert len(rows) == len(LISTINGS) * len(OSM_QUERY_SET)
    (OUT / "osm_facts.json").write_text(
        json.dumps([r.model_dump(mode="json") for r in rows], indent=1), encoding="utf-8"
    )
    (OUT / "chunks.json").write_text(
        json.dumps([c.model_dump(mode="json") for c in CHUNKS], indent=1), encoding="utf-8"
    )
    counts = build_index(CHUNKS, str(OUT / "chroma"), localities=LOCALITIES)

    by_loc: dict[str, int] = {}
    for r in LISTINGS:
        by_loc[r.locality] = by_loc.get(r.locality, 0) + 1
    manifest = DatasetManifest(
        bundle_version="1",
        contract_version="1",
        scraped_on=SCRAPED_ON,
        localities=by_loc,
        total_listings=len(LISTINGS),
        availability_marker="availability_status column: Yes = available, No = unavailable",
        curation_rule="fixture: hand-written, nothing dropped",
        fields_published=["locality", "rent", "coordinates"],
        fields_missing=["maintenance_charges", "amenities"],
        osm_query_set=[q.query.value for q in OSM_QUERY_SET],
        osm_index_date=OSM_ON,
        embedding_model=EMBEDDING_MODEL,
        embedding_model_version=model_fingerprint(),
        chunk_count_per_locality=counts,
        guide_sources={loc: [c.url for c in CHUNKS if c.locality == loc][:1] for loc in LOCALITIES},
        chromadb_version=chromadb.__version__,
        onnxruntime_version=onnxruntime.__version__,
    )
    (OUT / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    print(
        f"wrote {OUT}: {len(LISTINGS)} listings, {len(rows)} OSM rows, {len(CHUNKS)} chunks, {counts}"
    )


if __name__ == "__main__":
    main()
