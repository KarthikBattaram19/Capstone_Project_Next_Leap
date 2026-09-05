"""Owner names and phone numbers are removed BEFORE anything is written to disk (spec §3.2)."""

import re

# An optional +91 / 91 / 0 prefix with optional space or hyphen, then a digit 6-9 and four
# more digits, an optional space or hyphen, then five digits, bounded by non-digits.
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s\-]?|0)?[6-9]\d{4}[\s\-]?\d{5}(?!\d)")
# A bare run of nine or ten digits. The supplied sheet's Phone Number column is nine
# digits, which the pattern above never matched. A decimal's digits are left alone
# (coordinates run to eight fraction digits) and the widest legitimate figure in the
# sheet is a six-digit deposit, so no real value in this source is a nine-digit run.
_DIGIT_RUN = re.compile(r"(?<![\d.])\d{9,10}(?!\d)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def strip_pii(text: str) -> str:
    text = _EMAIL.sub("[email removed]", text)
    text = _PHONE.sub("[phone removed]", text)
    return _DIGIT_RUN.sub("[phone removed]", text)


class PiiLeakError(AssertionError):
    """Raised when text about to be written to disk still carries personal data."""


# Kind -> the pattern that finds it. Same patterns strip_pii uses, so the guard can
# never disagree with the stripper about what counts as personal data.
_KINDS = {"email": _EMAIL, "phone": _PHONE, "phone (bare digit run)": _DIGIT_RUN}


def find_pii(text: str) -> dict[str, int]:
    """Kinds of personal data present, and how many of each. Never returns the values."""
    found = {kind: len(pat.findall(text)) for kind, pat in _KINDS.items()}
    return {kind: n for kind, n in found.items() if n}


def assert_no_pii(text: str, *, where: str) -> None:
    """Refuse to publish `text`. `where` names the file for the error; values never appear.

    The message reports counts only: printing the leaked number would republish it into
    whatever log reads the failure.
    """
    found = find_pii(text)
    if found:
        detail = ", ".join(f"{n} x {kind}" for kind, n in sorted(found.items()))
        raise PiiLeakError(f"{where}: refusing to write, personal data present ({detail})")
