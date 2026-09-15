"""The P1–P8 verifier over small synthetic traces: a passing and a failing case per check.

Rows are built in the exact shape `scout.platform.telemetry.Trace.to_json` writes, so a
change to that shape breaks these tests rather than silently turning every check into
"cannot verify".
"""

import json
from types import SimpleNamespace

from scout.platform import telemetry

from evals.latency.preconditions import verify

RAILWAY_OK = {"deploy": {"healthcheckPath": "/health", "sleepApplication": False}}
SETTINGS_OK = SimpleNamespace(deepgram_endpointing_ms=400, hold_extra_ms=400, job2_effort="low")


def trace(turn_type="A", spans=(), marks=(), turn_id="8f2a91c0d4e1"):
    return {
        "turn_id": turn_id,
        "turn_type": turn_type,
        "cold_start": False,
        "spans": [{"name": n, "start_ms": s, "end_ms": e} for n, s, e in spans],
        "marks": [{"name": n, "at_ms": at} for n, at in marks],
    }


def type_b(tts, first, last, turn_id="b0b0b0b0b0b0"):
    return trace(
        "B",
        spans=[("retrieval", 0.2, 80.7)],
        marks=[
            (telemetry.TTS_FIRST_BYTE, tts),
            (telemetry.LLM_FIRST_TOKEN, first),
            (telemetry.TTS_FIRST_BYTE, tts + 900),  # the second sentence's first byte
            (telemetry.LLM_LAST_TOKEN, last),
        ],
        turn_id=turn_id,
    )


def booking(parent, *calls, name="booking.writes"):
    return trace(
        "A",
        spans=[("external.gemini", 0.0, 900.0), (name, *parent), *calls],
        turn_id="c0c0c0c0c0c0",
    )


def line(lines, tag):
    [hit] = [ln for ln in lines if ln.split(" ", 1)[0] == tag]
    return hit


def run(traces=(), settings=SETTINGS_OK, railway=RAILWAY_OK):
    return verify(settings, list(traces), railway)


def test_names_match_what_the_code_emits():
    # The verifier hard-codes mark names; if telemetry renames one, every trace check would
    # quietly become "cannot verify". Pin them to the module that writes them.
    from evals.latency import preconditions as p

    assert p.TTS_FIRST_BYTE == telemetry.TTS_FIRST_BYTE
    assert p.LLM_FIRST_TOKEN == telemetry.LLM_FIRST_TOKEN
    assert p.LLM_LAST_TOKEN == telemetry.LLM_LAST_TOKEN


def test_real_trace_row_shape_is_accepted_as_json_text():
    tr = telemetry.Trace(turn_type="B")
    tr.marks.append(telemetry.Mark(telemetry.TTS_FIRST_BYTE, 800.0))
    tr.marks.append(telemetry.Mark(telemetry.LLM_FIRST_TOKEN, 1200.0))
    lines = verify(SETTINGS_OK, [tr.to_json() + "\n", "\n"], RAILWAY_OK)
    assert line(lines, "P8") == "P8 ✓ (n=1 Type B traces)"


def test_one_line_per_precondition_in_order():
    tags = [ln.split(" ", 1)[0] for ln in run([type_b(800, 1200, 3000)])]
    assert tags == ["P1", "P2", "P3", "P3b", "P4", "P5", "P6", "P7", "P8"]


# ---- P1


def test_p1_passes_when_sleeping_is_off():
    assert line(run(), "P1") == "P1 ✓ (deploy.sleepApplication = false)"


def test_p1_fails_when_sleeping_is_on():
    got = line(run(railway={"deploy": {"sleepApplication": True}}), "P1")
    assert got == "P1 ✗ deploy.sleepApplication = true"


def test_p1_cannot_verify_without_the_key_or_the_file():
    assert "cannot verify" in line(run(railway={"deploy": {}}), "P1")
    assert "cannot verify" in line(run(railway=None), "P1")


# ---- P2


def test_p2_is_never_a_tick_because_no_span_counts_connections():
    got = line(run([type_b(800, 1200, 3000)]), "P2")
    assert got.startswith("P2 cannot verify:") and "✓" not in got


# ---- P3, P3b, P7 (settings)


def test_p3_p3b_p7_pass_on_the_required_values():
    lines = run()
    assert line(lines, "P3") == "P3 ✓ (deepgram_endpointing_ms = 400)"
    assert line(lines, "P3b") == "P3b ✓ (hold_extra_ms = 400)"
    assert line(lines, "P7") == "P7 ✓ (job2_effort = 'low')"


def test_p3_p3b_p7_fail_on_any_other_value():
    s = SimpleNamespace(deepgram_endpointing_ms=1000, hold_extra_ms=0, job2_effort="high")
    lines = run(settings=s)
    assert line(lines, "P3") == "P3 ✗ deepgram_endpointing_ms = 1000, required 400"
    assert line(lines, "P3b") == "P3b ✗ hold_extra_ms = 0, required 400"
    assert line(lines, "P7") == "P7 ✗ job2_effort = 'high', required 'low'"


def test_settings_checks_use_the_real_settings_field_names():
    from scout.config import Settings

    lines = run(settings=Settings(_env_file=None))
    for tag in ("P3", "P3b", "P7"):
        assert "cannot verify" not in line(lines, tag)


def test_a_missing_settings_field_is_cannot_verify_not_a_tick():
    got = line(run(settings=SimpleNamespace()), "P7")
    assert got == "P7 cannot verify: settings has no job2_effort"


# ---- P4


def test_p4_passes_when_speech_starts_before_the_last_token():
    got = line(
        run([type_b(800, 1200, 3000), trace("A", spans=[("external.gemini", 0, 900)])]), "P4"
    )
    assert got.startswith("P4 ✓ (n=1 traces with a streamed reply)")
    assert "Type A cannot verify" in got  # the gap is stated, not hidden inside the tick


def test_p4_fails_when_speech_waits_for_the_whole_reply():
    got = line(run([type_b(800, 1200, 3000), type_b(3100, 1200, 3000, turn_id="8f2a0000")]), "P4")
    assert got == "P4 ✗ trace 8f2a…: tts.first_byte after llm.last_token (1 of 2 traces)"


def test_p4_cannot_verify_on_eval_traces_with_a_silent_speaker():
    silent = trace("B", marks=[(telemetry.LLM_FIRST_TOKEN, 2600), (telemetry.LLM_LAST_TOKEN, 6700)])
    assert line(run([silent]), "P4").startswith("P4 cannot verify:")


# ---- P5


def test_p5_passes_with_no_osm_span():
    assert line(run([type_b(800, 1200, 3000)]), "P5") == "P5 ✓ (no OSM span in n=1 traces)"


def test_p5_fails_on_any_osm_span():
    live = trace("A", spans=[("external.osm", 10, 400)], turn_id="0sm0sm0sm0sm")
    assert line(run([live]), "P5") == "P5 ✗ trace 0sm0…: external.osm at request time"


def test_p5_cannot_verify_with_no_traces():
    assert line(run([]), "P5") == "P5 cannot verify: no traces given"


# ---- P6


def test_p6_passes_when_both_inserts_overlap_inside_the_span():
    tr = booking(
        (1000.0, 1650.0),
        ("external.google.insert", 1000.5, 1600.0),
        ("external.google.insert", 1000.7, 1649.9),
    )
    assert line(run([tr]), "P6") == "P6 ✓ (n=1 write groups)"


def test_p6_fails_when_the_writes_ran_one_after_the_other():
    tr = booking(
        (1000.0, 2200.0),
        ("external.google.insert", 1000.5, 1600.0),
        ("external.google.insert", 1600.2, 2199.9),
    )
    got = line(run([tr]), "P6")
    assert got.startswith("P6 ✗ trace c0c0…: calendar calls inside booking.writes did not overlap")


def test_p6_fails_on_duration_even_when_the_calls_overlap():
    # Overlapping calls, but the span lasted ≥ 2× the longest: something else sat inside it.
    tr = booking(
        (1000.0, 2400.0),
        ("external.google.insert", 1000.5, 1600.0),
        ("external.google.insert", 1001.0, 1599.0),
    )
    got = line(run([tr]), "P6")
    assert (
        got
        == "P6 ✗ trace c0c0…: booking.writes 1400 ms ≥ 2× the longest call 600 ms (1 of 1 write groups)"
    )


def test_p6_checks_a_reschedule_across_its_four_calls():
    good = booking(
        (0.0, 700.0),
        ("external.google.delete", 1.0, 400.0),
        ("external.google.delete", 1.2, 420.0),
        ("external.google.insert", 1.4, 690.0),
        ("external.google.insert", 1.6, 699.0),
        name="booking.reschedule_writes",
    )
    assert line(run([good]), "P6") == "P6 ✓ (n=1 write groups)"


def test_p6_cannot_verify_without_a_voice_booking():
    got = line(run([type_b(800, 1200, 3000)]), "P6")
    assert got.startswith("P6 cannot verify:")


# ---- P8


def test_p8_passes_when_the_opener_beats_job2s_first_token():
    assert line(run([type_b(800, 1200, 3000)]), "P8") == "P8 ✓ (n=1 Type B traces)"


def test_p8_fails_when_speech_waited_for_job2():
    got = line(run([type_b(1300, 1200, 3000, turn_id="8f2a91c0")]), "P8")
    assert got == "P8 ✗ trace 8f2a…: tts.first_byte after llm.first_token (1 of 1 Type B traces)"


def test_p8_ignores_type_a_and_cannot_verify_without_type_b():
    a_with_marks = trace(
        "A", marks=[(telemetry.TTS_FIRST_BYTE, 900), (telemetry.LLM_FIRST_TOKEN, 100)]
    )
    assert line(run([a_with_marks]), "P8").startswith("P8 cannot verify:")


def test_client_rows_are_not_mistaken_for_traces():
    client_row = {"turn_type": "A", "L0": 1300, "L1": 1400, "L2": 2900, "L4": 3500}
    assert line(run([json.dumps(client_row)]), "P5") == "P5 cannot verify: no traces given"
