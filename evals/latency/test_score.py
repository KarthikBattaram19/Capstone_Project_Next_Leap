import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from evals.latency.score import TARGETS_MS, render_table, score

REPO = Path(__file__).resolve().parents[2]

L2, L3, L4, L5 = (TARGETS_MS[k] for k in ("L2", "L3", "L4", "L5"))
FAST_L0, FAST_L1 = TARGETS_MS["L0"] * 0.4, TARGETS_MS["L1"] * 0.8


def turn(tt, l0, l1, l2, l4=None, l5=None):
    row = {"turn_type": tt, "L0": l0, "L1": l1}
    row["L2" if tt == "A" else "L3"] = l2
    if l4 is not None:
        row["L4"] = l4
    if l5 is not None:
        row["L5"] = l5
    return row


def test_a_lone_outlier_is_caught_by_the_2x_rule_not_by_p99():
    # 99 fast turns and one slow one. p99 is "the time within which 99 of every 100
    # requests finish" (plan §2), so nearest-rank p99 of 100 samples is the 99th, and
    # the lone outlier does NOT move it - that is p99 working, not failing. The single
    # slow request is the 2× rule's job. The two rules cover different failures, and
    # this asserts both halves of that split. Fixtures scale from TARGETS_MS so the
    # assertion is about the rules, not about whichever budget the spec holds today.
    fast, outlier = L2 * 0.8, L2 * 2.2
    lines = [turn("A", FAST_L0, FAST_L1, fast, l4=L4 * 0.6) for _ in range(99)]
    lines.append(turn("A", FAST_L0, FAST_L1, outlier, l4=L4 * 0.6))
    rep = score(lines)
    assert rep.p99["A"]["L2"] == fast  # the outlier does not drag p99 up
    assert rep.passed is False
    assert any("2×" in v for v in rep.violations)  # ... but it is still a hard failure


def test_a_slow_bulk_fails_on_p99_with_no_2x_violation():
    # The other half: every request slower than target but none past 2×. p99 must fail
    # on its own, or a uniformly slow system would pass.
    slow = L2 * 1.2
    lines = [turn("A", FAST_L0, FAST_L1, slow, l4=L4 * 0.6) for _ in range(100)]
    rep = score(lines)
    assert rep.p99["A"]["L2"] == slow
    assert rep.passed is False
    assert not any("2×" in v for v in rep.violations)
    assert any("p99" in v and "L2" in v for v in rep.violations)


def test_type_b_pass_does_not_cover_type_a():
    lines = [turn("B", FAST_L0, FAST_L1, L3 * 0.7, l5=L5 * 0.5) for _ in range(30)]
    lines += [turn("A", FAST_L0, FAST_L1, L2 * 1.1) for _ in range(30)]
    rep = score(lines)
    assert rep.passed is False and rep.p99["B"]["L3"] <= TARGETS_MS["L3"]


def test_cold_start_rows_are_counted_apart_and_never_scored():
    # A cold start is far past 2× every target (Gate L measured L1 3,150 on a fresh
    # container). Spec §5.2 P1: reported separately, never inside these numbers - so it
    # must neither raise a violation nor move the p99 of the warm rows.
    warm = [turn("A", FAST_L0, FAST_L1, L2 * 0.8, l4=L4 * 0.6) for _ in range(20)]
    cold = turn("A", FAST_L0, TARGETS_MS["L1"] * 3, L2 * 3, l4=L4 * 3)
    cold["cold_start"] = True
    rep = score([*warm, cold])
    assert rep.passed is True
    assert rep.counts == {"A": 20}
    assert rep.cold_start_counts == {"A": 1}
    assert rep.cold_start["A"]["L1"] == [TARGETS_MS["L1"] * 3]
    assert rep.p99["A"]["L2"] == L2 * 0.8


def test_cold_start_false_is_an_ordinary_row():
    row = turn("A", FAST_L0, FAST_L1, L2 * 2.5)
    row["cold_start"] = False
    rep = score([row])
    assert rep.cold_start_counts == {} and any("2×" in v for v in rep.violations)


@pytest.mark.parametrize("stage", ["L6", "L7", "L8"])
def test_l6_l7_l8_rows_keep_their_targets(stage):
    assert (TARGETS_MS["L6"], TARGETS_MS["L7"], TARGETS_MS["L8"]) == (5000, 5000, 30000)
    target = TARGETS_MS[stage]
    ok = score([{"turn_type": "A", stage: target * 0.9}])
    assert ok.passed and ok.p99["A"][stage] == target * 0.9
    over = score([{"turn_type": "A", stage: target * 2.1}])
    assert any(f"A/{stage}: single request" in v for v in over.violations)


def test_server_traces_give_components_not_stage_scores():
    # The shape telemetry.Trace.to_json writes (see latency/evals-*.jsonl): a trace cannot
    # see end-of-speech, so it yields component timings, no L-stage and no violation.
    tr = {
        "turn_id": "cd034381d5f2",
        "turn_type": "B",
        "cold_start": False,
        "spans": [{"name": "retrieval", "start_ms": 5.2, "end_ms": 272.7}],
        "marks": [
            {"name": "tts.first_byte", "at_ms": 900.0},
            {"name": "llm.first_token", "at_ms": 2641.8},
            {"name": "tts.first_byte", "at_ms": 3000.0},
        ],
    }
    rep = score([tr, {**tr, "cold_start": True}])
    assert rep.p99 == {} and rep.passed
    assert rep.counts == {"B": 1} and rep.cold_start_counts == {"B": 1}
    c = rep.components["B"]
    assert c["retrieval"] == {"n": 1, "median": 267.5, "p99": 267.5}
    assert c["tts.first_byte"]["median"] == 900.0  # the first sentence's byte, not the second


def test_table_lists_rows_violations_and_cold_start():
    cold = turn("A", FAST_L0, FAST_L1, L2 * 3)
    cold["cold_start"] = True
    rep = score([turn("A", FAST_L0, FAST_L1, L2 * 2.5), cold])
    text = "\n".join(render_table(rep))
    assert f"| A | L2 | 1 | {L2 * 2.5:.0f} | {L2} | NO |" in text
    assert "Violations (2):" in text
    assert "Cold-start rows, reported separately and not scored: A 1" in text


def _cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "evals.latency.score", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=REPO,
        # The table prints "×" and "—"; a Windows pipe would otherwise encode them cp1252.
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=True,
    ).stdout


def test_cli_prints_json_by_default_and_the_table_on_request(tmp_path):
    f = tmp_path / "evals-run1.jsonl"
    f.write_text(json.dumps(turn("B", FAST_L0, FAST_L1, L3 * 0.5, l5=L5 * 0.5)) + "\n\n")
    assert json.loads(_cli(str(f)))["passed"] is True  # the Gate L command's shape
    table = _cli("--table", str(f))
    assert "| B | L3 | 1 |" in table and "Violations (0):" in table
