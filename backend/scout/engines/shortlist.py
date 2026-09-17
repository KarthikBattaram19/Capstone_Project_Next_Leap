"""Plain code. No model participates in any decision here (arch §8, A4)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from scout.contract.outcome import UnmetConstraint
from scout.domain.constraints import ConstraintSet
from scout.domain.listing import Listing, Parking
from scout.domain.locality_names import one_per_place, variant_key
from scout.domain.money import rupees
from scout.domain.shortlist import Exclusion, Shortlist, ShortlistEntry
from scout.pipeline.dedupe import haversine_m

Available = Callable[[str], bool]


@dataclass(frozen=True)
class Match:
    soft_hits: int


@dataclass(frozen=True)
class Unknown:
    field: str


@dataclass(frozen=True)
class ExcludedV:
    field: str
    reason: str


Verdict = Match | Unknown | ExcludedV

# The constraint field -> the listing field it reads, where the two names differ.
_LISTING_FIELD = {
    "rent_max": "rent",
    "rent_min": "rent",
    "deposit_max": "deposit",
    "parking_required": "parking_available",
    "lift_required": "lift",
    "square_footage_min": "square_footage",
    "available_by": "available_from",
    "amenities_required": "amenities",
}


def _parking_ok(have: Parking, need: Parking) -> bool:
    return have is Parking.BOTH or have is need


def _is_constrained(c: ConstraintSet, field: str) -> bool:
    """Is this field actually asked for?

    It must not test falsiness: in Python `0 == False`, so the obvious
    `v not in (None, (), frozenset(), False)` reads a rent_max of 0 as *no budget at all*
    and silently returns the whole dataset (eval.md EC-SL-09). A zero cap is already caught
    as a contradiction in the reducer; this keeps it caught if it arrives by another route.
    """
    v = getattr(c, field)
    if v is None or v == () or v == frozenset():
        return False
    # An explicit "I don't need a lift" (or parking) constrains nothing.
    return not (field in ("lift_required", "parking_required") and v is False)


def evaluate(listing: Listing, c: ConstraintSet) -> Verdict:
    f = listing.field
    checks: list[tuple[str, Callable[[], bool | None]]] = [
        ("localities", lambda: listing.locality in c.localities if c.localities else None),
        ("bhk_type", lambda: _eq(f("bhk_type").value, c.bhk_type)),
        ("rent_max", lambda: _le(f("rent").value, c.rent_max)),
        ("rent_min", lambda: _ge(f("rent").value, c.rent_min)),
        ("deposit_max", lambda: _le(f("deposit").value, c.deposit_max)),
        ("furnishing", lambda: _eq(f("furnishing").value, c.furnishing)),
        ("property_type", lambda: _eq(f("property_type").value, c.property_type)),
        (
            "parking_required",
            lambda: _parking(f("parking").value, f("parking_available").value, c.parking_required),
        ),
        ("lift_required", lambda: _lift(f("lift").value, c.lift_required)),
        ("square_footage_min", lambda: _ge(f("square_footage").value, c.square_footage_min)),
        ("available_by", lambda: _le(f("available_from").value, c.available_by)),
        ("amenities_required", lambda: _amenities(f("amenities").value, c.amenities_required)),
    ]

    for field, check in checks:
        if not _is_constrained(c, field):
            continue
        result = check()
        if result is None:  # the listing does not say — its own group, never a match
            return Unknown(field)
        if result is False:
            return ExcludedV(field, _reason(listing, field, c))

    soft = 0
    if f("lift").value:
        soft += 1
    deposit, rent = f("deposit").value, f("rent").value
    if deposit is not None and rent and deposit <= 3 * rent:
        soft += 1
    return Match(soft_hits=soft)


def _eq(value, want) -> bool | None:
    if want is None or value is None:
        return None
    return value is want


def _le(value, cap) -> bool | None:
    if cap is None or value is None:
        return None
    return value <= cap


def _ge(value, floor) -> bool | None:
    if floor is None or value is None:
        return None
    return value >= floor


def _parking(kind, available, need) -> bool | None:
    """A parking requirement means parking is available (E2, decision 3).

    A listing that states its kind is read by kind when she named one; otherwise whether
    parking is available decides. `kind` is null on every listing in today's dataset.
    """
    if not need:
        return None
    if kind is not None:
        if kind is Parking.NONE:
            return False
        return True if need is True else _parking_ok(kind, need)
    return available


def _lift(value, need) -> bool | None:
    if not need or value is None:
        return None
    return value is True


def _amenities(value, need) -> bool | None:
    if not need or value is None:
        return None
    return all(any(a.lower() in x.lower() for x in value) for a in need)


def _reason(listing: Listing, field: str, c: ConstraintSet) -> str:
    if field == "localities":
        v = listing.locality
    else:
        v = listing.field(_LISTING_FIELD.get(field, field)).value
    return f"{field} not met ({v})"


def _rank_key(listing: Listing, soft: int):
    rent = listing.field("rent").value
    # More soft hits first, a null rent after every stated rent, then rent asc, then id.
    return (-soft, rent is None, rent if rent is not None else 0, listing.id)


def build(listings: list[Listing], c: ConstraintSet, available: Available) -> Shortlist:
    matched: list[tuple[Listing, int]] = []
    unknown: dict[str, list[str]] = {}
    excluded: list[Exclusion] = []
    for listing in listings:
        if not available(listing.id):
            excluded.append(Exclusion(listing.id, "no longer available", "availability"))
            continue
        v = evaluate(listing, c)
        if isinstance(v, Match):
            matched.append((listing, v.soft_hits))
        elif isinstance(v, Unknown):
            unknown.setdefault(v.field, []).append(listing.id)
        else:
            excluded.append(Exclusion(listing.id, v.reason, v.field))
    matched.sort(key=lambda t: _rank_key(*t))
    return Shortlist(
        matched=tuple(ShortlistEntry(x.id, i + 1) for i, (x, _) in enumerate(matched)),
        unknown={k: tuple(v) for k, v in unknown.items()},
        excluded=tuple(excluded),
    )


def refine(
    previous: Shortlist, listings: list[Listing], c: ConstraintSet, available: Available
) -> Shortlist:
    fresh = build(listings, c, available)
    now_matching = set(fresh.order)
    kept = [i for i in previous.order if i in now_matching]  # previous order, untouched
    appended = [i for i in fresh.order if i not in set(kept)]  # new ones, in rank order
    order = kept + appended
    return Shortlist(
        matched=tuple(ShortlistEntry(i, n + 1) for n, i in enumerate(order)),
        unknown=fresh.unknown,
        excluded=fresh.excluded,
    )


def reorder(previous: Shortlist, key: Callable[[str], float | None]) -> Shortlist:
    """The same listings in another order she asked for (F1): ascending `key`, a listing
    with no value last, ties kept in their current order. Nothing is added or dropped."""
    current = previous.order
    order = sorted(current, key=lambda i: (key(i) is None, key(i) or 0))
    return Shortlist(
        matched=tuple(ShortlistEntry(i, n + 1) for n, i in enumerate(order)),
        unknown=previous.unknown,
        excluded=previous.excluded,
    )


def binding_constraints(s: Shortlist, c: ConstraintSet) -> list[UnmetConstraint]:
    counts: dict[str, int] = {}
    for x in s.excluded:
        counts[x.field] = counts.get(x.field, 0) + 1
    out: list[UnmetConstraint] = []
    for field, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        val = getattr(c, field, None)
        out.append(
            UnmetConstraint(field=field, value=str(val), binding=(n == max(counts.values())))
        )
    return out


def nearest_localities(
    chosen: list[str] | tuple[str, ...],
    places: dict[str, dict],
    covered: list[str],
    k: int = 2,
) -> list[str]:
    """The k covered localities whose centres are closest to any chosen locality's centre.

    Straight-line distance between the build-time centres in places.json (Task 2.7). A
    chosen locality with no centre yields nothing: "nearby" is a claim about geography and
    is never made without a measurement behind it.
    """
    centres = [places[n] for n in chosen if n in places]
    if not centres:
        return []
    # Another spelling of a chosen place is that place, not a neighbour ("nearby Domluru"
    # for a search in Domlur); and each neighbour is named once, in its plainest spelling.
    taken = {variant_key(n) for n in chosen}
    scored = []
    for name in covered:
        if variant_key(name) in taken or name not in places:
            continue
        p = places[name]
        d = min(haversine_m(c["lat"], c["lng"], p["lat"], p["lng"]) for c in centres)
        scored.append((d, name))
    return one_per_place(name for _, name in sorted(scored))[:k]


def without(c: ConstraintSet, field: str) -> ConstraintSet:
    """The same requirements with one of them dropped."""
    empty = {"localities": (), "amenities_required": frozenset()}
    return c.with_(**{field: empty.get(field)})


# How a dropped requirement is named aloud. Never a field name (production, 2026-09-17).
_DROP_LABELS = {
    "localities": "the area",
    "bhk_type": "the BHK",
    "rent_max": "the budget",
    "rent_min": "the minimum rent",
    "deposit_max": "the deposit limit",
    "furnishing": "furnishing",
    "property_type": "the property type",
    "parking_required": "parking",
    "lift_required": "the lift",
    "square_footage_min": "the size",
    "available_by": "the move-in date",
}


def suggest_relaxations(
    s: Shortlist,
    c: ConstraintSet,
    nearby: list[str],
    not_stated: dict[str, int] | None = None,
) -> list[str]:
    """Suggest only, in plain words.

    `nearby` comes from nearest_localities - never from list order, which once offered the
    alphabetically first names as "nearby" (production, 2026-09-17) - and the caller passes
    it only when the place is what rules everything out. `not_stated` maps a requirement to
    how many listings would appear if it were dropped that do not mention it; the offer is
    made only when that number is known and above zero.
    """
    tips: list[str] = []
    if any(x.field == "rent_max" for x in s.excluded) and c.rent_max:
        tips.append(f"go up to {rupees(int(c.rent_max * 1.2 // 1000 * 1000))}")
    if any(x.field == "localities" for x in s.excluded):
        others = one_per_place(loc for loc in nearby if loc not in c.localities)[:2]
        if others:
            tips.append("look nearby in " + " or ".join(others))
    there = " there" if c.localities else ""
    for field, n in (not_stated or {}).items():
        if n <= 0 or field not in s.unknown:
            continue
        if field == "amenities_required":
            label = " and ".join(sorted(c.amenities_required))
        else:
            label = _DROP_LABELS.get(field, "that requirement")
        verb = "don't" if n > 1 else "doesn't"
        tips.append(
            f"leave out {label} - {n} listing{'s' if n > 1 else ''}{there} {verb} mention it"
        )
    return tips
