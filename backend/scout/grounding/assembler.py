"""The last gate: an unciteable sentence never reaches the renter (arch §9.4)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from scout.conversation.job2 import Job2Sentence
from scout.domain.provenance import Provenanced
from scout.grounding.resolvers import FactBundle

# A sentence that carries a number, a price, a distance or a yes/no is asserting a value.
_ASSERTS_VALUE = re.compile(r"\d|₹|km|minute|yes|no\b", re.IGNORECASE)

# The marks of a sentence that DENIES rather than asserts. Declaring a gap is an answer,
# not a fabrication: "There is no metro within 3 km in the map data" cites a null row, trips
# _ASSERTS_VALUE on "3" and "km", and is nonetheless correct (eval.md EC-J2-08).
_DENIES = re.compile(
    r"\b(?:no|not|none|nothing|never|without|unavailable|unknown)\b"
    r"|isn't|aren't|doesn't|don't"
    r"|not stated|don't have|do not have",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BoundClaim:
    text: str
    refs: list[str]
    facts: dict[str, Provenanced[Any]]


class ClaimAssembler:
    def __init__(self, bundle: FactBundle) -> None:
        self._b = bundle
        self._chunks = {c.citation_ref: c for c in bundle.chunks}

    def bind(self, s: Job2Sentence) -> BoundClaim | None:
        if not s.fact_refs:
            return None
        known = self._b.all_refs()
        if any(r not in known for r in s.fact_refs):
            return None
        facts = {r: (self._b.facts.get(r) or self._chunks[r]) for r in s.fact_refs}
        # Talking only about gaps: keep it when it denies, drop it when it asserts.
        if (
            all(f.value is None for f in facts.values())
            and _ASSERTS_VALUE.search(s.text)
            and not _DENIES.search(s.text)
        ):
            return None
        return BoundClaim(text=s.text, refs=list(s.fact_refs), facts=facts)

    def render_gaps(self) -> list[str]:
        lines: list[str] = []
        for ref in self._b.gaps():
            kind, _, rest = ref.partition(":")
            name = rest.split(":")[-1].replace("_", " ")
            if kind == "dataset":
                lines.append(f"I don't have a {name} figure for this listing.")
            elif kind == "osm":
                lines.append(
                    f"No {name.replace('nearest ', '')} found in the map data within the "
                    "search radius."
                )
        if not self._b.chunks:
            lines.append("Limited neighbourhood data available for this locality.")
        return lines
