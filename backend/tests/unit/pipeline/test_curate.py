from datetime import date

from scout.domain.listing import ListingRecord
from scout.pipeline.curate import curate
from scout.pipeline.gap_report import gap_report


def rec(i, locality, available=True, **fields):
    return ListingRecord(
        id=f"{locality[:3].lower()}-{i:03d}",
        source_url="u",
        scraped_on=date(2026, 9, 1),
        locality=locality,
        availability_status=available,
        **fields,
    )


def test_keeps_ten_best_populated_and_never_pads():
    thick = [rec(i, "Koramangala", rent=1, deposit=2, lift=True) for i in range(12)]
    thin = [rec(i, "HSR Layout", rent=1) for i in range(3)]
    unavailable = [rec(99, "HSR Layout", available=False, rent=1, deposit=2)]
    kept, rule = curate(thick + thin + unavailable)
    by_loc = {}
    for k in kept:
        by_loc.setdefault(k.locality, []).append(k)
    assert len(by_loc["Koramangala"]) == 10
    assert len(by_loc["HSR Layout"]) == 3  # real count, not padded
    assert all(k.availability_status for k in kept)
    assert "10" in rule and "fields" in rule


def test_null_availability_is_kept_not_treated_as_unavailable():
    # Spec §3.1: this source publishes no availability marker, so null can never
    # exclude a listing. Only an explicit False does.
    unknown = [rec(i, "Whitefield", available=None, rent=1) for i in range(2)]
    gone = [rec(9, "Whitefield", available=False, rent=1)]
    kept, rule = curate(unknown + gone)
    assert sorted(k.id for k in kept) == ["whi-000", "whi-001"]
    assert all(k.availability_status is None for k in kept)
    assert "not stated" in rule


def test_gap_report_names_unpublished_fields():
    g = gap_report([rec(1, "X", rent=1), rec(2, "X", rent=2)])
    assert "rent" in g.fields_published and "deposit" in g.fields_missing
