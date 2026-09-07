"""The checked-in schema is exactly what the code exports (CI diffs the two byte for byte)."""

import json
from pathlib import Path

from scout.contract.export import export_schema

CHECKED_IN = Path(__file__).parents[3].parent / "contract" / "v1.schema.json"


def test_checked_in_schema_matches_code():
    assert json.loads(CHECKED_IN.read_text(encoding="utf-8")) == export_schema(), (
        "run: python -m scout.contract.export > contract/v1.schema.json"
    )


def test_checked_in_bytes_match_the_module_output():
    # CI runs `python -m scout.contract.export | diff - contract/v1.schema.json` on Linux:
    # a byte comparison, so indentation, key order, LF line ends and the absent trailing
    # newline all matter, not only the parsed document.
    expected = json.dumps(export_schema(), indent=2, sort_keys=True).encode("utf-8")
    assert CHECKED_IN.read_bytes() == expected


def test_schema_names_every_outcome_shape():
    defs = export_schema()["$defs"]
    for name in (
        "Answered",
        "Empty",
        "Degraded",
        "Failed",
        "NeedsInput",
        "CardVM",
        "CommuteRowVM",
        "CitationVM",
    ):
        assert name in defs
