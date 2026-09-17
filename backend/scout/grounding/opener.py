"""P8: the first sentence spoken on a 'why?' turn is built by code from facts already in hand."""

from __future__ import annotations

from scout.domain.commute_format import render_commute
from scout.domain.money import rupees
from scout.domain.provenance import Distance
from scout.grounding.resolvers import FactBundle


def build_opener(bundle: FactBundle, commute_point_name: str | None) -> str:
    lid = bundle.listing_id
    rent = bundle.facts.get(f"dataset:{lid}:rent")
    bhk = bundle.facts.get(f"dataset:{lid}:bhk_type")
    parts: list[str] = []

    if rent is not None and rent.value is not None and bhk is not None and bhk.value is not None:
        parts.append(f"It's {rupees(rent.value)} a month for a {bhk.value.value}")
    elif rent is not None and rent.value is not None:
        parts.append(f"It's {rupees(rent.value)} a month")

    metro = bundle.facts.get(f"osm:{lid}:nearest_metro")
    if metro is not None and isinstance(metro.value, Distance):
        parts.append(render_commute(metro, "Metro").spoken)

    work = next(
        (f for r, f in bundle.facts.items() if r.startswith("computed:") or r.endswith(":work")),
        None,
    )
    if work is not None and isinstance(work.value, Distance) and commute_point_name:
        parts.append(
            render_commute(work, "Work").spoken.replace(
                "where you said you work", commute_point_name
            )
        )

    first = ", ".join(parts) + "." if parts else "Here's what I have on this listing."
    # E1: the neighbourhood heading is not said here. Ended on "On the neighbourhood —", the
    # opener led straight into the gap line on production (2026-09-17) when no neighbourhood
    # claim followed; lane B says it before the first neighbourhood claim it speaks.
    tail = "" if bundle.chunks else " I have limited neighbourhood data for this locality."
    return first + tail


NEIGHBOURHOOD_HEADING = "On the neighbourhood —"


def is_neighbourhood_claim(refs: list[str], bundle: FactBundle) -> bool:
    """Whether a claim cites a guide passage: the only kind the neighbourhood heading leads."""
    passages = {c.citation_ref for c in bundle.chunks}
    return any(r in passages for r in refs)


def with_neighbourhood_heading(text: str) -> str:
    return f"{NEIGHBOURHOOD_HEADING} {text}"
