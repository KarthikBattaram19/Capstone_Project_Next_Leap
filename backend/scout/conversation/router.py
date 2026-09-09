"""Type A or Type B by pattern matching, before Job 1 runs (AD-3, spec §5.1)."""

import re
from typing import Literal

TurnType = Literal["A", "B"]

_EXPLAIN = re.compile(
    r"\bwhy\b|what(?:'s| is) (?:the |this |that )?(?:area|neighbou?rhood|place|locality)|"
    r"\b(?:area|neighbou?rhood) (?:actually )?like\b|\bcommute realistic\b|\btell me about\b|"
    r"\bis it (?:safe|noisy|quiet|walkable)\b|\bsafe at night\b|\bhow far\b|"
    r"\bnearest (?:metro|bus|station)\b|"
    r"\bexplain\b",
    re.IGNORECASE,
)

# Kept for the record: the words that mark an action turn. `classify_turn` decides on
# _EXPLAIN plus the leading-verb guard; this names what "everything else" is made of.
_ACTION = re.compile(
    r"\b(book|cancel|reschedule|drop|remove|only|add|show|under|above|budget|bhk)\b", re.IGNORECASE
)

ORDINALS = {
    "first": 1,
    "1st": 1,
    "one": 1,
    "second": 2,
    "2nd": 2,
    "two": 2,
    "third": 3,
    "3rd": 3,
    "three": 3,
    "fourth": 4,
    "4th": 4,
    "fifth": 5,
    "5th": 5,
}


def parse_ordinal(text: str) -> int | None:
    """ "the second one" -> 2. Pattern matching in code, no model call (AD-3).

    Lane B uses it so that "how far is the metro from the second one" explains the listing
    the renter actually meant: lane B never calls Job 1, so `Job1Result.reference` does not
    exist on that path.
    """
    m = re.search(r"\bthe\s+(\w+)\s+one\b", text, re.IGNORECASE) or re.search(
        r"\b(\w+)\s+one\b", text, re.IGNORECASE
    )
    if m is None:
        return None
    return ORDINALS.get(m.group(1).lower())


def classify_turn(text: str, has_shortlist: bool) -> TurnType:
    if (
        has_shortlist
        and _EXPLAIN.search(text)
        and not re.match(r"^\s*(book|cancel|reschedule)\b", text, re.IGNORECASE)
    ):
        return "B"
    return "A"
