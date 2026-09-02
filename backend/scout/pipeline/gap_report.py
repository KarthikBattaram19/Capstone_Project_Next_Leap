"""Which of spec §3.1's fields the source actually publishes — reported, never guessed around."""

from __future__ import annotations

from scout.domain.listing import SCHEMA_FIELDS, ListingRecord
from scout.domain.manifest import GapReport


def gap_report(
    records: list[ListingRecord], availability_marker: str | None = None
) -> GapReport:
    published = [f for f in SCHEMA_FIELDS if any(getattr(r, f) is not None for r in records)]
    missing = [f for f in SCHEMA_FIELDS if f not in published]
    return GapReport(
        availability_marker=availability_marker,
        fields_published=published,
        fields_missing=missing,
    )
