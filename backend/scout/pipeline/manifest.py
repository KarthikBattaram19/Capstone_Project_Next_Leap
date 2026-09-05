"""Emit / update data/bundle/manifest.json. Each pipeline step adds its own fields (AD-2)."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scout.domain.listing import ListingRecord
from scout.domain.manifest import DatasetManifest
from scout.pipeline.curate import RULE
from scout.pipeline.gap_report import gap_report
from scout.pipeline.pii import assert_no_pii

BUNDLE = Path("data/bundle")
MANIFEST = BUNDLE / "manifest.json"


def _today_ist() -> date:
    # Every clock read in this codebase names its zone (spec §2.4, arch §10).
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


def load_manifest() -> DatasetManifest | None:
    if MANIFEST.exists():
        return DatasetManifest.model_validate_json(MANIFEST.read_text(encoding="utf-8"))
    return None


def save_manifest(m: DatasetManifest) -> None:
    # Committed output, so it gets the same last check as listings.json: locality names
    # and merged-record ids are the fields a leak could ride in on.
    payload = m.model_dump_json(indent=2)
    assert_no_pii(payload, where=str(MANIFEST))
    MANIFEST.write_text(payload, encoding="utf-8")


def from_import(
    availability_marker: str | None, raw_all: Path, merged: dict[str, list[str]]
) -> DatasetManifest:
    kept = [
        ListingRecord.model_validate(x)
        for x in json.loads((BUNDLE / "listings.json").read_text(encoding="utf-8"))
    ]
    raw = [
        ListingRecord.model_validate(x) for x in json.loads(raw_all.read_text(encoding="utf-8"))
    ]
    counts: dict[str, int] = {}
    for r in kept:
        counts[r.locality] = counts.get(r.locality, 0) + 1
    gap = gap_report(raw, availability_marker)
    existing = load_manifest()
    base = existing.model_dump() if existing else {}
    base.update(
        {
            "bundle_version": "1",
            "contract_version": "1",
            "scraped_on": max(r.scraped_on for r in kept) if kept else _today_ist(),
            "localities": counts,
            "total_listings": len(kept),
            "availability_marker": availability_marker,
            "curation_rule": RULE,
            "fields_published": gap.fields_published,
            "fields_missing": gap.fields_missing,
            "merged_records": merged,
        }
    )
    return DatasetManifest.model_validate(base)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--marker", required=True, help="the availability marker from SOURCE_NOTES.md, or NONE"
    )
    ap.add_argument("--raw", default="data/raw/listings_all.json")
    a = ap.parse_args()
    merged = {
        r["id"]: r["merged_from"]
        for r in json.loads((BUNDLE / "listings.json").read_text(encoding="utf-8"))
        if r.get("merged_from")
    }
    m = from_import(None if a.marker == "NONE" else a.marker, Path(a.raw), merged)
    save_manifest(m)
    print(m.model_dump_json(indent=2))
