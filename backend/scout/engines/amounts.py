"""'35k' → 35000; '1.2 lakh' → 120000; 'thirty five' → ask (spec §5.1, §6.26)."""

from __future__ import annotations

import re
from dataclasses import dataclass

_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}


@dataclass(frozen=True)
class Amount:
    rupees: int
    heard: str


@dataclass(frozen=True)
class Ambiguous:
    heard: str
    candidates: list[int]


@dataclass(frozen=True)
class NoAmount:
    pass


AmountResult = Amount | Ambiguous | NoAmount


def _words_to_number(s: str) -> float | None:
    s = s.replace("-", " ")
    if "point" in s:
        whole, _, frac = s.partition("point")
        w = _words_to_number(whole.strip())
        digits = "".join(str(_WORDS[t]) for t in frac.split() if t in _WORDS and _WORDS[t] < 10)
        if w is None or not digits:
            return None
        return float(f"{int(w)}.{digits}")
    total = 0
    for tok in s.split():
        if tok not in _WORDS:
            return None
        total += _WORDS[tok]
    return float(total) if s.strip() else None


# Longest alternative first, so "ninety" is not read as "nine" with a stray "ty" left over.
# Python's alternation takes the first branch that matches, and "nine", "six", "seven" and
# "eight" are all prefixes of a ten: without this, "sixty thousand" parsed as a bare 6.
_WORD_ALT = "|".join(sorted(_WORDS, key=len, reverse=True))

_NUM = r"(\d+(?:,\d{2,3})*(?:\.\d+)?)"
_WORDNUM = r"((?:(?:" + _WORD_ALT + r")[\s-]?)+(?:point(?:\s(?:" + _WORD_ALT + r"))+)?)"
_SCALE = r"\s*(k|thousand|lakhs?|crores?)\b"
_BARE_NUM = r"(?<![\d.])(\d{1,3}(?:\.\d+)?)(?![\d.])"
# A grouped figure, Indian or Western: 1,75,000 as well as 175,000, plus a plain run of
# digits. The Indian alternative is not optional — everything this system prints is grouped
# the Indian way (₹1,75,000), so a transcript that reads one back must parse it, and a
# Western-only pattern silently matched the "75,000" inside "1,75,000".
_GROUPED = r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})+,\d{3}|\d{4,7})(?![\d.])"
# "two BHK" is a room count, not an amount: a number word followed by a room unit is
# not a bare magnitude to ask about.
_ROOM_UNIT = re.compile(r"[\s-]*(bhk|rk|bedrooms?|bathrooms?|balconies|balcony)\b", re.IGNORECASE)


def normalise_amount(text: str) -> AmountResult:
    t = text.lower().replace("rs.", "").replace("rs ", "").replace("₹", "")

    m = re.search(_NUM + _SCALE, t) or re.search(_WORDNUM + _SCALE, t)
    if m:
        raw, scale = m.group(1), m.group(2)
        n = float(raw.replace(",", "")) if raw[0].isdigit() else _words_to_number(raw.strip())
        if n is None:
            return NoAmount()
        mult = (
            1000
            if scale in ("k", "thousand")
            else 100_000
            if scale.startswith("lakh")
            else 10_000_000
        )
        return Amount(rupees=round(n * mult), heard=m.group(0).strip())

    m = re.search(_GROUPED, t)  # 35,000 or 1,75,000 or 28000
    if m:
        return Amount(rupees=int(m.group(1).replace(",", "")), heard=m.group(1))

    m = re.search(_BARE_NUM, t)
    if m is None:
        wm = re.search(_WORDNUM, t)
        if wm is not None and not _ROOM_UNIT.match(t, wm.end()):
            m = wm
    if m:
        raw = m.group(1)
        n = float(raw) if raw[0].isdigit() else _words_to_number(raw.strip())
        if n is not None and n > 0:
            return Ambiguous(
                heard=raw.strip(), candidates=[int(n), int(n * 1000), int(n * 100_000)]
            )
    return NoAmount()
