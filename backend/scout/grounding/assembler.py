"""The last gate: an unciteable sentence never reaches the renter (arch §9.4)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from scout.conversation.job2 import Job2Sentence
from scout.domain.provenance import Provenanced
from scout.grounding.resolvers import FactBundle
from scout.grounding.support import supports

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

# A sentence ABOUT the documents — what the guides do not discuss, mention or say — is a
# gap spoken as prose. The gap is right; the sentence is not: nothing in the cited passage
# says it, and the renter hears every gap separately (spec §3.5). Suite C c-018 met one on
# 2026-09-15 ("the neighbourhood guides themselves don't actually discuss deposit amounts"),
# citing two passages, neither of which contains a word of it.
_META_GAP = re.compile(
    r"\b(?:guides?|documents?|passages?|sources?|articles?|pages?)\b[^.;]{0,40}?"
    r"\b(?:do not|don't|does not|doesn't|never|aren't|isn't|is not|are not)\b[^.;]{0,24}?"
    r"\b(?:discuss|mention|say|cover|address|state|include|talk|specify|give|provide|list"
    r"|contain|answer|explain|describe|specific|clear|explicit|silent)",
    re.IGNORECASE,
)


# The field names the renter hears. "I don't have a available from figure" is not a
# sentence anyone says out loud; the gap lines are humanised (spec §3.5).
_GAP_LABELS = {
    "available_from": "move-in date",
    "maintenance_charges": "maintenance charge",
    "maintenance_included": "maintenance",
    "square_footage": "size",
    "area_basis": "carpet-or-built-up",
    "bhk_type": "BHK",
    "society_name": "society name",
    "total_floors": "total floors",
    "property_type": "property type",
}


@dataclass(frozen=True)
class BoundClaim:
    text: str
    refs: list[str]
    facts: dict[str, Provenanced[Any]]


class ClaimAssembler:
    def __init__(self, bundle: FactBundle) -> None:
        self._b = bundle
        self._chunks = {c.citation_ref: c for c in bundle.chunks}
        # What the fence caught, by reason. A silent drop cannot answer the question
        # Docs/JOB2_SCORES.md asks — whether Job 2 is being fenced or is simply writing
        # uncitable prose. Counts only: the dropped sentence itself is never stored or
        # logged (spec §5.3).
        self.drops = {"no_refs": 0, "unknown_ref": 0, "gap_assertion": 0, "unsupported": 0}
        self.bound = 0

    @property
    def dropped(self) -> int:
        return sum(self.drops.values())

    def _drop(self, reason: str) -> None:
        self.drops[reason] += 1

    def bind(self, s: Job2Sentence) -> BoundClaim | None:
        if not s.fact_refs:
            self._drop("no_refs")
            return None
        known = self._b.all_refs()
        if any(r not in known for r in s.fact_refs):
            self._drop("unknown_ref")
            return None
        facts = {r: (self._b.facts.get(r) or self._chunks[r]) for r in s.fact_refs}
        # Talking only about gaps: keep it when it denies, drop it when it asserts.
        if (
            all(f.value is None for f in facts.values())
            and _ASSERTS_VALUE.search(s.text)
            and not _DENIES.search(s.text)
        ):
            self._drop("gap_assertion")
            return None
        # Talking about the documents instead of from them: a gap in prose.
        if _META_GAP.search(s.text):
            self._drop("gap_assertion")
            return None
        # A passage is cited for what it says. A sentence whose cited passage does not
        # support it is a mis-citation — right words, wrong ref — and Suite C fails it;
        # the renter never hears it either.
        if any(
            r in self._chunks and not supports(s.text, self._chunks[r].value.text)
            for r in s.fact_refs
        ):
            self._drop("unsupported")
            return None
        self.bound += 1
        return BoundClaim(text=s.text, refs=list(s.fact_refs), facts=facts)

    def render_gaps(self) -> list[str]:
        lines: list[str] = []
        for ref in self._b.gaps():
            kind, _, rest = ref.partition(":")
            name = _GAP_LABELS.get(rest.split(":")[-1], rest.split(":")[-1].replace("_", " "))
            if kind == "dataset":
                article = "an" if name[0].lower() in "aeiou" else "a"
                lines.append(f"I don't have {article} {name} figure for this listing.")
            elif kind == "osm":
                lines.append(
                    f"No {name.replace('nearest ', '')} found in the map data within the "
                    "search radius."
                )
        if not self._b.chunks:
            lines.append("Limited neighbourhood data available for this locality.")
        return lines
