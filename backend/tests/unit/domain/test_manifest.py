from datetime import date

from scout.domain.manifest import DatasetManifest
from scout.domain.osm import OSM_QUERY_SET, OsmQuery


def test_query_set_is_fixed_and_named():
    ids = [q.query for q in OSM_QUERY_SET]
    assert OsmQuery.NEAREST_METRO in ids and len(ids) == len(set(ids))


def test_manifest_round_trips_and_records_the_sign_off_items():
    m = DatasetManifest(
        bundle_version="1",
        contract_version="1",
        scraped_on=date(2026, 9, 1),
        localities={"Koramangala": 10, "HSR Layout": 7},
        total_listings=17,
        availability_marker="css: .status-available",
        curation_rule="most fields present, then newest",
        fields_published=["rent", "locality"],
        fields_missing=["maintenance_charges"],
        merged_records={"kor-001": ["kor-014"]},
        osm_query_set=[q.value for q in OsmQuery],
        osm_index_date=date(2026, 9, 2),
        embedding_model="all-MiniLM-L6-v2",
        embedding_model_version="onnx:sha256:abc",
        chunk_count_per_locality={"Koramangala": 12, "HSR Layout": 9},
        guide_sources={"Koramangala": ["https://en.wikipedia.org/wiki/Koramangala"]},
        chromadb_version="x",
        onnxruntime_version="y",
    )
    again = DatasetManifest.model_validate_json(m.model_dump_json())
    assert again == m and again.total_listings == sum(again.localities.values())


def test_total_that_disagrees_with_the_per_locality_counts_is_refused():
    import pytest

    with pytest.raises(ValueError, match="total_listings must equal"):
        DatasetManifest(
            bundle_version="1",
            contract_version="1",
            scraped_on=date(2026, 9, 1),
            localities={"Koramangala": 10},
            total_listings=11,
            availability_marker=None,
            curation_rule="most fields present, then newest",
            fields_published=["rent"],
            fields_missing=[],
        )
