"""Every fact that can reach a renter is wrapped in Provenanced[T] (arch §4)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Generic, TypeVar

T = TypeVar("T")


class Source(str, Enum):
    DATASET = "DATASET"
    OSM = "OSM"
    GUIDE = "GUIDE"
    COMPUTED = "COMPUTED"
    NONE = "NONE"


class Method(str, Enum):
    ROUTED = "ROUTED"
    STRAIGHT_LINE = "STRAIGHT_LINE"


class Timing(str, Enum):
    PRECOMPUTED = "PRECOMPUTED"
    LIVE = "LIVE"


class ProvenanceError(ValueError):
    """Raised when a fact would be representable without its provenance."""


@dataclass(frozen=True)
class Distance:
    metres: int
    minutes: int | None = None


@dataclass(frozen=True)
class Provenanced(Generic[T]):  # noqa: UP046 -- addendum specifies Generic + TypeVar
    value: T | None
    source: Source
    timing: Timing
    method: Method | None = None
    as_of: date | None = None
    citation_ref: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.value, Distance) and self.method is None:
            raise ProvenanceError("a distance cannot exist without its method")
        if self.source is Source.NONE and self.value is not None:
            raise ProvenanceError("source NONE means 'I don't have that'; it carries no value")

    @property
    def is_gap(self) -> bool:
        return self.value is None
