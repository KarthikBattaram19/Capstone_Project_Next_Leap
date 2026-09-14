"""Does a cited passage actually support the sentence that cites it?

A support test, not a plagiarism test: Job 2 paraphrases in short sentences (Task 2.12).
Either some three-word run is shared, or at least two — and at least half — of the
sentence's content words (four letters or more, minus stopwords) appear in the passage.

Suite C applies the same test from the outside (evals/assertions/grounding.py, kept
separate on purpose: the suite must not import the code it measures). The assembler
applies it here so a mis-cited sentence never reaches the renter in the first place — on
2026-09-15 Job 2 twice restated one HSR Layout passage word for word and cited the
neighbouring one (c-008).
"""

from __future__ import annotations

_STOPWORDS = frozenset(
    {
        "this",
        "that",
        "with",
        "from",
        "have",
        "here",
        "there",
        "which",
        "what",
        "about",
        "area",
        "areas",
        "locality",
        "listing",
        "flat",
        "your",
        "will",
        "been",
        "more",
        "most",
        "very",
        "some",
        "they",
        "their",
        "than",
        "then",
        "into",
        "also",
        "many",
        "much",
    }
)

_PUNCT = ".,;:!?\"'()[]{}—–-"


def _windows(s: str, n: int) -> set[str]:
    words = s.lower().split()
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def supports(claim: str, passage: str) -> bool:
    if _windows(claim, 3) & _windows(passage, 3):
        return True
    words = [w.strip(_PUNCT) for w in claim.lower().split()]
    content = [w for w in words if len(w) >= 4 and w not in _STOPWORDS]
    if not content:
        return False
    haystack = passage.lower()
    hits = sum(1 for w in content if w in haystack)
    return hits >= 2 and hits * 2 >= len(content)
