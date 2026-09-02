"""Merge adverts for the same flat: exact address OR coordinates within 50 m (spec §3.1)."""

from __future__ import annotations

import math

from scout.domain.listing import SCHEMA_FIELDS, ListingRecord

MERGE_RADIUS_M = 50.0


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def detail_score(rec: ListingRecord) -> int:
    return sum(1 for f in SCHEMA_FIELDS if getattr(rec, f) is not None)


def _agrees(a: ListingRecord, b: ListingRecord) -> bool:
    # Two adverts that disagree on what the flat *is* are not the same flat,
    # however close together they sit.
    rent_differs = a.rent is not None and b.rent is not None and a.rent != b.rent
    bhk_differs = a.bhk_type is not None and b.bhk_type is not None and a.bhk_type != b.bhk_type
    return not (rent_differs or bhk_differs)


def _same_flat(a: ListingRecord, b: ListingRecord) -> bool:
    # A shared society name in two localities is two societies.
    if a.locality != b.locality:
        return False
    if not _agrees(a, b):
        return False
    # Why the rent/BHK guard exists: a society name is a *building*, and a portal
    # usually pins every unit in a tower at one coordinate, so "same society" and
    # "within 50 m" both hold for twenty genuinely different flats. Requiring the
    # stated rent and BHK to agree keeps the spec's 50 m rule while stopping a
    # tower from collapsing into one listing (eval.md EC-DUP-03/04).
    if a.coordinates and b.coordinates:
        return (
            haversine_m(
                a.coordinates.lat, a.coordinates.lng, b.coordinates.lat, b.coordinates.lng
            )
            <= MERGE_RADIUS_M
        )
    # Exact-address arm when either coordinate is missing.
    if a.society_name and b.society_name:
        return a.society_name.strip().casefold() == b.society_name.strip().casefold()
    return False


def dedupe(records: list[ListingRecord]) -> tuple[list[ListingRecord], dict[str, list[str]]]:
    kept: list[ListingRecord] = []
    merged: dict[str, list[str]] = {}
    # Most-detailed first, then id, so the winner of any cluster is deterministic.
    for rec in sorted(records, key=lambda r: (-detail_score(r), r.id)):
        winner = next((k for k in kept if _same_flat(k, rec)), None)
        if winner is None:
            kept.append(rec)
        else:
            merged.setdefault(winner.id, []).append(rec.id)
    for k in kept:
        if k.id in merged:
            k.merged_from = merged[k.id]
    return sorted(kept, key=lambda r: r.id), merged
