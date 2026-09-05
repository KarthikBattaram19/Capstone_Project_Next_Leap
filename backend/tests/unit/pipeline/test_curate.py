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


def test_the_bundle_write_refuses_to_publish_pii(tmp_path):
    # The importer strips PII and never reads the three PII columns, so a leak can only
    # arrive through a hand-edited raw file. This is the last check before the bundle —
    # the one output that IS committed — reaches disk.
    import pytest

    from scout.pipeline.curate import write_bundle
    from scout.pipeline.pii import PiiLeakError

    out = tmp_path / "listings.json"
    leaked = rec(1, "Koramangala", rent=1, society_name="Ramesh 9876543210")
    with pytest.raises(PiiLeakError):
        write_bundle([leaked], out)
    assert not out.exists()  # nothing half-written


def test_the_bundle_write_emits_the_records_when_clean(tmp_path):
    import json

    from scout.pipeline.curate import write_bundle

    out = tmp_path / "listings.json"
    write_bundle([rec(1, "Koramangala", rent=35000)], out)
    written = json.loads(out.read_text(encoding="utf-8"))
    assert [r["id"] for r in written] == ["kor-001"]
    assert written[0]["rent"] == 35000


def test_the_manifest_write_is_guarded_too(monkeypatch, tmp_path):
    # manifest.json is committed alongside listings.json; it carries locality names and
    # merged-record ids, so it gets the same last check.
    import pytest

    from scout.domain.manifest import DatasetManifest
    from scout.pipeline import manifest as mod
    from scout.pipeline.pii import PiiLeakError

    target = tmp_path / "manifest.json"
    monkeypatch.setattr(mod, "MANIFEST", target)
    m = DatasetManifest(
        bundle_version="1",
        contract_version="1",
        scraped_on=date(2026, 9, 5),
        localities={"Ramesh 9876543210": 1},
        total_listings=1,
        availability_marker="availability_status",
        curation_rule="r",
        fields_published=["rent"],
        fields_missing=["floor"],
    )
    with pytest.raises(PiiLeakError):
        mod.save_manifest(m)
    assert not target.exists()


def test_a_merge_winner_dropped_by_the_cap_takes_its_merged_ids_with_it():
    # Dedupe runs before the cap, so a record can absorb a duplicate and then be cut by
    # the 10-per-locality ceiling. Its merged_from goes with it, and the manifest — which
    # reconstructs merged_records from the bundle file — therefore reports merges among
    # BUNDLED records only, not everything dedupe did. On the 2026-09-05 sheet that is
    # 42 winners in the manifest against 112 dedupe actually performed. This is the
    # intended reading (the manifest describes the bundle), pinned so it is not
    # "fixed" into a claim about the whole import by accident.
    from scout.pipeline.dedupe import dedupe

    # Eleven thick records, so the cap of 10 bites; the thinnest of them absorbs a twin.
    thick = [rec(i, "Koramangala", rent=1, deposit=2, lift=True) for i in range(10)]
    # Same society, same locality, same rent, no coordinates -> dedupe's exact-address arm.
    winner = rec(50, "Koramangala", rent=3, society_name="Prestige Acropolis", balconies=1)
    twin = rec(51, "Koramangala", rent=3, society_name="Prestige Acropolis")
    every = thick + [winner, twin]

    deduped, merged = dedupe(every)
    assert merged == {"kor-050": ["kor-051"]}  # dedupe did merge them
    assert len(deduped) == 11

    kept, _rule = curate(every)
    assert len(kept) == 10
    assert "kor-050" not in {k.id for k in kept}  # the cap dropped the winner
    assert all(not k.merged_from for k in kept)  # so the bundle records no merge at all
