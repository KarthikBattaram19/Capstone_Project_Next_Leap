"""The ONE embedding model, used identically at build time and question time (AD-10, spec §3.3)."""

from __future__ import annotations

import hashlib
import time
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


def tune_threads(
    candidates: tuple[int, ...] = (0, 1, 2),
    repeats: int = 5,
    probe: str = "Is it quiet at night near the first one?",
) -> dict[int, float]:
    """Time one question embedding per ONNX thread setting and keep the fastest session.

    `0` is ONNX Runtime's own default, which sizes the pool from the cores it can see. On
    a shared container those are the host's, not the CPU the container may use, and the
    threads fight: production spent 2.6-2.7 s warm in retrieval on 2026-09-17 against
    ~50 ms on a laptop. Measured where it runs instead of guessed; the timings are
    returned so the caller can log them. Thread count does not change the weights, so the
    manifest fingerprint and the embeddings are unaffected.
    """
    ef = get_embedding_function()
    ef._download_model_if_not_exists()
    ef(["warm up"])  # loads the tokenizer and the default session once
    ort = ef.ort
    onnx = next(Path(ef.DOWNLOAD_PATH).rglob("model.onnx"))
    timings: dict[int, float] = {}
    sessions: dict[int, object] = {}
    for n in candidates:
        so = ort.SessionOptions()
        so.log_severity_level = 3
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if n:
            so.intra_op_num_threads = n
            so.inter_op_num_threads = 1
        session = ort.InferenceSession(
            str(onnx), providers=["CPUExecutionProvider"], sess_options=so
        )
        # `model` is a functools.cached_property on ONNXMiniLM_L6_V2 (chromadb 1.5.9), so
        # the instance dict is where the cached session lives.
        ef.__dict__["model"] = session
        ef([probe])  # the first run of a session pays its own warm-up
        start = time.perf_counter()
        for _ in range(repeats):
            ef([probe])
        timings[n] = (time.perf_counter() - start) * 1000 / repeats
        sessions[n] = session
    ef.__dict__["model"] = sessions[min(timings, key=timings.get)]
    return timings
