from evals.latency.score import TARGETS_MS, score


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
    # this asserts both halves of that split.
    lines = [turn("A", 120, 600, 1200, l4=2000) for _ in range(99)]
    lines.append(turn("A", 120, 600, 3200, l4=2000))
    rep = score(lines)
    assert rep.p99["A"]["L2"] == 1200  # the outlier does not drag p99 up
    assert rep.passed is False
    assert any("2×" in v for v in rep.violations)  # ... but it is still a hard failure


def test_a_slow_bulk_fails_on_p99_with_no_2x_violation():
    # The other half: every request slower than target but none past 2×. p99 must fail
    # on its own, or a uniformly slow system would pass.
    lines = [turn("A", 120, 600, 1800, l4=2000) for _ in range(100)]
    rep = score(lines)
    assert rep.p99["A"]["L2"] == 1800
    assert rep.passed is False
    assert not any("2×" in v for v in rep.violations)
    assert any("p99" in v and "L2" in v for v in rep.violations)


def test_type_b_pass_does_not_cover_type_a():
    lines = [turn("B", 100, 500, 1000, l5=4000) for _ in range(30)]
    lines += [turn("A", 100, 500, 1600) for _ in range(30)]
    rep = score(lines)
    assert rep.passed is False and rep.p99["B"]["L3"] <= TARGETS_MS["L3"]
