"""Suite A — constraint extraction and shortlist correctness (spec §7.1).

Skeleton from Task 1.6: the loader and the assertion calls are in place; cases/a is filled
in Task 2.10, which also removes the xfail marker. Each case is {"id", "turns", "expect"};
`turns` end with "yes" after the readback, and `expect` may carry: `kind`, `matched_ids`,
`unknown_ids`, `excluded_ids`, `readback_contains`.
"""

from __future__ import annotations

import pytest
from scout.contract.outcome import Answered, Degraded

from evals.conftest import load_cases
from evals.harness.driver import Driver

# Remove in Task 2.10, when the orchestrator exists.
pytestmark = pytest.mark.xfail(strict=False, reason="orchestrator pending (Task 2.10)")

CASES = load_cases("a")


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
async def test_extraction(case, store, settings):
    outcomes = await Driver(store, settings).run(case["turns"])
    last = outcomes[-1]
    exp = case["expect"]

    # The readback is spoken before any shortlist; every outcome is both spoken and shown.
    heard = " ".join(o.spoken for o in outcomes)
    for word in exp.get("readback_contains", []):
        assert word in heard, f"readback never said {word!r}"

    if "kind" in exp:
        assert last.kind == exp["kind"], f"got {last.kind}: {last.spoken}"
        if exp["kind"] != "answered":
            return

    assert isinstance(last, (Answered, Degraded)), f"got {last.kind}: {last.spoken}"
    shortlist = last.view_model.shortlist
    assert shortlist is not None, "answered without a shortlist"
    unknown = {i for g in shortlist.unknown_on for i in g.listing_ids}

    for i in exp.get("matched_ids", []):
        assert i in shortlist.order, f"{i} should be matched"
    for i in exp.get("unknown_ids", []):
        assert i in unknown, f"{i} should be in the unknown group"
        assert i not in shortlist.order, f"{i} is unknown and must not be ranked"
    for i in exp.get("excluded_ids", []):
        assert i not in shortlist.order and i not in unknown, f"{i} should be excluded"
