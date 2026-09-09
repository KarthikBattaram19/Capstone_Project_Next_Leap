"""P3b: a pause after 'under', 'near', 'and' or a bare number is not the end of the sentence."""

import re

CONTINUATION_WORDS = (
    "under",
    "above",
    "near",
    "with",
    "and",
    "about",
    "around",
    "to",
    "below",
    "over",
    "between",
    "or",
)

_NUMBER_WORDS = (
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
    "hundred",
    "point",
)

_UNIT = re.compile(r"(k|thousand|lakh|lakhs|bhk|rk|sq\s?ft|feet|km|rupees|rs\.?)$", re.IGNORECASE)


def looks_unfinished(interim: str) -> bool:
    words = interim.strip().lower().rstrip(",.").split()
    if not words:
        return False
    last = words[-1]
    if last in CONTINUATION_WORDS:
        return True
    if _UNIT.search(last):
        # "35k", "forty thousand", "1.2 lakh" — the magnitude arrived; nothing is pending.
        return False
    # A bare magnitude ("35", "forty") is the start of an amount, not the whole of one.
    return bool(re.fullmatch(r"\d+(\.\d+)?", last)) or last in _NUMBER_WORDS
