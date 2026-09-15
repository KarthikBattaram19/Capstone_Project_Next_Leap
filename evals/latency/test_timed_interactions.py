"""The Task 4.1 driver's pure parts: the plan, the frames, the rows and the timing arithmetic.

Nothing here reaches a provider, production or Google. The one socket test talks to a fake
gateway on 127.0.0.1, as test_spike_driver.py does.
"""

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import wave
from pathlib import Path

import pytest
import websockets
from scout.contract.messages import HelloIn, OutcomeMsg, TextIn
from scout.contract.outcome import Answered, Degraded, NeedsInput
from scout.contract.viewmodels import AnsweredViewModel, BookingVM, ShortlistVM, SlotVM
from scout.conversation.router import classify_turn

from evals.latency.score import TARGETS_MS, score

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "timed_interactions.py"
_spec = importlib.util.spec_from_file_location("timed_interactions", SCRIPT)
ti = importlib.util.module_from_spec(_spec)
sys.modules["timed_interactions"] = ti  # dataclasses resolve string annotations through it
_spec.loader.exec_module(ti)

EMAIL = "renter@example.com"


def plan():
    return ti.build_plan(EMAIL)


# ---- the plan


def test_the_plan_is_the_twenty_interactions_the_addendum_names():
    assert ti.measure_counts(plan()) == {"A": 8, "B": 6, "L6": 3, "L7": 2, "L8": 1}


def test_every_timed_utterance_routes_to_the_turn_type_it_is_scored_as():
    # The server decides A or B by pattern (router.classify_turn); a row scored as B whose
    # words the server routes to A would put a Type A time against the Type B target.
    for s in plan():
        if s.measure not in ("A", "B", "L6"):
            continue
        has_shortlist = s.name != "brief"  # only the brief arrives before a shortlist exists
        want = "B" if s.measure == "B" else "A"
        assert classify_turn(s.say, has_shortlist=has_shortlist) == want, s.id


def test_each_conversation_books_before_it_cancels_reschedules_or_polls_mail():
    steps = plan()
    for c in (1, 2, 3):
        names = [s.name for s in steps if s.conversation == c]
        booked_at = names.index("booking-yes")
        for later in ("reschedule", "cancel", "cleanup", "pdf"):
            if later in names:
                assert names.index(later) > booked_at, (c, later)


def test_the_pdf_is_timed_where_no_reschedule_mails_a_second_one():
    steps = plan()
    [mail] = [s for s in steps if s.via == "mail"]
    assert not any(s.via == "reschedule" and s.conversation == mail.conversation for s in steps)


def test_every_booking_made_is_cancelled_by_the_end():
    steps = plan()
    for c in (1, 2, 3):
        vias = [s.via for s in steps if s.conversation == c]
        assert vias.count("cancel") == 1 and vias[-1] == "cancel", c


def test_voice_steps_name_a_recording_and_typed_steps_do_not():
    for s in plan():
        if s.via == "voice":
            assert s.wav and s.wav.endswith(".wav"), s.id
        else:
            assert s.wav is None, s.id
    [email] = [s for s in plan() if s.name == "email" and s.conversation == 1]
    assert email.via == "text" and email.say == EMAIL


def test_every_expectation_is_a_known_check():
    assert {s.expect for s in plan()} <= set(ti.EXPECT)


# ---- frames and outcomes, against the contract's own models


def test_frames_the_driver_sends_validate_against_the_contract():
    HelloIn.model_validate_json(ti.hello_frame())
    assert TextIn.model_validate_json(ti.text_frame("The first slot")).text == "The first slot"


SLOT = SlotVM(
    start_ist="2026-09-16T10:00:00+05:30", end_ist="2026-09-16T11:00:00+05:30", spoken="x"
)


def _outcome(o) -> dict:
    # Through OutcomeMsg, exactly as WsSink.outcome sends it.
    return json.loads(OutcomeMsg(outcome=o).model_dump_json())["outcome"]


def _needs(field):
    return _outcome(NeedsInput(question="q", field=field, spoken="q"))


def test_expectations_read_the_outcome_fields_the_backend_sends():
    booking = BookingVM(
        code="ABC234",
        listing_id="kor-001",
        slot=SLOT,
        state="booked",
        pdf_status="pending",
        calendar_sync="complete",
    )
    booked = _outcome(Answered(view_model=AnsweredViewModel(booking=booking), spoken="Booked"))
    shortlist = _outcome(
        Answered(
            view_model=AnsweredViewModel(shortlist=ShortlistVM(order=["kor-001"], groups=[])),
            spoken="Here",
        )
    )
    degraded = _outcome(
        Degraded(view_model=AnsweredViewModel(), missing=["explanation"], why="down", spoken="x")
    )
    assert ti.outcome_matches("readback", _needs("constraints_readback"))
    assert ti.outcome_matches("slots", _needs("slot"))
    assert ti.outcome_matches("email", _needs("email"))
    assert ti.outcome_matches("email_confirm", _needs("email_confirm"))
    assert ti.outcome_matches("booked", booked)
    assert ti.outcome_matches("shortlist", shortlist)
    assert ti.outcome_matches("explanation", degraded)
    assert not ti.outcome_matches("booked", _needs("slot"))  # "slot taken" re-offer
    assert not ti.outcome_matches("shortlist", booked)
    assert not ti.outcome_matches("any", None)  # no outcome at all never matches


# ---- the clock, the rows and the arithmetic


def _clock_from(frames, first_sent=10.0, last_sent=12.0):
    clock = ti.TurnClock(first_sent=first_sent, last_sent=last_sent)
    for at, f in frames:
        ti.observe(clock, at, f)
    return clock


GATEWAY_SEQUENCE = [
    (11.3, json.dumps({"type": "transcript", "text": "two bhk", "final": False})),
    (11.9, json.dumps({"type": "transcript", "text": "two bhk", "final": False})),
    (13.0, b"\x00\x00"),  # audio before `start` is not first audio
    (13.5, json.dumps({"type": "transcript", "text": "two bhk", "final": True})),
    (13.6, json.dumps({"type": "ack", "text": "two bhk", "state": "processing"})),
    (14.8, json.dumps({"type": "audio_out", "event": "start", "sample_rate": 24000})),
    (14.9, b"\x00\x00"),
    (15.4, json.dumps({"type": "outcome", "outcome": {"kind": "answered"}})),
    (16.0, b"\x00\x00"),
    (19.0, json.dumps({"type": "audio_out", "event": "end"})),
]


def test_observe_keeps_the_first_of_each_event():
    c = _clock_from(GATEWAY_SEQUENCE)
    assert (c.first_interim, c.ack, c.first_audio, c.outcome, c.speech_ended) == (
        11.3,
        13.6,
        14.9,
        15.4,
        19.0,
    )
    assert c.payload == {"kind": "answered"}


@pytest.mark.parametrize(
    ("measure", "audio_key", "outcome_key", "absent"),
    [("A", "L2", "L4", ("L3", "L5")), ("B", "L3", "L5", ("L2", "L4"))],
)
def test_turn_row_uses_the_spike_rules(measure, audio_key, outcome_key, absent):
    step = ti.Step(1, "x", "voice", "words", "x.wav", measure)
    row = ti.turn_row(step, _clock_from(GATEWAY_SEQUENCE), "prod")
    # L0 from the FIRST frame sent (10.0); every other stage from the LAST (12.0).
    assert row["L0"] == 1300.0
    assert row["L1"] == 1600.0
    assert row[audio_key] == 2900.0
    assert row[outcome_key] == 3400.0
    assert row["turn_type"] == measure and row["interaction"] == "c1.x" and row["label"] == "prod"
    assert not any(k in row for k in absent) and "cold_start" not in row and "timed_out" not in row


def test_a_turn_that_never_answers_is_a_2x_violation_not_a_gap():
    step = ti.Step(1, "x", "voice", "words", "x.wav", "B")
    clock = _clock_from(GATEWAY_SEQUENCE[:5])
    clock.gave_up = 12.0 + ti.TURN_TIMEOUT_S
    row = ti.turn_row(step, clock, "prod")
    assert row["timed_out"] is True and row["L5"] == ti.TURN_TIMEOUT_S * 1000
    assert row["L3"] is None  # no audio is not a latency; TTS failure has its own row (§6.53)
    assert any("B/L5: single request" in v for v in score([row]).violations)
    assert not ti.row_measured(row)


def test_cold_start_rows_are_flagged_and_left_out_of_scoring():
    step = ti.Step(1, "brief", "voice", "words", "x.wav", "A")
    row = ti.turn_row(step, _clock_from(GATEWAY_SEQUENCE), "prod", cold_start=True)
    assert row["cold_start"] is True
    rep = score([row])
    assert rep.cold_start_counts == {"A": 1} and rep.p99 == {}


def test_booking_row_times_the_yes_to_the_booked_outcome():
    step = ti.Step(2, "booking-yes", "voice", "Yes", "yes.wav", "L6", "booked")
    row = ti.booking_row(step, _clock_from(GATEWAY_SEQUENCE), "prod")
    assert row == {"turn_type": "A", "L6": 3400.0, "interaction": "c2.booking-yes", "label": "prod"}
    assert ti.row_measured(row)


def test_http_and_mail_rows_and_what_counts_as_measured():
    step = ti.Step(1, "reschedule", "reschedule", measure="L7")
    ok = ti.http_row(step, 100.0, 101.25, 200, "prod")
    assert ok["L7"] == 1250.0 and ti.row_measured(ok)
    assert not ti.row_measured(ti.http_row(step, 100.0, 100.1, 503, "prod"))
    mail = ti.Step(3, "pdf", "mail", measure="L8")
    got = ti.mail_row(mail, 50.0, 62.5, True, "prod")
    assert got["L8"] == 12500.0 and ti.row_measured(got)
    late = ti.mail_row(mail, 50.0, 170.0, False, "prod")
    assert not ti.row_measured(late)
    rep = score([ok, got, late])
    assert rep.p99["A"]["L7"] == 1250.0
    assert any("A/L8: single request 120000" in v for v in rep.violations)
    assert TARGETS_MS["L8"] == 30000


def test_http_base_sits_beside_the_socket():
    assert ti.http_base("wss://x.up.railway.app/ws") == "https://x.up.railway.app"
    assert ti.http_base("ws://127.0.0.1:8000/ws") == "http://127.0.0.1:8000"


def test_gmail_query_asks_the_inbox_not_the_sent_copy():
    assert ti.gmail_query("ABC234") == "subject:ABC234 in:inbox"


async def test_poll_until_returns_when_found_and_gives_up_on_time():
    calls = {"n": 0}

    async def third_time():
        calls["n"] += 1
        return calls["n"] == 3

    _, found = await ti.poll_until(third_time, timeout_s=5, poll_s=0.01)
    assert found and calls["n"] == 3

    async def never():
        return False

    t0 = asyncio.get_running_loop().time()
    _, found = await ti.poll_until(never, timeout_s=0.05, poll_s=0.01)
    assert not found and asyncio.get_running_loop().time() - t0 < 1


def test_problems_are_found_before_anything_connects(tmp_path):
    steps = plan()
    got = ti.problems(steps, tmp_path, None, None)
    assert any("--email" in p for p in got)
    assert any("recordings missing" in p and "yes.wav" in p for p in got)
    assert any("--gmail-reader-credentials" in p for p in got)
    for name in {s.wav for s in steps if s.wav}:
        (tmp_path / name).write_bytes(b"")
    reader = tmp_path / "reader.json"
    reader.write_text("{}")
    assert ti.problems(steps, tmp_path, reader, EMAIL) == []
    # A cold start is one spoken brief: it needs neither an email nor a mail reader.
    assert ti.problems(steps[:1], tmp_path, None, None) == []


def test_dry_run_prints_the_plan_and_connects_to_nothing():
    # Port 9 on localhost: were anything opened, the run would fail, not print a plan.
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "--url", "ws://127.0.0.1:9/ws", "--label", "t", "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        cwd=REPO,
        timeout=60,
        check=True,
    ).stdout
    assert "nothing sent" in out
    assert "c3.pdf" in out and "timed: A 8 · B 6 · L6 3 · L7 2 · L8 1 = 20" in out
    assert "cannot run:" in out  # no wav dir, email or reader given
    assert not (REPO / "latency" / "timed-t.jsonl").exists()


# ---- one conversation against a fake gateway on localhost


def _wav(path: Path, ms: int = 100) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x11\x22" * (16000 * ms // 1000))
    return path


async def _gateway(ws):
    """hello, then per turn: (interim if spoken) ack, audio start, a chunk, outcome, end."""
    assert json.loads(await ws.recv())["type"] == "hello"
    await ws.send(json.dumps({"type": "hello", "contract_version": "1", "session_id": "s1"}))
    spoken = False
    async for msg in ws:
        if isinstance(msg, bytes):
            if any(msg):
                if not spoken:
                    await ws.send(json.dumps({"type": "transcript", "text": "y", "final": False}))
                spoken = True
                continue
            if not spoken:
                continue  # silence with no speech before it
            spoken = False
        else:
            assert json.loads(msg)["type"] == "text"
        await ws.send(json.dumps({"type": "ack", "text": "y", "state": "processing"}))
        await ws.send(json.dumps({"type": "audio_out", "event": "start", "sample_rate": 24000}))
        await ws.send(b"\x00\x00" * 240)
        await ws.send(json.dumps({"type": "outcome", "outcome": {"kind": "needs_input"}}))
        await ws.send(json.dumps({"type": "audio_out", "event": "end"}))


async def test_one_session_carries_a_spoken_and_a_typed_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(ti, "SETTLE_S", 0.0)
    pcm = ti._spike.read_pcm16(_wav(tmp_path / "yes.wav"))
    async with websockets.serve(_gateway, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        conv = await ti.Conversation.open(f"ws://127.0.0.1:{port}")
        try:
            assert conv.session_id == "s1"
            spoken = await asyncio.wait_for(
                conv.turn(ti.Step(1, "a", "voice", "Yes", "yes.wav", "A"), pcm, timeout_s=10), 20
            )
            typed = await asyncio.wait_for(
                conv.turn(ti.Step(1, "b", "text", "The first slot"), None, timeout_s=10), 20
            )
        finally:
            await conv.close()

    row = ti.turn_row(ti.Step(1, "a", "voice", "Yes", "yes.wav", "A"), spoken, "t")
    assert row["L0"] > 0 and row["L1"] is not None and row["L2"] <= row["L4"]
    assert spoken.speech_ended is not None  # waited for the reply to finish before moving on
    assert typed.outcome is not None and typed.first_interim is None
    assert typed.first_audio is not None  # its own audio, not the previous turn's
    assert typed.first_audio > spoken.speech_ended
