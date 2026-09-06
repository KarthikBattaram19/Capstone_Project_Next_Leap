from scout.pipeline.chunking import chunk_document


def fake_embed(texts):
    # Two topics: paragraphs mentioning "pub" cluster together on one axis; the
    # "park" paragraphs cluster together on the other. Cosine between the two is 0.
    return [[1.0, 0.0] if "pub" in t else [0.0, 1.0] for t in texts]


DOC = "\n\n".join(
    [
        "Koramangala is known for its pubs and nightlife. " * 6,
        "The pub scene draws a young crowd on weekends. " * 6,
        "The area has several parks with walking tracks. " * 6,
        "Parks here open early and are popular with families. " * 6,
    ]
)


def test_splits_where_meaning_shifts_not_by_length():
    chunks = chunk_document(DOC, embed=fake_embed, min_words=20, max_words=400)
    assert len(chunks) == 2
    assert "pub" in chunks[0] and "park" not in chunks[0]
    assert "park" in chunks[1] and "pub" not in chunks[1]


def test_never_cuts_inside_a_sentence_when_capping_length():
    chunks = chunk_document(
        "A short sentence. " * 100,
        embed=lambda ts: [[1.0, 0.0]] * len(ts),
        min_words=20,
        max_words=60,
    )
    assert chunks
    assert all(c.strip().endswith(".") for c in chunks)
    assert all(len(c.split()) <= 60 for c in chunks)


def test_a_short_tail_is_folded_into_the_previous_chunk_when_it_fits():
    # A document whose last paragraph is a few words would otherwise leave a chunk far
    # below min_words. It joins the previous chunk when the pair stays within max_words.
    # The tail is on the "pub" axis, so the drift rule splits it off first.
    doc = DOC + "\n\nA small pub stands by the gate."
    chunks = chunk_document(doc, embed=fake_embed, min_words=20, max_words=400)
    assert len(chunks) == 2
    assert chunks[1].endswith("A small pub stands by the gate.")


def test_a_short_tail_stays_separate_when_folding_would_exceed_max_words():
    long_para = "Parks here open early and are popular with families. " * 20  # 180 words
    doc = long_para + "\n\nA small pub stands by the gate."
    chunks = chunk_document(doc, embed=fake_embed, min_words=20, max_words=185)
    assert len(chunks) == 2
    assert chunks[1] == "A small pub stands by the gate."
