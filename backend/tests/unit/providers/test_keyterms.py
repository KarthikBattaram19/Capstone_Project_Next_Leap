import json

from scout.config import BACKEND_DIR
from scout.providers.deepgram_stt import (
    DOMAIN_TERMS,
    MAX_KEYTERM_CHARS,
    MAX_KEYTERMS,
    build_keyterms,
)


def test_keyterms_are_the_domain_terms_only():
    # 2026-09-17, conv 2: "Dommasandra" was a keyterm and "Domlur" was not; the renter said
    # Domlur and Deepgram heard "I mentioned Dommasandra." three times. Locality names are no
    # longer primed — the name matching after the transcript (B1/C1) resolves them.
    ks = build_keyterms()
    assert ks == DOMAIN_TERMS
    assert "BHK" in ks and "lakh" in ks


def test_no_locality_name_is_primed():
    # Resolved from the code: CI runs pytest from the repo root, where "../data" is
    # outside the checkout.
    manifest = (BACKEND_DIR.parent / "data" / "bundle" / "manifest.json").read_text(
        encoding="utf-8"
    )
    localities = {n.casefold() for n in json.loads(manifest)["localities"]}
    ks = build_keyterms()
    assert "Dommasandra".casefold() in localities
    assert not [k for k in ks if k.casefold() in localities]


def test_keyterms_stay_inside_the_measured_budget():
    # Deepgram refused the socket at 85 terms (measured 2026-09-10); keep well inside it.
    ks = build_keyterms()
    assert len(ks) <= MAX_KEYTERMS
    assert sum(len(k) for k in ks) <= MAX_KEYTERM_CHARS


def test_the_returned_list_is_a_copy():
    ks = build_keyterms()
    ks.append("Dommasandra")
    assert "Dommasandra" not in build_keyterms()
