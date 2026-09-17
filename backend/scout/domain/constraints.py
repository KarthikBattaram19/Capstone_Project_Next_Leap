"""What the renter asked for. Never edited in place — every change makes a new one (arch §8.1)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from typing import ClassVar, Literal

from scout.domain.listing import BhkType, Furnishing, Parking, PropertyType
from scout.domain.locality_names import one_per_place
from scout.domain.money import rupees


@dataclass(frozen=True)
class CommutePoint:
    name: str
    lat: float
    lng: float


def _text(v: object) -> str:
    """An enum reads as its value; a plain string reads as itself.

    Job 1 and the eval cases hand these fields through as strings before the reducer
    coerces them, so the readback must not assume the enum has already been built.
    """
    return str(getattr(v, "value", v))


@dataclass(frozen=True)
class ConstraintSet:
    localities: tuple[str, ...] = ()
    bhk_type: BhkType | None = None
    rent_max: int | None = None
    rent_min: int | None = None
    deposit_max: int | None = None
    furnishing: Furnishing | None = None
    property_type: PropertyType | None = None
    # True: any parking. A Parking kind: the kind she named, searched as any parking because
    # no listing in the dataset states the kind (voice fix batch E2, 2026-09-17).
    parking_required: Parking | bool | None = None
    lift_required: bool | None = None
    amenities_required: frozenset[str] = field(default_factory=frozenset)
    square_footage_min: int | None = None
    available_by: date | None = None
    commute: CommutePoint | None = None
    confirmed: frozenset[str] = field(default_factory=frozenset)

    HARD_FIELDS: ClassVar[tuple[str, ...]] = (
        "localities",
        "bhk_type",
        "rent_max",
        "rent_min",
        "deposit_max",
        "furnishing",
        "property_type",
        "parking_required",
        "lift_required",
        "amenities_required",
        "square_footage_min",
        "available_by",
    )

    def with_(self, **changes) -> "ConstraintSet":  # noqa: UP037 -- quoted in the addendum
        return replace(self, **changes)

    def is_empty(self) -> bool:
        return all(getattr(self, f) in (None, (), frozenset()) for f in self.HARD_FIELDS)

    def set_fields(self) -> list[str]:
        return [f for f in self.HARD_FIELDS if getattr(self, f) not in (None, (), frozenset())]

    def readback(self) -> list[str]:
        out: list[str] = []
        if self.localities:
            # One name per place: "TCPalya" searches T.C Palya and TC Palya (C1).
            out.append("in " + " or ".join(one_per_place(self.localities)))
        if self.bhk_type:
            out.append(f"a {_text(self.bhk_type)}")
        if self.rent_max is not None:
            out.append(f"rent up to {rupees(self.rent_max)}")
        if self.rent_min is not None:
            out.append(f"rent at least {rupees(self.rent_min)}")
        if self.deposit_max is not None:
            out.append(f"deposit up to {rupees(self.deposit_max)}")
        if self.furnishing:
            out.append(_text(self.furnishing).replace("_", " "))
        if self.property_type:
            out.append(_text(self.property_type).replace("_", " "))
        if self.parking_required:
            out.append("with parking")
        if self.lift_required:
            out.append("with a lift")
        for a in sorted(self.amenities_required):
            out.append(f"with {a}")
        if self.square_footage_min:
            out.append(f"at least {self.square_footage_min} sq ft")
        if self.available_by:
            out.append(f"available by {self.available_by.isoformat()}")
        if self.commute:
            out.append(f"commuting to {self.commute.name}")
        return out


@dataclass(frozen=True)
class ConstraintEdit:
    field: str
    op: Literal["set", "add", "remove", "clear"]
    value: str | int | None
