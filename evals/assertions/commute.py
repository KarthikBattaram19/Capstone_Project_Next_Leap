"""Three-layer commute agreement: spoken words, card badge and full label name ONE method.

Spec §7.3: a run in which speech and card disagree is a failed run even if each layer is
individually well-formed. The straight-line badge must be visibly distinct from the routed one.
"""

from __future__ import annotations

from scout.contract.viewmodels import CardVM, CommuteRowVM, ExplanationVM

SPOKEN_WORDS = {"ROUTED": "by route", "STRAIGHT_LINE": "straight line"}
BADGES = {"ROUTED": "by route", "STRAIGHT_LINE": "straight-line"}
# "traight-line" on purpose: it matches both "Straight-line" and "straight-line" in a label.
LABEL_FRAGMENT = {"ROUTED": "routing", "STRAIGHT_LINE": "traight-line"}


def _row_agrees(row: CommuteRowVM, method: str) -> list[str]:
    problems: list[str] = []
    if row.value_text == "not stated":
        if row.badge != "":
            problems.append(f"{row.what}: 'not stated' row must carry no badge, got {row.badge!r}")
        return problems
    if row.badge != BADGES[method]:
        problems.append(f"{row.what}: badge {row.badge!r} != {BADGES[method]!r}")
    if LABEL_FRAGMENT[method] not in row.full_label or row.full_label.strip() == "[OSM]":
        problems.append(
            f"{row.what}: full label {row.full_label!r} does not resolve to method + timing"
        )
    spoken = row.spoken.replace("straight-line", "straight line")
    if SPOKEN_WORDS[method] not in spoken:
        problems.append(f"{row.what}: spoken {row.spoken!r} lacks {SPOKEN_WORDS[method]!r}")
    if (
        method == "STRAIGHT_LINE"
        and row.what == "Work"
        and "road distance will be longer" not in row.spoken
    ):
        problems.append(f"{row.what}: straight-line caveat missing from the same breath")
    return problems


def assert_three_layers_agree(
    card: CardVM, explanation: ExplanationVM | None, expected_method: str, row: str = "transit"
) -> None:
    r = card.transit if row == "transit" else card.your_commute
    assert r is not None, f"card {card.listing_id} has no {row} row"
    problems = _row_agrees(r, expected_method)
    if explanation is not None:
        text = " ".join([explanation.opener] + [c.text for c in explanation.claims]).replace(
            "straight-line", "straight line"
        )
        other = "straight line" if expected_method == "ROUTED" else "by route"
        if r.value_text != "not stated" and SPOKEN_WORDS[expected_method] not in text:
            problems.append(f"explanation never says {SPOKEN_WORDS[expected_method]!r}")
        if other in text and SPOKEN_WORDS[expected_method] not in text:
            problems.append("explanation names the OTHER method — layers disagree")
    assert not problems, "\n".join(problems)


def assert_your_commute_absent(card: CardVM) -> None:
    assert card.your_commute is None, (
        "no commute point stated: the 'Your commute' row must be absent, not empty"
    )
