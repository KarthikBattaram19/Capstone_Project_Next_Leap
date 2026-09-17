"""One place, several spellings.

The bundle holds some localities under two spellings, as separate names: "T.C Palya" and
"TC Palya", "Domlur" (2 listings) and "Domluru" (8). Treated as different places, "TCPalya"
was refused as ambiguous and "Did you mean Domluru or Domlur?" was asked (production,
2026-09-17). Names are one place when they match after dropping case, spaces and
punctuation, and then one trailing "u" or "a" (the Kannada ending: Domluru, Bagaluru,
Ashoka Nagara). On the 464 real names that merges exactly ten pairs, each read by hand
and each one place; tests/unit/domain/test_locality_names.py pins them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable


def squash(name: str) -> str:
    """ "K.R. Puram", "K R Puram" and "KR Puram" are one name."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def variant_key(name: str) -> str:
    s = squash(name)
    return s[:-1] if len(s) > 3 and s[-1] in "ua" else s


def same_place(a: str, b: str) -> bool:
    return variant_key(a) == variant_key(b)


def plainest(names: Iterable[str]) -> str:
    """The spelling said back: no dots, then the shortest ("TC Palya", "Domlur")."""
    return min(names, key=lambda n: (len(re.findall(r"[^A-Za-z0-9 ]", n)), len(n), n))


def one_per_place(names: Iterable[str]) -> list[str]:
    """One name per place, in first-appearance order, using only the names given."""
    groups: dict[str, list[str]] = {}
    for n in names:
        groups.setdefault(variant_key(n), []).append(n)
    return [plainest(g) for g in groups.values()]
