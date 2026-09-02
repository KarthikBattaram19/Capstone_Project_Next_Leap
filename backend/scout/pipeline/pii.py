"""Owner names and phone numbers are removed BEFORE anything is written to disk (spec §3.2)."""

import re

# An optional +91 / 91 / 0 prefix with optional space or hyphen, then a digit 6-9 and four
# more digits, an optional space or hyphen, then five digits, bounded by non-digits.
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s\-]?|0)?[6-9]\d{4}[\s\-]?\d{5}(?!\d)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def strip_pii(text: str) -> str:
    text = _EMAIL.sub("[email removed]", text)
    return _PHONE.sub("[phone removed]", text)
