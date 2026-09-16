"""The WebSocket-side rules: the P3b hold, ack-before-any-model, barge-in, and never going silent.

The last two were guarded by the walking skeleton's own tests until Task 2.10 deleted it. A
turn runs as a task nobody awaits, so an exception inside it is swallowed by the event loop
and the browser is left after `audio_out start` with nothing at all — which is how an unset
SMALLEST_VOICE_ID presented in production. The guarantees move here with the code.
"""

import asyncio
import time
import types

import pytest

from scout.config import Settings
from scout.contract.outcome import Answered
from scout.contract.viewmodels import AnsweredViewModel
from scout.conversation.live import RUNAWAY_S, LiveSession
from scout.conversation.session import SessionManager
from scout.conversation.state import TurnState

HOLD_S = 0.4


class FakeStt:
    def __init__(self):
        self.started = False

    async def start(self):
        self.started = True

    async def close(self):
        pass

    async def send_audio(self, pcm):
        pass

    async def keepalive(self):
        pass


class RecordingSink:
    def __init__(self):
        self.events = []

    async def transcript(self, text, final):
        self.events.append(("transcript", text, final))

    async def ack(self, text):
        self.events.append(("ack", text, None))

    async def audio_start(self):
        self.events.append(("audio_start", None, None))

    async def audio_chunk(self, pcm):
        self.events.append(("audio_chunk", None, None))

    async def audio_end(self):
        self.events.append(("audio_end", None, None))

    async def audio_stop(self):
        self.events.append(("audio_stop", None, None))

    async def outcome(self, payload):
        self.events.append(("outcome", payload["outcome"]["kind"], None))

    def acks(self):
        return [e for e in self.events if e[0] == "ack"]


class FakeOrch:
    """Stands in for the orchestrator: LiveSession only calls these two."""

    def __init__(self, handler=None):
        self.store = type("S", (), {"localities": ["Koramangala"]})()
        self.cancelled = 0
        self._handler = handler

    async def handle_text(self, session, text, confidence=1.0):
        if self._handler is not None:
            return await self._handler(session, text)
        return Answered(view_model=AnsweredViewModel(), spoken="ok")

    async def cancel_speech(self, session):
        self.cancelled += 1


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(LiveSession, "_make_stt", lambda self: FakeStt())

    def build(handler=None):
        s = Settings(_env_file=None, cors_allowed_origins="http://localhost:3000")
        sink = RecordingSink()
        session = LiveSession(s, sink, FakeOrch(handler), SessionManager(60))
        session.state = TurnState.CAPTURING  # the renter has started speaking
        return session, sink

    return build


async def test_an_unfinished_phrase_waits_for_the_rest_and_acks_once(live):
    session, sink = live()
    await session._final("two BHK under")
    await asyncio.sleep(0.25)
    assert not sink.acks(), "acknowledged mid-sentence; the hold did not hold"

    await session._final("forty thousand")
    await asyncio.sleep(0.05)
    acks = sink.acks()
    assert len(acks) == 1
    assert acks[0][1] == "two BHK under forty thousand"


async def test_the_hold_expires_when_nothing_more_arrives(live):
    session, sink = live()
    await session._final("budget forty")
    await asyncio.sleep(0.2)
    assert not sink.acks()
    await asyncio.sleep(HOLD_S)
    acks = sink.acks()
    assert len(acks) == 1
    assert acks[0][1] == "budget forty"


async def test_utterance_end_during_a_hold_acks_immediately(live):
    session, sink = live()
    await session._final("two BHK under")
    await session._utterance_end()
    acks = sink.acks()
    assert len(acks) == 1
    assert acks[0][1] == "two BHK under"


async def test_the_ack_precedes_any_model_call(live):
    order = []

    async def handler(session, text):
        order.append("model")
        return Answered(view_model=AnsweredViewModel(), spoken="ok")

    session, sink = live(handler)
    await session._final("two BHK in Koramangala")
    await asyncio.wait_for(session._turn, timeout=5)
    assert sink.events[0][0] == "transcript"
    assert [e[0] for e in sink.events].index("ack") >= 0
    assert order == ["model"]
    # L1: the acknowledgement is already out before the model is asked anything.
    assert sink.events[1][0] == "ack"


async def test_a_turn_that_raises_reports_a_failure_instead_of_silence(live):
    async def boom(session, text):
        raise RuntimeError("job 1 is down")

    session, sink = live(boom)
    await session._final("two BHK in Koramangala")
    await asyncio.wait_for(session._turn, timeout=5)
    assert ("outcome", "failed", None) in sink.events
    assert session.state is TurnState.IDLE


async def test_words_during_a_turn_are_barge_in_but_a_sound_onset_alone_is_not(live):
    async def slow(session, text):
        await asyncio.sleep(5)
        return Answered(view_model=AnsweredViewModel(), spoken="too late")

    session, sink = live(slow)
    await session._final("two BHK in Koramangala")
    first = session._turn
    await asyncio.sleep(0.05)  # it is mid-turn now
    await session._speech_started()  # a breath, a cough: Deepgram's VAD fires on it
    assert session.orch.cancelled == 0 and not first.done(), "an onset alone cancelled the turn"
    assert session.state is TurnState.TYPE_A

    await session._interim("no wait")  # real words: the renter's new sentence wins
    assert session.orch.cancelled == 1, "the speaker must be told to stop"
    # _run_turn swallows the CancelledError and returns, so the task ends done, not
    # cancelled — what matters is that it stops and never answers.
    await first
    assert first.done(), "the interrupted turn must not keep going"
    assert session.state is TurnState.CAPTURING
    assert not [e for e in sink.events if e[0] == "outcome"], "the stale turn still answered"


async def test_an_onset_with_no_words_while_thinking_still_ends_in_an_outcome(live):
    # Production, 2026-09-10: the renter answered the readback, the VAD fired again on
    # nothing, the turn was cancelled, and the page sat in "processing" forever.
    async def job1(session, text):
        await asyncio.sleep(0.3)
        return Answered(view_model=AnsweredViewModel(), spoken="ok")

    session, sink = live(job1)
    await session._final("yes")
    await asyncio.sleep(0.05)
    await session._speech_started()
    await session._utterance_end()  # ...and no words ever follow
    await asyncio.sleep(0.6)
    assert [e for e in sink.events if e[0] == "outcome"], f"stuck in {session.state}"
    assert session.state is TurnState.IDLE


async def test_a_spoken_turn_trace_carries_the_final_transcript_and_the_ack(live, tmp_path):
    import json

    from scout.platform import telemetry

    log = tmp_path / "latency.jsonl"
    telemetry.configure(str(log))
    try:
        session, _ = live()
        await session._final("two BHK in Koramangala")
        await asyncio.wait_for(session._turn, timeout=5)
    finally:
        telemetry.configure(None)

    marks = {m["name"]: m["at_ms"] for m in json.loads(log.read_text().splitlines()[0])["marks"]}
    assert 0 <= marks["stt.final"] <= marks["ack"]


# --- §6 walkthrough rows: guards that were read but not executed (Task 4.2) ---


def _outcomes(sink):
    return [e for e in sink.events if e[0] == "outcome"]


async def test_an_utterance_with_no_words_re_prompts_once_and_never_reaches_job1(live):
    """Spec §6.18. An empty transcript must not be sent to Job 1, and the re-prompt is
    once per run of silences - a renter who is simply not speaking should not be nagged
    on every hold expiry."""
    session, sink = live()

    await session._finalize()  # nothing captured at all

    outs = _outcomes(sink)
    assert len(outs) == 1 and outs[0][1] == "failed"
    assert not sink.acks(), "an empty transcript was acknowledged as if it were an utterance"
    assert session.state is TurnState.IDLE

    session.state = TurnState.CAPTURING
    await session._finalize()  # silent again, immediately
    assert len(_outcomes(sink)) == 1, "the re-prompt repeated on a run of silences"


async def test_the_re_prompt_suppressor_clears_once_words_arrive(live):
    """The other half of §6.18: the suppressor covers a run of silences, not the session,
    so a renter who goes quiet again later is answered rather than met with nothing."""
    session, sink = live()
    await session._finalize()
    assert len(_outcomes(sink)) == 1

    session.state = TurnState.CAPTURING
    await session._final("a 2BHK in Koramangala")
    await asyncio.sleep(0.05)
    await session._utterance_end()
    await asyncio.sleep(0.05)
    assert sink.acks(), "the utterance with words was not acknowledged"

    session.state = TurnState.CAPTURING
    await session._finalize()  # silent again, but after a real utterance
    assert len(_outcomes(sink)) >= 2, "the suppressor never cleared; the renter met silence"


async def test_a_runaway_utterance_is_capped_and_what_was_captured_still_runs(live):
    """Spec §6.19. Capture stops at RUNAWAY_S rather than waiting for an end-of-speech that
    is not coming, and the words captured so far are transcribed and confirmed back - not
    discarded, which would lose everything the renter said."""
    session, sink = live()
    session._segments = ["a 2BHK in Koramangala under 35,000"]
    session._speech_started_at = time.monotonic() - (RUNAWAY_S + 1.0)

    await session.audio(b"\x00" * 320)  # the frame that crosses the cap
    await asyncio.sleep(0.05)

    assert session._speech_started_at is None, "the cap did not finalise the utterance"
    acks = sink.acks()
    assert acks and acks[0][1] == "a 2BHK in Koramangala under 35,000"


async def test_the_cap_does_not_fire_on_an_utterance_inside_the_limit(live):
    """The cap has to be a cap, not a timeout on every turn."""
    session, sink = live()
    session._segments = ["still talking"]
    session._speech_started_at = time.monotonic()  # just started

    await session.audio(b"\x00" * 320)
    await asyncio.sleep(0.05)

    assert session._speech_started_at is not None
    assert not sink.acks()


async def test_the_greeting_is_sent_and_spoken_before_the_microphone_is_heard(monkeypatch):
    """Arch §11.2 P-7, addendum Task 2.10: on hello Nakshatra speaks first, from a constant.

    Never wired until 2026-09-16, when the browser walkthrough found a click on the mic
    produced silence. It travels as an ordinary `answered` outcome - no contract change -
    and is emitted before the STT stream opens, so no provider sits on the path to it.
    """
    from scout.conversation import live as live_mod
    from scout.conversation import persona
    from scout.conversation.speaker import split_sentences

    order = []
    spoken = []

    class Stt(FakeStt):
        async def start(self):
            order.append("stt_open")

    class FakeSpeaker:
        def __init__(self, tts, sink):
            pass

        async def speak(self, sentences):
            spoken.append(list(sentences))

        async def cancel(self):
            pass

    class Sink(RecordingSink):
        async def outcome(self, payload):
            order.append("outcome")
            self.last = payload["outcome"]
            await super().outcome(payload)

    monkeypatch.setattr(LiveSession, "_make_stt", lambda self: Stt())
    monkeypatch.setattr(live_mod, "Speaker", FakeSpeaker)
    s = Settings(_env_file=None, cors_allowed_origins="http://localhost:3000")
    sink = Sink()
    session = LiveSession(s, sink, FakeOrch(), SessionManager(60))

    await session.start()
    await asyncio.sleep(0.01)

    assert order[:2] == ["outcome", "stt_open"]
    assert sink.last["kind"] == "answered"
    assert sink.last["spoken"] == persona.GREETING
    assert sink.last["view_model"]["notices"] == [persona.GREETING]
    assert spoken == [split_sentences(persona.GREETING)]
    assert session.state is TurnState.IDLE, "the greeting must not look like a turn in flight"


async def test_a_stale_sound_onset_does_not_start_the_runaway_clock(live, monkeypatch):
    """Production, 2026-09-17: a noise onset just after the greeting set the §6.19 clock, no
    words followed, and 35 s later the renter's first frame tripped the 30 s cap - an empty
    utterance, answered "I didn't hear anything" while their words were still arriving. The
    cap measures an utterance, so its clock starts at the first words, not at a sound."""
    from scout.conversation import live as live_mod

    now = [1000.0]
    # Only live.py's clock: patching time.monotonic itself would freeze the event loop.
    fake = types.SimpleNamespace(monotonic=lambda: now[0], perf_counter=time.perf_counter)
    monkeypatch.setattr(live_mod, "time", fake)
    session, sink = live()
    session.state = TurnState.IDLE

    await session._speech_started()  # a cough, a chair - no words follow
    now[0] += RUNAWAY_S + 5
    await session._interim("two BHK in Koramangala")  # the real utterance begins now
    now[0] += 0.1
    await session.audio(bytes(320))
    await asyncio.sleep(0.05)

    assert not _outcomes(sink), "the cap fired on a clock started by a sound, not by words"
    assert session._speech_started_at == 1000.0 + RUNAWAY_S + 5
