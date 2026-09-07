"""Suite B — order-preserving refinement (spec §7.1).

Skeleton from Task 1.6: the loader and the assertion call are in place; cases/b is filled in
Task 2.10, which also removes the xfail marker. Each case is {"id", "before_turns",
"edit_turn", "expect"}: the suite runs `before_turns` (ending in "yes") on one session,
captures the shortlist, runs `edit_turn` on the same session, captures it again, and asserts
that every listing the edit did not touch is byte-identical and still in its relative place.
`expect.touched` lists the ids the edit is allowed to change (Task 2.10 may replace this with
ids computed from `engine.evaluate`); `expect.kind` names the edit turn's outcome kind.
"""

from __future__ import annotations

import pytest
from scout.contract.outcome import Answered, Degraded

from evals.assertions.order import assert_untouched_identical
from evals.conftest import load_cases
from evals.harness.driver import Driver

# Remove in Task 2.10, when the orchestrator exists.
pytestmark = pytest.mark.xfail(strict=False, reason="orchestrator pending (Task 2.10)")

CASES = load_cases("b")


def _shortlist(outcome):
    assert isinstance(outcome, (Answered, Degraded)), f"got {outcome.kind}: {outcome.spoken}"
    assert outcome.view_model.shortlist is not None, "answered without a shortlist"
    return outcome.view_model.shortlist


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
async def test_refinement(case, store, settings):
    from scout.conversation.session import SessionManager  # exists from Task 2.10

    exp = case["expect"]
    driver = Driver(store, settings)
    session = SessionManager(ttl_s=600).create()

    before = _shortlist((await driver.run(case["before_turns"], session=session))[-1])
    edited = (await driver.run([case["edit_turn"]], session=session))[-1]

    if "kind" in exp:
        assert edited.kind == exp["kind"], f"got {edited.kind}: {edited.spoken}"
        if exp["kind"] != "answered":
            return

    after = _shortlist(edited)
    assert_untouched_identical(before, after, set(exp.get("touched", [])))
