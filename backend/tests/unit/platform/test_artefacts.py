"""The artefact store loads the mini bundle and refuses every kind of mismatch, by name."""

import json
import shutil
from pathlib import Path

import pytest

from scout.domain.osm import OsmQuery
from scout.platform.artefacts import ArtefactStore
from scout.platform.boot import BootError

BUNDLE = Path(__file__).parents[2] / "fixtures" / "bundle_min"


def test_loads_and_wraps(bundle_min):
    # `bundle_min` is a copy: opening the committed store would modify its sqlite.
    store = ArtefactStore.load(bundle_min)
    assert set(store.localities) == {"Koramangala", "HSR Layout"}
    kor = next(x for x in store.listings.values() if x.locality == "Koramangala")
    assert kor.field("rent").value is not None
    assert store.osm(kor.id, OsmQuery.NEAREST_METRO).listing_id == kor.id
    assert store.collection("Koramangala").count() == 2


def test_version_mismatch_refuses(tmp_path):
    shutil.copytree(BUNDLE, tmp_path / "b")
    p = tmp_path / "b" / "manifest.json"
    m = json.loads(p.read_text(encoding="utf-8"))
    m["contract_version"] = "0"
    p.write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(BootError, match="contract_version"):
        ArtefactStore.load(str(tmp_path / "b"))


def test_missing_osm_row_refuses(tmp_path):
    shutil.copytree(BUNDLE, tmp_path / "b")
    p = tmp_path / "b" / "osm_facts.json"
    rows = json.loads(p.read_text(encoding="utf-8"))
    p.write_text(json.dumps(rows[1:]), encoding="utf-8")
    with pytest.raises(BootError, match="OSM"):
        ArtefactStore.load(str(tmp_path / "b"))


def test_embedding_model_mismatch_refuses(tmp_path):
    shutil.copytree(BUNDLE, tmp_path / "b")
    p = tmp_path / "b" / "manifest.json"
    m = json.loads(p.read_text(encoding="utf-8"))
    m["embedding_model_version"] = "onnx:sha256:deadbeef"
    p.write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(BootError, match="embedding"):
        ArtefactStore.load(str(tmp_path / "b"))
