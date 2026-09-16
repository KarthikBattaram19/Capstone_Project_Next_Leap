"""The embedding session is timed at boot and the fastest thread setting is kept.

Production, 2026-09-17: a "why?" turn spent 2.6-2.7 s warm (7.9 s cold) in retrieval, which
embeds the question with this model, against ~50 ms on a laptop. ONNX Runtime sizes its
thread pool from the cores it can see, which on a shared container is not the CPU it is
allowed to use. Rather than guess, the backend measures each setting where it runs.
"""

from scout.pipeline import embedding


def test_tuning_times_every_candidate_and_keeps_the_fastest_session(monkeypatch):
    ef = embedding.get_embedding_function()
    timings = embedding.tune_threads(candidates=(0, 1), repeats=1)

    assert set(timings) == {0, 1}
    assert all(ms > 0 for ms in timings.values())
    best = min(timings, key=timings.get)
    assert ef.model.get_session_options().intra_op_num_threads == best
    assert len(ef(["is it quiet at night?"])[0]) == 384, "the tuned session still embeds"


def test_a_tuned_session_embeds_like_the_default_one():
    ef = embedding.get_embedding_function()
    before = ef(["a park near the metro"])[0]
    embedding.tune_threads(candidates=(1,), repeats=1)
    after = ef(["a park near the metro"])[0]
    assert max(abs(a - b) for a, b in zip(before, after, strict=True)) < 1e-4
