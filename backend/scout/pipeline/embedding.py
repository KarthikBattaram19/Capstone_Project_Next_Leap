"""The ONE embedding model, used identically at build time and question time (AD-10, spec §3.3)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

EMBEDDING_MODEL = "all-MiniLM-L6-v2"

_ef: ONNXMiniLM_L6_V2 | None = None


def get_embedding_function() -> ONNXMiniLM_L6_V2:
    global _ef
    if _ef is None:
        # Set explicitly — never rely on Chroma's default moving under us.
        _ef = ONNXMiniLM_L6_V2()
    return _ef


def model_fingerprint() -> str:
    """sha256 of the ONNX weights on disk: the manifest's embedding_model_version."""
    ef = get_embedding_function()
    # Both private names verified against chromadb 1.5.9 on 2026-09-06:
    # `_download_model_if_not_exists()` fetches and unpacks the archive on first use,
    # and `DOWNLOAD_PATH` is the directory it unpacks into (see Task 1.1 Step 3).
    ef._download_model_if_not_exists()
    onnx = next(Path(ef.DOWNLOAD_PATH).rglob("model.onnx"))
    return "onnx:sha256:" + hashlib.sha256(onnx.read_bytes()).hexdigest()[:16]
