"""One rupee formatter, used everywhere money is shown or spoken (spec §4).

Indian grouping: the last three digits, then pairs — ₹1,00,000, never ₹100,000. It lives in
the domain because the readback the renter HEARS and the card they SEE must agree; when the
readback used Python's default grouping the same deposit was spoken "₹100,000" and printed
"₹1,00,000" in the very next breath.
"""

from __future__ import annotations

NOT_STATED = "not stated"


def rupees(n: int | None) -> str:
    if n is None:
        return NOT_STATED
    sign, s = ("-", str(-n)) if n < 0 else ("", str(n))
    if len(s) <= 3:
        return f"{sign}₹{s}"
    head, tail = s[:-3], s[-3:]
    parts: list[str] = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return sign + "₹" + ",".join([*parts, tail])
