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


# A question that NAMES a listing ("the first one", "this one") is asking about that
# listing, not changing the preferences — so it belongs in lane B even when it uses none of
# the words in _EXPLAIN. Found by the 2026-09-10 eval pass: "is there a park near the first
# one?" and "when can I move into the first one?" were routed to lane A, which produces no
# explanation at all, so Suite C's grounding assertions were skipped rather than passed.
_ASKS_ABOUT_LISTING = re.compile(
    r"\b(?:what|when|where|how|which|is|are|does|do|can|could|tell me)\b"
    r"[^?]*\b(?:this|that|the\s+\w+)\s+one\b",
    re.IGNORECASE,
)

# The renter quoting the guide back at us: no listing reference and no _EXPLAIN word, but
# plainly a question about a document the assistant holds.
_ASKS_ABOUT_GUIDE = re.compile(r"\bthe guide say|\bwhat does (?:it|the guide) say", re.IGNORECASE)

# Acting on a listing is not asking about it. These verbs anywhere in the turn keep the turn
# in lane A: "can I book the second one?" reads like a question and is a booking.
_ACTS = re.compile(r"\b(?:book|cancel|reschedule|drop|remove|add|show)\b", re.IGNORECASE)


def classify_turn(text: str, has_shortlist: bool) -> TurnType:
    if not has_shortlist:
        return "A"
    # Unchanged from before the 2026-09-10 widening: whatever _EXPLAIN matched then still
    # routes the same way now, so "show me why you picked this one" keeps its explanation.
    if _EXPLAIN.search(text) and not re.match(
        r"^\s*(book|cancel|reschedule)\b", text, re.IGNORECASE
    ):
        return "B"
    # The widening, and the action guard that belongs only to it: a turn that acts on a
    # listing is not asking about it, however much it reads like a question.
    if _ACTS.search(text):
        return "A"
    if _ASKS_ABOUT_LISTING.search(text) or _ASKS_ABOUT_GUIDE.search(text):
        return "B"
    return "A"
