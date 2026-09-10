"""The per-case drop table that goes into Docs/JOB2_SCORES.md after a run."""

from __future__ import annotations

from evals.harness.dropreport import render


def test_a_row_per_case_with_the_reasons_and_a_total():
    lines = render(
        {
            "c-001": {"bound": 4, "no_refs": 1, "unknown_ref": 0, "gap_assertion": 0},
            "c-002": {"bound": 3, "no_refs": 0, "unknown_ref": 2, "gap_assertion": 1},
        }
    )
    body = "\n".join(lines)

    assert "c-001" in body and "c-002" in body
    assert "unknown_ref=2" in body, body
    assert "7 bound, 4 dropped" in body, body


def test_a_case_that_dropped_nothing_still_reports_what_it_bound():
    body = "\n".join(render({"c-003": {"bound": 5}}))

    assert "c-003" in body and "5" in body
    assert "5 bound, 0 dropped" in body, body


def test_no_explanation_turns_says_so_rather_than_printing_an_empty_table():
    # A silent empty table reads like "nothing was dropped", which is a different claim.
    assert "no lane b turns" in "\n".join(render({})).lower()
