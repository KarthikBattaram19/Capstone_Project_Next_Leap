"""One formatter returns all three renderings from the same object (arch §4.1)."""

from __future__ import annotations

from dataclasses import dataclass

from scout.domain.provenance import Distance, Method, Provenanced, Source, Timing

NOT_STATED = "not stated"


@dataclass(frozen=True)
class CommuteRendering:
    spoken: str
    badge: str
    full_label: str
    value_text: str


def _km(metres: int) -> str:
    # A listing 40 m from the metro reads "40 m", never "0.0 km" (the "never zero" rule, spec §3.1).
    if metres < 1000:
        return f"{metres} m"
    km = metres / 1000
    if km < 10:
        return f"{km:.1f} km"
    return f"{km:.0f} km"


def render_commute(fact: Provenanced[Distance], what: str) -> CommuteRendering:
    if fact.value is None:
        return CommuteRendering(
            spoken=f"I don't have a {what.lower()} distance for this listing.",
            badge="",
            full_label=_full_label(fact),
            value_text=NOT_STATED,
        )
    d = fact.value
    label = _full_label(fact)
    if fact.method is Method.ROUTED:
        badge = "by route"
        # The verb comes from the distance, never assumed — the same formatter
        # renders a 400 m metro and a 5 km hospital.
        if d.minutes is not None:
            if d.metres <= 1500:
                spoken = f"about a {d.minutes}-minute walk by route to the {what.lower()}"
            else:
                spoken = f"about {d.minutes} minutes by route to the {what.lower()}"
        else:
            spoken = f"about {_km(d.metres)} by route to the {what.lower()}"
        if fact.timing is Timing.LIVE and d.minutes is not None:
            spoken = f"about {d.minutes} minutes by route"
    else:
        badge = "straight-line"
        if fact.source is Source.COMPUTED or fact.timing is Timing.LIVE:
            spoken = (
                f"roughly {_km(d.metres)} straight-line from where you said you work — "
                "the real road distance will be longer"
            )
        else:
            spoken = f"about {_km(d.metres)} in a straight line to the {what.lower()}"
    return CommuteRendering(spoken=spoken, badge=badge, full_label=label, value_text=_km(d.metres))


def _full_label(fact: Provenanced[Distance]) -> str:
    if fact.source is Source.COMPUTED:
        return "[Straight-line from coordinates — computed now]"
    if fact.timing is Timing.LIVE:
        return "[OSM routing — live]"
    stamp = fact.as_of.isoformat() if fact.as_of else "unknown date"
    if fact.method is Method.STRAIGHT_LINE:
        return f"[OSM straight-line — precomputed {stamp}]"
    return f"[OSM routing — precomputed {stamp}]"
