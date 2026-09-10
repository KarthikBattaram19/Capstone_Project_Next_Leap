from scout.providers.deepgram_stt import build_keyterms


def test_keyterms_come_from_the_dataset():
    ks = build_keyterms(["HSR Layout", "Koramangala"])
    assert "HSR Layout" in ks and "Koramangala" in ks and "BHK" in ks and "lakh" in ks


def test_keyterms_are_capped_and_spent_on_the_best_populated_localities():
    import json
    import pathlib

    from scout.providers.deepgram_stt import DOMAIN_TERMS, MAX_KEYTERM_CHARS, MAX_KEYTERMS

    # 464 real names → the budget, not the list. The most-populated localities survive.
    manifest = pathlib.Path("../data/bundle/manifest.json").read_text(encoding="utf-8")
    counts = json.loads(manifest)["localities"]
    ks = build_keyterms(counts)
    assert len(ks) == MAX_KEYTERMS
    assert sum(len(k) for k in ks) <= MAX_KEYTERM_CHARS
    assert all(t in ks for t in DOMAIN_TERMS)
    # 128 localities sit at the 10-listing ceiling; ties are ranked by name, so the
    # alphabetically first of them must be kept.
    top = min(n for n in counts if counts[n] == max(counts.values()))
    assert top in ks
    kept = [k for k in ks if k not in DOMAIN_TERMS]
    assert min(counts[k] for k in kept) >= max(counts[n] for n in counts if n not in kept)


def test_a_small_list_is_kept_whole():
    assert build_keyterms({"Koramangala": 7, "HSR Layout": 10})[:2] == ["HSR Layout", "Koramangala"]
