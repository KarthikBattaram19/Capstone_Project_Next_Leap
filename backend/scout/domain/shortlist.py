"""Three groups, not one list (arch §8.2). Order is fixed; grouping on screen never reorders it."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ShortlistEntry:
    listing_id: str
    rank: int
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Exclusion:
    listing_id: str
    reason: str  # "rent 45000 > 40000" | "no longer available" | …
    field: str  # the constraint field that excluded it


@dataclass(frozen=True)
class Shortlist:
    matched: tuple[ShortlistEntry, ...] = ()
    unknown: dict[str, tuple[str, ...]] = field(default_factory=dict)  # field -> listing ids
    excluded: tuple[Exclusion, ...] = ()

    @property
    def order(self) -> list[str]:
        return [e.listing_id for e in self.matched]

    def is_empty(self) -> bool:
        return not self.matched
