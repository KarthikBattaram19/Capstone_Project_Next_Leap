"""(current requirements, one edit) → new requirements, or a question (arch §8.1, spec §6.5)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from dateutil import parser as dateparser

from scout.domain.constraints import CommutePoint, ConstraintEdit, ConstraintSet
from scout.domain.listing import BhkType, Furnishing, Parking, PropertyType
from scout.domain.money import rupees

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class Contradiction:
    field: str
    question: str


ReducerResult = ConstraintSet | Contradiction

_ENUMS = {
    "bhk_type": BhkType,
    "furnishing": Furnishing,
    "property_type": PropertyType,
    "parking_required": Parking,
}


# What renters actually say, mapped to the dataset's vocabulary. A voice system hears
# "semi", "car parking" and "flat"; the sheet says "semi_furnished", "four_wheeler" and
# "apartment". Job 1 is told to copy the words it heard rather than invent a value, so the
# mapping belongs here — and a word that is not in this table is still a question, never a
# guess.
_SYNONYMS: dict[str, dict[str, str]] = {
    "furnishing": {
        "semi": "SEMI_FURNISHED",
        "semifurnished": "SEMI_FURNISHED",
        "part_furnished": "SEMI_FURNISHED",
        "fully": "FULLY_FURNISHED",
        "full": "FULLY_FURNISHED",
        "furnished": "FULLY_FURNISHED",
        "bare": "UNFURNISHED",
        "empty": "UNFURNISHED",
        "none": "UNFURNISHED",
    },
    "parking_required": {
        "car": "FOUR_WHEELER",
        "car_parking": "FOUR_WHEELER",
        "four_wheeler_parking": "FOUR_WHEELER",
        "bike": "TWO_WHEELER",
        "scooter": "TWO_WHEELER",
        "two_wheeler_parking": "TWO_WHEELER",
        "car_and_bike": "BOTH",
        "any": "BOTH",
    },
    "property_type": {
        "flat": "APARTMENT",
        "apartments": "APARTMENT",
        "house": "INDEPENDENT_HOUSE",
        "independent": "INDEPENDENT_HOUSE",
        "independent_house_or_villa": "INDEPENDENT_HOUSE",
        "villas": "VILLA",
        "builder": "BUILDER_FLOOR",
    },
    "bhk_type": {"studio": "RK1", "rk": "RK1"},
}


# A figure with the unit the renter said still attached: "1274 sq ft", "1,274 square feet".
# Job 1 is told to copy what it heard rather than invent a value, so the unit arrives with
# it. The unit must be one we recognise — "3BHK" in a size field is a mis-extraction and
# stays a question rather than quietly becoming 3.
_NUMBER_WITH_UNIT = re.compile(
    r"^\s*(\d[\d,]*)\s*(?:sq\.?\s?ft\.?|sqft|square\s?f(?:ee|oo)t|feet|ft)?\s*$",
    re.IGNORECASE,
)


def _number(field: str, value) -> int:
    # bool is an int subclass, and a flag is not a figure: True falls through to the regex,
    # which does not match "True", and comes back as a question.
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    m = _NUMBER_WITH_UNIT.match(str(value))
    if m is None:
        raise ValueError(f"{field}: {value!r} is not a number")
    return int(m.group(1).replace(",", ""))


def _coerce(field: str, value) -> object:
    if value is None:
        return None
    if field in _ENUMS:
        cls = _ENUMS[field]
        token = str(value).strip().lower().replace(" ", "_")
        bare = token.replace("_", "")  # "2 BHK" -> "2bhk"
        for m in cls:
            if token in (m.value.lower(), m.name.lower()) or bare == m.value.lower().replace(
                "_", ""
            ):
                return m
        name = _SYNONYMS.get(field, {}).get(token)
        if name is not None:
            return cls[name]
        raise ValueError(f"{field}: {value!r} is not one of {[m.value for m in cls]}")
    if field in ("rent_max", "rent_min", "deposit_max", "square_footage_min"):
        return _number(field, value)
    if field == "lift_required":
        return str(value).strip().lower() in ("true", "yes", "1")
    if field == "available_by":
        return value if isinstance(value, date) else dateparser.parse(str(value)).date()
    if field == "commute":
        if not isinstance(value, CommutePoint):
            raise ValueError(
                "commute must be resolved to a CommutePoint by the orchestrator "
                "(store.place) before reducing"
            )
        return value
    return str(value)


def _unusable(field: str, value) -> str:
    return f"I didn't follow the {field.replace('_', ' ')} — I heard {value!r}. What should I use?"


def _check(c: ConstraintSet, field: str) -> Contradiction | None:
    if c.rent_min is not None and c.rent_max is not None and c.rent_max < c.rent_min:
        return Contradiction(
            field,
            f"You asked for rent at least {rupees(c.rent_min)} but at most "
            f"{rupees(c.rent_max)}. "
            "Which should I keep?",
        )
    if c.deposit_max is not None and c.deposit_max <= 0:
        return Contradiction(
            field, "A deposit limit of zero would exclude everything — what deposit is acceptable?"
        )
    if (c.rent_max is not None and c.rent_max <= 0) or (c.rent_min is not None and c.rent_min < 0):
        return Contradiction(
            field, "A rent limit of zero would exclude everything — what budget did you mean?"
        )
    if c.square_footage_min is not None and c.square_footage_min <= 0:
        return Contradiction(field, "What minimum size in square feet did you mean?")
    if c.available_by is not None and c.available_by < datetime.now(IST).date():
        return Contradiction(
            field,
            f"{c.available_by.isoformat()} is in the past — when do you want to move in?",
        )
    return None


def apply_edit(current: ConstraintSet, edit: ConstraintEdit) -> ReducerResult:
    f, op = edit.field, edit.op
    confirmed = current.confirmed - {f}  # a set on any field un-confirms it
    # Nothing in lane A catches a ValueError: an enum, date or amount Job 1 could not
    # normalise must end the turn in a question, not a stack trace (eval.md EC-RED-06/07).
    try:
        if f in ("localities", "amenities_required"):
            cur = set(getattr(current, f))
            val = _coerce(f, edit.value)
            if op in ("add", "set"):
                cur = {val} if op == "set" else cur | {val}
            elif op == "remove":
                cur -= {val}
            elif op == "clear":
                cur = set()
            new_val = tuple(sorted(cur)) if f == "localities" else frozenset(cur)
            nxt = current.with_(**{f: new_val, "confirmed": confirmed})
        else:
            nxt = current.with_(
                **{
                    f: None if op == "clear" else _coerce(f, edit.value),
                    "confirmed": confirmed,
                }
            )
    except (ValueError, TypeError, OverflowError, AttributeError):
        return Contradiction(f, _unusable(f, edit.value))
    return _check(nxt, f) or nxt


def apply_edits(current: ConstraintSet, edits: list[ConstraintEdit]) -> ReducerResult:
    c: ReducerResult = current
    for e in edits:
        c = apply_edit(c, e)
        if isinstance(c, Contradiction):
            return c
    return c


def confirm_all(current: ConstraintSet) -> ConstraintSet:
    return current.with_(confirmed=frozenset(current.set_fields()))
