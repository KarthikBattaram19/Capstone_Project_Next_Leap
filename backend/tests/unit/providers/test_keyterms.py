from scout.providers.deepgram_stt import build_keyterms


def test_keyterms_come_from_the_dataset():
    ks = build_keyterms(["HSR Layout", "Koramangala"])
    assert "HSR Layout" in ks and "Koramangala" in ks and "BHK" in ks and "lakh" in ks
