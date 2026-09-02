from datetime import date
from pathlib import Path

import pytest

from scout.domain.listing import AreaBasis, BhkType
from scout.pipeline.import_sheet import SheetSchemaError, import_sheet

SAMPLE = Path(__file__).parents[2] / "fixtures" / "listing_sample.xlsx"


def test_maps_every_supplied_column():
    recs = import_sheet(SAMPLE, date(2026, 9, 2))
    assert len(recs) == 5
    r = recs[0]
    assert isinstance(r.locality, str) and r.locality
    assert r.rent is not None
    assert r.deposit is not None
    assert r.bhk_type in set(BhkType)
    assert r.coordinates is not None


def test_fields_the_sheet_lacks_are_none_not_guessed():
    r = import_sheet(SAMPLE, date(2026, 9, 2))[0]
    assert r.amenities is None
    assert r.lift is None
    assert r.floor is None
    assert r.available_from is None
    assert r.availability_status is None
    assert r.maintenance_charges is None
    assert r.area_basis is AreaBasis.UNKNOWN


def test_a_bare_yes_never_becomes_a_four_wheeler_claim():
    for r in import_sheet(SAMPLE, date(2026, 9, 2)):
        assert r.parking is None
        assert r.parking_available in {True, False}


def test_balconies_is_imported():
    for r in import_sheet(SAMPLE, date(2026, 9, 2)):
        assert isinstance(r.balconies, int)


def test_output_carries_no_pii():
    dumped = "".join(r.model_dump_json() for r in import_sheet(SAMPLE, date(2026, 9, 2)))
    assert "@" not in dumped
    import re

    # no 10-digit mobiles anywhere
    assert not re.search(r"(?<!\d)[6-9]\d{9}(?!\d)", dumped)


def test_missing_required_column_is_an_error(tmp_path):
    from openpyxl import Workbook, load_workbook

    src = load_workbook(SAMPLE, read_only=True)[
        "Bangalore_Properties_List"
    ]
    rows = list(src.iter_rows(values_only=True))
    header = list(rows[0])
    drop = header.index("locality")
    wb = Workbook()
    ws = wb.active
    ws.title = "Bangalore_Properties_List"
    for row in rows:
        ws.append([c for i, c in enumerate(row) if i != drop])
    broken = tmp_path / "no_locality.xlsx"
    wb.save(broken)

    with pytest.raises(SheetSchemaError):
        import_sheet(broken, date(2026, 9, 2))
