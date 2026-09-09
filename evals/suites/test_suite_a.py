"""Suite A — constraint extraction and shortlist correctness (spec §7.1).

Each case is {"id", "turns", "expect"}. `turns` end with "yes" after the readback wherever a
shortlist is wanted. `expect` may carry:

  kind                 the last outcome's kind
  readback_contains    words that must appear in what was spoken across the whole session
  extracted            constraint field -> value, asserted on the session's ConstraintSet
  all_matched_satisfy  a constraint dict; every matched listing is re-evaluated against it
  matched_ids          ids that must be in the ranked order
  unknown_ids          ids that must be in an unknown group and NOT ranked
  excluded_ids         ids that must be in neither
  unknown_field        a field that must head an unknown group
  localities_span      the matched ids must span at least this many localities
  unmet_field          on an empty result, the field the empty state names as binding
  suggestions_contain  on an empty result, words the suggestions must carry
"""

from __future__ import annotations

import pytest
from scout.contract.outcome import Answered, Degraded
from scout.conversation.session import SessionManager
from scout.domain.constraints import ConstraintEdit, ConstraintSet
from scout.engines.reducer import apply_edits
from scout.engines.shortlist import Match, evaluate

from evals.conftest import load_cases
from evals.harness.driver import Driver

CASES = load_cases("a")


def constraints_from(spec: dict) -> ConstraintSet:
    """Build a ConstraintSet from a case's JSON, through the production coercion."""
    edits: list[ConstraintEdit] = []
    for field, value in spec.items():
        if isinstance(value, list):
            edits.extend(ConstraintEdit(field, "add", v) for v in value)
        else:
            edits.append(ConstraintEdit(field, "set", value))
    out = apply_edits(ConstraintSet(), edits)
    assert isinstance(out, ConstraintSet), f"case constraints contradict themselves: {out}"
    return out


def _plain(v):
    if hasattr(v, "value"):  # an enum
        return v.value
    if hasattr(v, "isoformat"):  # a date
        return v.isoformat()
    if isinstance(v, (tuple, frozenset)):
        return sorted(_plain(x) for x in v)
    return v


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
async def test_extraction(case, store, settings):
    session = SessionManager(ttl_s=600).create()
    outcomes = await Driver(store, settings).run(case["turns"], session=session)
    last = outcomes[-1]
    exp = case["expect"]

    # Every outcome is both spoken and shown, so the readback is checked on what was said.
    heard = " ".join(o.spoken for o in outcomes)
    for word in exp.get("readback_contains", []):
        assert word in heard, f"never said {word!r}; heard: {heard}"

    for field, value in exp.get("extracted", {}).items():
        got = _plain(getattr(session.constraints, field))
        want = sorted(value) if isinstance(value, list) else value
        assert got == want, f"{field}: extracted {got!r}, expected {want!r} — said: {heard}"

    if "kind" in exp:
        assert last.kind == exp["kind"], f"got {last.kind}: {last.spoken}"

    if last.kind == "empty":
        if "unmet_field" in exp:
            assert exp["unmet_field"] in [u.field for u in last.unmet], (
                f"empty state does not name {exp['unmet_field']}: {last.unmet}"
            )
        for word in exp.get("suggestions_contain", []):
            assert any(word in s for s in last.suggestions), (
                f"suggestions never offer {word!r}: {last.suggestions}"
            )
        assert not exp.get("matched_ids"), "case expects matches but the result was empty"
        return

    if exp.get("kind") not in (None, "answered"):
        return

    assert isinstance(last, (Answered, Degraded)), f"got {last.kind}: {last.spoken}"
    shortlist = last.view_model.shortlist
    assert shortlist is not None, "answered without a shortlist"
    unknown = {i for g in shortlist.unknown_on for i in g.listing_ids}

    for i in exp.get("matched_ids", []):
        assert i in shortlist.order, f"{i} should be matched; got {shortlist.order}"
    for i in exp.get("unknown_ids", []):
        assert i in unknown, f"{i} should be in the unknown group"
        assert i not in shortlist.order, f"{i} is unknown and must not be ranked"
    for i in exp.get("excluded_ids", []):
        assert i not in shortlist.order and i not in unknown, f"{i} should be excluded"

    if "unknown_field" in exp:
        assert exp["unknown_field"] in [g.field for g in shortlist.unknown_on], (
            f"no unknown group on {exp['unknown_field']}"
        )

    if "all_matched_satisfy" in exp:
        c = constraints_from(exp["all_matched_satisfy"])
        for i in shortlist.order:
            verdict = evaluate(store.listings[i], c)
            assert isinstance(verdict, Match), f"{i} was matched but does not satisfy: {verdict}"

    if "localities_span" in exp:
        spanned = {store.listings[i].locality for i in shortlist.order}
        assert len(spanned) >= exp["localities_span"], f"only spans {spanned}"
