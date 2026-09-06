"""Semantic chunking: split where the meaning shifts, never mid-sentence (AD-9)."""

from __future__ import annotations

import math
import re
from collections.abc import Callable

Embed = Callable[[list[str]], list[list[float]]]

# Splits after sentence-ending punctuation followed by whitespace.
_SENT = re.compile(r"(?<=[.!?])\s+")


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _words(s: str) -> int:
    return len(s.split())


def _cap(chunk: str, max_words: int) -> list[str]:
    """Split an over-long chunk at sentence boundaries only."""
    out: list[str] = []
    cur: list[str] = []
    for sent in _SENT.split(chunk):
        if cur and _words(" ".join(cur + [sent])) > max_words:
            out.append(" ".join(cur))
            cur = []
        cur.append(sent)
    if cur:
        out.append(" ".join(cur))
    return out


def chunk_document(
    text: str,
    *,
    embed: Embed,
    min_words: int = 60,
    max_words: int = 220,
    drift: float = 0.35,
) -> list[str]:
    paras = _paragraphs(text)
    if not paras:
        return []
    vecs = embed(paras)
    chunks: list[str] = []
    cur = [paras[0]]
    for i in range(1, len(paras)):
        shift = 1.0 - _cos(vecs[i - 1], vecs[i])
        too_long = _words(" ".join(cur + [paras[i]])) > max_words
        long_enough = _words(" ".join(cur)) >= min_words
        if (shift > drift and long_enough) or too_long:
            chunks.append(" ".join(cur))
            cur = [paras[i]]
        else:
            cur.append(paras[i])
    chunks.append(" ".join(cur))
    pieces = [piece for ch in chunks for piece in _cap(ch, max_words)]
    # A document's last paragraph is often a few words. Left alone it would be a chunk
    # far below min_words; fold it into the previous chunk when the pair still fits.
    if (
        len(pieces) >= 2
        and _words(pieces[-1]) < min_words
        and _words(pieces[-2]) + _words(pieces[-1]) <= max_words
    ):
        pieces[-2:] = [pieces[-2] + " " + pieces[-1]]
    return pieces
