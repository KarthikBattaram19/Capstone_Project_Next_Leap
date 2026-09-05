"""Up to 10 per locality — a ceiling, not a target (spec §1)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scout.domain.listing import ListingRecord
from scout.pipeline.dedupe import dedupe, detail_score
from scout.pipeline.pii import assert_no_pii

CAP = 10
# Spec §3.1 (availability filtering): a null availability_status can never exclude a
# listing — only an explicit False does. The 2026-09-05 sheet does publish a marker
# (`availability_status`), but the rule is written for any source, marker or not.
RULE = (
    "Records marked unavailable are dropped; a null availability (a source that publishes no "
    "marker) is kept and shown as not stated; duplicates merged (exact society/address or "
    f"coordinates within 50 m, most-detailed record wins); where a locality exceeds {CAP}, "
    f"keep the {CAP} records with the most non-null schema fields, ties broken by newest "
    "as-of date then id."
)


def curate(records: list[ListingRecord]) -> tuple[list[ListingRecord], str]:
    available = [r for r in records if r.availability_status is not False]
    kept, _merged = dedupe(available)
    by_loc: dict[str, list[ListingRecord]] = {}
    for r in kept:
        by_loc.setdefault(r.locality, []).append(r)
    out: list[ListingRecord] = []
    for loc in sorted(by_loc):
        # Most fields first, then newest as-of date (negated ordinal), then id.
        ranked = sorted(
            by_loc[loc], key=lambda r: (-detail_score(r), -r.scraped_on.toordinal(), r.id)
        )
        out.extend(ranked[:CAP])
    return out, RULE


def write_bundle(records: list[ListingRecord], out: Path) -> None:
    """Serialise, check for personal data, then write. In that order.

    `data/bundle/listings.json` is the one pipeline output that is committed, so it is
    the last place a leak could become public. The importer already refuses to read the
    sheet's three PII columns and strips text on the way in; this is defence in depth
    against a hand-edited raw file, and it fails the build rather than publishing.
    """
    payload = json.dumps([r.model_dump(mode="json") for r in records], indent=2)
    assert_no_pii(payload, where=str(out))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--inp", default="data/raw/listings_all.json")
    ap.add_argument("--out", default="data/bundle/listings.json")
    a = ap.parse_args()
    raw = [
        ListingRecord.model_validate(x) for x in json.loads(Path(a.inp).read_text(encoding="utf-8"))
    ]
    kept, rule = curate(raw)
    write_bundle(kept, Path(a.out))
    counts: dict[str, int] = {}
    for r in kept:
        counts[r.locality] = counts.get(r.locality, 0) + 1
    print(json.dumps({"rule": rule, "counts": counts, "total": len(kept)}, indent=2))
