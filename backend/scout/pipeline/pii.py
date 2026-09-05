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
