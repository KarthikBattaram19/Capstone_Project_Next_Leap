"""Every claim cites something in the right locality, and the cited chunk supports the claim."""

from __future__ import annotations

from scout.contract.viewmodels import ExplanationVM
from scout.platform.artefacts import ArtefactStore

# Words that carry no evidence on their own.
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


def _supports(claim: str, chunk: str) -> bool:
    """A support test, not a plagiarism test: Job 2 paraphrases in short sentences (Task 2.12).

    (1) some three-word run is shared; failing that, (2) at least 2, and at least half, of the
    claim's content words (four letters or more, minus stopwords) appear in the chunk.
    """
    if _windows(claim, 3) & _windows(chunk, 3):
        return True
    words = [w.strip(_PUNCT) for w in claim.lower().split()]
    content = [w for w in words if len(w) >= 4 and w not in _STOPWORDS]
    if not content:
        return False
    haystack = chunk.lower()
    hits = sum(1 for w in content if w in haystack)
    return hits >= 2 and hits * 2 >= len(content)


def assert_every_claim_cites(
    explanation: ExplanationVM, store: ArtefactStore, locality: str
) -> None:
    refs = {c.ref for c in explanation.sources}
    for claim in explanation.claims:
        assert claim.citation_refs, f"uncited claim reached the renter: {claim.text!r}"
        for ref in claim.citation_refs:
            assert ref in refs, f"claim cites {ref} which is not in Sources"
            kind, _, rest = ref.partition(":")
            if kind == "guide":
                chunk = store.chunks[rest]
                assert chunk.locality == locality, (
                    f"cross-locality citation: {ref} is {chunk.locality}, expected {locality}"
                )
                assert _supports(claim.text, chunk.text), (
                    f"cited chunk does not support the claim:\n"
                    f" claim: {claim.text}\n chunk: {chunk.text[:200]}"
                )
            elif kind in ("dataset", "osm"):
                listing_id = rest.split(":")[0]
                assert store.listings[listing_id].locality == locality, (
                    f"cross-locality citation {ref}"
                )
            else:
                raise AssertionError(f"unknown citation kind in {ref}")
    for s in explanation.sources:
        assert s.label.strip() != "[OSM]", "a bare [OSM] citation is an automatic failure"
