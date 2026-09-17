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

_ORDINAL_WORDS = {
    "1st": "first",
    "2nd": "second",
    "3rd": "third",
    "4th": "fourth",
    "5th": "fifth",
    "6th": "sixth",
    "7th": "seventh",
    "8th": "eighth",
    "9th": "ninth",
    "10th": "tenth",
}
_DIGIT_ORDINAL_ONE = re.compile(r"\b(\d{1,2}(?:st|nd|rd|th))\s+(?:1|one)\b", re.IGNORECASE)


def normalise_ordinals(text: str) -> str:
    """ "the 1st 1" -> "the first one", before routing and before Job 1.

    Deepgram's numerals/smart_format write a spoken ordinal as digits. On production
    (2026-09-17) "the first one" arrived as "The 1st 1." and was taken for another language,
    and "book a visit for the 1st 1" was asked "which listing?". Only the "<ordinal> one"
    shape is rewritten, so "the 1st floor" keeps its meaning.
    """

    def word(m: re.Match) -> str:
        return f"{_ORDINAL_WORDS.get(m.group(1).lower(), m.group(1))} one"

    return _DIGIT_ORDINAL_ONE.sub(word, text)


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

_CARDINALS = frozenset({"one", "two", "three"})
_LISTING_NOUN = r"(?:listing|property|flat|home|place|house|apartment)"
_ORDINAL_NOUN = re.compile(rf"\b(\w+)\s+{_LISTING_NOUN}\b", re.IGNORECASE)


def parse_ordinal(text: str) -> int | None:
    """ "the second one" -> 2. Pattern matching in code, no model call (AD-3).

    Lane B uses it so that "how far is the metro from the second one" explains the listing
    the renter actually meant: lane B never calls Job 1, so `Job1Result.reference` does not
    exist on that path.
    """
    m = re.search(r"\bthe\s+(\w+)\s+one\b", text, re.IGNORECASE) or re.search(
        r"\b(\w+)\s+one\b", text, re.IGNORECASE
    )
    if m is not None and m.group(1).lower() in ORDINALS:
        return ORDINALS[m.group(1).lower()]
    # A2: "this 2nd listing", "the third flat". Only true ordinals here: "two flats" and
    # "one place" are not a reference to a listing on screen.
    for m in _ORDINAL_NOUN.finditer(text):
        word = m.group(1).lower()
        if word not in _CARDINALS and word in ORDINALS:
            return ORDINALS[word]
    return None


# A question that NAMES a listing ("the first one", "this one") is asking about that
# listing, not changing the preferences — so it belongs in lane B even when it uses none of
# the words in _EXPLAIN. Found by the 2026-09-10 eval pass: "is there a park near the first
# one?" and "when can I move into the first one?" were routed to lane A, which produces no
# explanation at all, so Suite C's grounding assertions were skipped rather than passed.
_ORDINAL_WORD = r"(?:first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th)"
_ASKS_ABOUT_LISTING = re.compile(
    r"\b(?:what|when|where|how|which|is|are|does|do|can|could|tell me)\b"
    rf"[^?]*\b(?:(?:this|that|the\s+\w+)\s+one|(?:this|that)(?:\s+{_ORDINAL_WORD})?\s+"
    rf"{_LISTING_NOUN}|the\s+{_ORDINAL_WORD}\s+{_LISTING_NOUN})\b",
    re.IGNORECASE,
)

# A2, heard on production (2026-09-17): "Does it have a nearby hospital?" and "So does this
# have a lift facility?" name no listing, but with a shortlist on screen "it" and "this" are
# the listing last referred to. Routed to lane A they became requirements and an empty result.
_DOES_IT_HAVE = re.compile(
    rf"\bdoes\s+(?:it|this|that|the(?:\s+{_ORDINAL_WORD})?\s+{_LISTING_NOUN})"
    rf"(?:\s+(?:{_ORDINAL_WORD}\s+)?(?:one|{_LISTING_NOUN}))?\s+have\b(?!\s+to\b)",
    re.IGNORECASE,
)

# "Is there a hospital nearby?" / "is there a school near it?". A question about the listing
# only when it carries no requirement: "is there a 3BHK nearby under 40,000" is a search.
_IS_THERE_NEAR = re.compile(
    r"\bis\s+there\s+(?:a|an|any)\b[^?.]*?\bnear(?:by|\s+(?:it|this|that|here|there|by))\b",
    re.IGNORECASE,
)

# A3: what a requirement sounds like. A sentence stating these is the renter refining the
# search, even when another sentence in the same turn said "why" (production, 2026-09-17:
# "I don't know why you did not listen to me ... The size should be at least 1,500 square
# feet. It should be fully furnished." was explained instead of applied).
_REQUIREMENT = re.compile(
    r"bhk\b|\bsq\.?\s*f(?:ee)?t\b|\bsqft\b|\bsquare\s+f(?:ee|oo)t\b|\bfurnished\b|"
    r"\bparking\b|\blift\b|\bbudget\b|\blakhs?\b|\b\d+\s*k\b|"
    r"\d[\d,]*\s*(?:rupees|thousand)\b|₹|\brent\b[^.?!]*\d|\bshould\s+be\b|"
    r"\bat\s+least\b",
    re.IGNORECASE,
)


def mentions_requirement(text: str) -> bool:
    """Whether the words carry a requirement marker anywhere, question or not (F1)."""
    return bool(_REQUIREMENT.search(text))


_QUESTION_START = re.compile(
    r"^(?:(?:so|and|but|okay|ok|well|then|also|enough)[,\s]+)*"
    r"(?:why|what|when|where|who|which|how|is|are|was|does|do|did|can|could|will|would)\b",
    re.IGNORECASE,
)


def _states_requirements(text: str) -> bool:
    """A requirement marker in a sentence that is not itself a question."""
    for sentence in re.findall(r"[^.?!]+[.?!]?", text):
        body = sentence.strip()
        if not body or body.endswith("?") or _QUESTION_START.match(body):
            continue
        if _REQUIREMENT.search(body):
            return True
    return False


# The renter quoting the guide back at us: no listing reference and no _EXPLAIN word, but
# plainly a question about a document the assistant holds.
_ASKS_ABOUT_GUIDE = re.compile(r"\bthe guide say|\bwhat does (?:it|the guide) say", re.IGNORECASE)

# Acting on a listing is not asking about it. These verbs anywhere in the turn keep the turn
# in lane A: "can I book the second one?" reads like a question and is a booking.
_ACTS = re.compile(r"\b(?:book|cancel|reschedule|drop|remove|add|show)\b", re.IGNORECASE)


def classify_turn(text: str, has_shortlist: bool) -> TurnType:
    if not has_shortlist:
        return "A"
    asks_about_listing = bool(_ASKS_ABOUT_LISTING.search(text) or _DOES_IT_HAVE.search(text))
    # A3: requirement content wins over a bare "why" elsewhere in the turn.
    if _states_requirements(text) and not asks_about_listing:
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
    if asks_about_listing or _ASKS_ABOUT_GUIDE.search(text):
        return "B"
    if _IS_THERE_NEAR.search(text) and not _REQUIREMENT.search(text):
        return "B"
    return "A"
