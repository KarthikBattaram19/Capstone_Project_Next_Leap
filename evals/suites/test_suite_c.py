"""Suite C — grounding and hallucination (spec §7.1). One case per JSON file in cases/c."""

from __future__ import annotations

import pytest
from scout.contract.outcome import Answered, Degraded
from scout.conversation.session import SessionManager

from evals.assertions.commute import assert_three_layers_agree, assert_your_commute_absent
from evals.assertions.grounding import assert_every_claim_cites
from evals.conftest import load_cases
from evals.harness.driver import Driver

CASES = load_cases("c")


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
async def test_grounding(case, store, settings, job2_drops):
    # The suite owns the session (as Suite B does) so the assembler's per-case bound and
    # dropped counts can be read off it afterwards. Recorded, never asserted on: a drop is
    # the fence working, and a threshold here would be an assertion nobody agreed.
    session = SessionManager(ttl_s=600).create()
    outcomes = await Driver(store, settings).run(case["turns"], session=session)
    job2_drops[case["id"]] = {"bound": session.job2_bound, **session.job2_drops}
    last = outcomes[-1]
    exp = case["expect"]

    if exp.get("kind") == "empty":
        assert last.kind == "empty"
        return

    assert isinstance(last, (Answered, Degraded)), f"got {last.kind}: {last.spoken}"
    vm = last.view_model

    if "commute_method" in exp:
        card = next(
            c for g in vm.shortlist.groups for c in g.cards if c.listing_id == exp["listing_id"]
        )
        assert_three_layers_agree(
            card, vm.explanation, exp["commute_method"], row=exp.get("row", "transit")
        )

    if exp.get("your_commute_absent"):
        card = next(
            c for g in vm.shortlist.groups for c in g.cards if c.listing_id == exp["listing_id"]
        )
        assert_your_commute_absent(card)

    if vm.explanation is not None:
        assert_every_claim_cites(vm.explanation, store, case["locality"])
        for gap in exp.get("gaps_declared", []):
            assert any(gap.lower() in g.lower() for g in vm.explanation.gaps), (
                f"gap not declared: {gap}"
            )
        for forbidden in exp.get("must_not_mention", []):
            text = " ".join(c.text for c in vm.explanation.claims).lower()
            assert forbidden.lower() not in text, f"contamination: {forbidden!r} appeared"

    for word in exp.get("spoken_contains", []):
        assert word in last.spoken
