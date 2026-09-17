"""The last gate: an unciteable sentence never reaches the renter (arch §9.4)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from scout.conversation.job2 import Job2Sentence
from scout.domain.money import rupees
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
# sentence anyone says out loud; the gap lines are humanised (spec §3.5). The two
# maintenance fields are one gap to the renter: on production (2026-09-17) she heard "I
# don't have a maintenance charge figure ... I don't have a maintenance figure" back to back.
_GAP_LABELS = {
    "available_from": "move-in date",
    "maintenance_charges": "maintenance",
    "maintenance_included": "maintenance",
    "square_footage": "size",
    "area_basis": "carpet-or-built-up",
    "bhk_type": "BHK",
    "society_name": "society name",
    "total_floors": "total floors",
    "property_type": "property type",
    "restaurants_within_500m": "restaurants within 500 m",
}

# A sentence of at most this many words is short enough to say; a longer one stays on screen.
_SPOKEN_WORDS = 30


def speakable(text: str) -> bool:
    """E1: a raw field name ("maintenance_charges", "semi_furnished") is never said aloud."""
    return "_" not in text


_MONEY_FIELDS = ("rent", "deposit", "maintenance_charges")


def format_money(text: str, facts: dict[str, Provenanced[Any]]) -> str:
    """A cited amount said as "30000" or "Rs 30000" becomes "₹30,000" (E1).

    FACTS already hands Job 2 the formatted amount; this is the net for when it does not copy it.
    """
    for ref, f in facts.items():
        if ref.split(":")[-1] in _MONEY_FIELDS and isinstance(f.value, int) and f.value >= 1000:
            text = re.sub(
                rf"(?<![\d,])(?:₹\s*|Rs\.?\s*|INR\s*)?{f.value}(?![\d,])",
                rupees(f.value),
                text,
            )
    return text


def worth_saying(claim: BoundClaim, listing_id: str) -> bool:
    """Whether a bound claim is one of the few said aloud (E1); every claim is on screen."""
    if not speakable(claim.text) or len(claim.text.split()) > _SPOKEN_WORDS:
        return False
    if all(f.value is None for f in claim.facts.values()):
        return False  # a gap in prose: the one spoken gap line covers it
    # The opener already said the rent and the BHK.
    said = {f"dataset:{listing_id}:rent", f"dataset:{listing_id}:bhk_type"}
    return not set(claim.refs) <= said


def gap_label(name: str) -> str:
    """The words for a field or map query: `nearest_metro` -> "nearest metro"."""
    name = name.split(":")[-1].strip()
    return _GAP_LABELS.get(name, name.replace("_", " "))


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
        return BoundClaim(text=format_money(s.text, facts), refs=list(s.fact_refs), facts=facts)

    def _gap_items(self) -> list[tuple[str, str]]:
        """(label, screen line) per gap in the facts, one per label, in bundle order."""
        items: list[tuple[str, str]] = []
        seen: set[str] = set()
        for ref in self._b.gaps():
            kind, _, rest = ref.partition(":")
            field = rest.split(":")[-1]
            name = gap_label(field)
            if name in seen:
                continue
            if kind == "dataset":
                article = "an" if name[0].lower() in "aeiou" else "a"
                line = f"I don't have {article} {name} figure for this listing."
            elif kind == "osm" and field.startswith("nearest_"):
                line = (
                    f"No {name.replace('nearest ', '')} found in the map data within the "
                    "search radius."
                )
            elif kind == "osm":
                line = f"No {name} found in the map data."
            else:
                continue
            seen.add(name)
            items.append((name, line))
        return items

    def render_gaps(self) -> list[str]:
        lines = [line for _, line in self._gap_items()]
        if not self._b.chunks:
            lines.append("Limited neighbourhood data available for this locality.")
        return lines

    def _extra_gaps(self, job2_gaps: list[str]) -> list[tuple[str, str]]:
        """Job 2's own gaps list, minus what the facts already declare, in words.

        On production it returned raw names ("maintenance_charges maintenance_included
        parking lift ...") and they were read out as they stood.
        """
        known = {name.lower() for name, _ in self._gap_items()}
        out: list[tuple[str, str]] = []
        for g in job2_gaps:
            g = g.strip()
            if not g:
                continue
            if " " not in g:  # a field name or a ref
                name = gap_label(g)
                line = f"Not stated: {name}."
            else:
                name = g.replace("_", " ").rstrip(".")
                line = name[0].upper() + name[1:] + "."
            if name.lower() in known:
                continue
            known.add(name.lower())
            out.append((name, line))
        return out

    def all_gaps(self, job2_gaps: list[str]) -> list[str]:
        """Every gap for the screen, once each, never a raw field name."""
        return self.render_gaps() + [line for _, line in self._extra_gaps(job2_gaps)]

    def gap_summary(self, question: str, extra: list[str] | None = None) -> str | None:
        """The one spoken line about gaps (E1). The rest are on screen.

        It says "don't have": Suite C's null-row case listens for those words.
        """
        names = [n for n, _ in self._gap_items()]
        names += [n for n, _ in self._extra_gaps(extra or []) if len(n.split()) <= 4]
        if not names:
            return None
        q = question.lower()
        asked = [n for n in names if any(w in q for w in n.lower().split() if len(w) > 3)]
        ordered = asked + [n for n in names if n not in asked]
        if len(ordered) == 1:
            return f"I don't have the {ordered[0]} for this listing."
        return (
            f"I don't have some details for this listing, like the {ordered[0]} and {ordered[1]}."
        )
