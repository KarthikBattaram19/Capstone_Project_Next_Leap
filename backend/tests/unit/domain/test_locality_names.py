import json
from pathlib import Path

from scout.domain.locality_names import one_per_place, same_place, variant_key

_MANIFEST = Path(__file__).resolve().parents[4] / "data" / "bundle" / "manifest.json"


def test_the_spelling_variants_merged_in_the_real_bundle_were_each_checked_by_hand():
    """Production, 2026-09-17: the bundle holds one place under two spellings (T.C Palya /
    TC Palya; Domlur 2 listings / Domluru 8), so "TCPalya" was refused as ambiguous and
    "Did you mean Domluru or Domlur?" was asked. Every group below was read by hand and is
    one place; a new dataset that merges anything else fails here until someone checks it."""
    names = json.loads(_MANIFEST.read_text(encoding="utf-8"))["localities"]
    groups: dict[str, list[str]] = {}
    for n in sorted(names):
        groups.setdefault(variant_key(n), []).append(n)
    merged = sorted(v for v in groups.values() if len(v) > 1)
    assert merged == [
        ["Ashoka Nagara", "Ashokanagar"],
        ["Bagalur", "Bagaluru"],
        ["Bapuji Nagar", "Bapuji Nagara"],
        ["Bellandur", "Bellanduru"],
        ["Domlur", "Domluru"],
        ["J.P Nagar", "JP Nagar"],
        ["R.T Nagar", "RT Nagar"],
        ["T.C Palya", "TC Palya"],
        ["Ullal", "Ullalu"],
        ["Vignananagar", "Vignananagara"],
    ]


def test_spaces_dots_and_a_trailing_u_or_a_are_one_place():
    assert same_place("TCPalya", "T.C Palya") and same_place("TC Palya", "T.C Palya")
    assert same_place("Domlur", "Domluru")
    assert not same_place("Domlur", "Dommasandra")


def test_one_name_per_place_in_first_appearance_order_and_the_plainest_spelling():
    assert one_per_place(["T.C Palya", "Koramangala", "TC Palya"]) == ["TC Palya", "Koramangala"]
    assert one_per_place(["Domlur", "Domluru"]) == ["Domlur"]
    assert one_per_place(["J.P Nagar"]) == ["J.P Nagar"], "only a name that is there is used"
