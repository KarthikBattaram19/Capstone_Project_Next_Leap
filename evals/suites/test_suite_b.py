"""Suite B — order-preserving refinement (spec §7.1).

Each case is {"id", "before_turns", "edit_turn", "expect"}: the suite runs `before_turns`
(ending in "yes") on one session, captures the shortlist, runs `edit_turn` on the same
session, captures it again, and asserts that every listing the edit did not touch is
byte-identical and still in its relative place.

`touched` is computed, not listed: a listing is touched when its verdict against the
constraints differs before and after the edit. `expect` may carry `kind`, `extracted`,
`matched_ids`, `excluded_ids`, `appended_after` (ids that must come after every id kept
from the previous order) and `suggestions_contain`.
"""

from __future__ import annotations

import pytest
from scout.contract.outcome import Answered, Degraded
from scout.conversation.session import SessionManager
from scout.engines.shortlist import evaluate

from evals.assertions.order import assert_untouched_identical
from evals.conftest import load_cases
from evals.harness.driver import Driver
from evals.suites.test_suite_a import _plain

CASES = load_cases("b")


def _shortlist(outcome):
    assert isinstance(outcome, (Answered, Degraded)), f"got {outcome.kind}: {outcome.spoken}"
    assert outcome.view_model.shortlist is not None, "answered without a shortlist"
    return outcome.view_model.shortlist


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
async def test_refinement(case, store, settings):
    exp = case["expect"]
    driver = Driver(store, settings)
    session = SessionManager(ttl_s=600).create()

    before = _shortlist((await driver.run(case["before_turns"], session=session))[-1])
    constraints_before = session.constraints
    edited = (await driver.run([case["edit_turn"]], session=session))[-1]
    constraints_after = session.constraints

    for field, value in exp.get("extracted", {}).items():
        got = _plain(getattr(constraints_after, field))
        want = sorted(value) if isinstance(value, list) else value
        assert got == want, f"{field}: extracted {got!r}, expected {want!r} — {edited.spoken}"

    if "kind" in exp:
        assert edited.kind == exp["kind"], f"got {edited.kind}: {edited.spoken}"

    if edited.kind == "needs_input":
        # A contradiction asks; it never half-applies. The shortlist is what it was.
        assert session.shortlist.order == before.order, "the shortlist moved on a question"
        return

    if edited.kind == "empty":
        # Every listing landed in an unknown group: null never satisfies a must-have, and
        # the empty state offers to include them rather than dropping them silently.
        for word in exp.get("suggestions_contain", []):
            assert any(word in s for s in edited.suggestions), (
                f"suggestions never offer {word!r}: {edited.suggestions}"
            )
        return

    after = _shortlist(edited)
    touched = {
        listing.id
        for listing in store.listings.values()
        if evaluate(listing, constraints_before) != evaluate(listing, constraints_after)
    }
    assert_untouched_identical(before, after, touched)

    for i in exp.get("matched_ids", []):
        assert i in after.order, f"{i} should still be there; got {after.order}"
    for i in exp.get("excluded_ids", []):
        assert i not in after.order, f"{i} should have gone; got {after.order}"

    kept = [i for i in before.order if i in after.order]
    for i in exp.get("appended_after", []):
        assert i in after.order, f"{i} should have been appended; got {after.order}"
        assert after.order.index(i) > max(after.order.index(k) for k in kept), (
            f"{i} was re-sorted into the middle instead of appended: {after.order}"
        )
