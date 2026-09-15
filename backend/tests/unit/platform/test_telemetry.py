import scout.platform.telemetry as t


def test_trace_records_named_spans_and_turn_type():
    with t.trace(turn_type="A") as tr:
        with t.span("stt.final"):
            pass
        t.mark("stt.interim")
        with t.span("external.groq"):
            pass
    names = [s.name for s in tr.spans]
    assert names == ["stt.final", "external.groq"]
    assert tr.marks[0].name == "stt.interim"
    assert tr.turn_type == "A"
    assert all(s.duration_ms >= 0 for s in tr.spans)


def test_export_line_has_no_transcript_text():
    with t.trace(turn_type="B") as tr, t.span("retrieval"):
        pass
    line = tr.to_json()
    assert "retrieval" in line and "transcript" not in line


def test_the_jsonl_export_writes_one_line_per_turn(tmp_path):
    # Task 0.10 scores Gate L from this file, so it is the one telemetry output
    # that something outside this module reads.
    import json

    log = tmp_path / "nested" / "latency.jsonl"
    t.configure(str(log))
    try:
        with t.trace(turn_type="A"), t.span("stt.final"):
            pass
        with t.trace(turn_type="B"), t.span("retrieval"):
            pass
    finally:
        t.configure(None)

    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # appended, not overwritten
    assert [json.loads(x)["turn_type"] for x in lines] == ["A", "B"]
    assert json.loads(lines[0])["spans"][0]["name"] == "stt.final"


def test_no_log_path_writes_nothing_and_a_span_outside_a_turn_is_harmless(tmp_path):
    # Timing code that runs outside a turn must still run. It records nothing.
    t.configure(None)
    with t.span("orphan"):
        pass
    assert t.current() is None
    assert list(tmp_path.iterdir()) == []


def test_only_the_first_turn_a_process_serves_is_marked_cold(monkeypatch):
    # Spec §5.2: cold start is reported separately, never averaged in. Nothing set the flag
    # before Task 4.1, so every row of every trace file claimed to be warm.
    monkeypatch.setattr(t, "_cold", True)
    with t.trace(turn_type="A") as first:
        pass
    with t.trace(turn_type="A") as second:
        pass
    assert first.cold_start is True
    assert second.cold_start is False


def test_a_turn_can_start_its_clock_at_end_of_speech_and_place_earlier_marks():
    # The final transcript and the ack happen before the turn's task runs; without a clock
    # set at end-of-speech those marks landed outside any trace and were dropped.
    import time

    final_at = time.perf_counter()
    ack_at = final_at + 0.004
    with t.trace(turn_type="A", t0=final_at) as tr:
        tr.mark_at(t.STT_FINAL, final_at)
        tr.mark_at(t.ACK, ack_at)
    assert [(m.name, round(m.at_ms)) for m in tr.marks] == [("stt.final", 0), ("ack", 4)]
