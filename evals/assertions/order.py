"""Order-preserving refinement: a card nobody mentioned is byte-identical, and stays in place."""

from __future__ import annotations

from scout.contract.viewmodels import CardVM, ShortlistVM


def _cards(vm: ShortlistVM) -> dict[str, CardVM]:
    return {c.listing_id: c for g in vm.groups for c in g.cards}


def assert_untouched_identical(before: ShortlistVM, after: ShortlistVM, touched: set[str]) -> None:
    b, a = _cards(before), _cards(after)
    untouched = [i for i in before.order if i not in touched and i in a]
    for i in untouched:
        # Rank is renumbered by every refinement; zero it on both copies before comparing.
        bj = b[i].model_copy(update={"rank": 0}).model_dump_json()
        aj = a[i].model_copy(update={"rank": 0}).model_dump_json()
        assert bj == aj, f"listing {i} changed although it was not mentioned:\n{bj}\n{aj}"
    after_positions = [after.order.index(i) for i in untouched]
    assert after_positions == sorted(after_positions), (
        f"relative order of untouched listings changed: {untouched} → {after.order}"
    )
