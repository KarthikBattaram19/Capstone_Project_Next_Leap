"""The WebSocket-side rules: the P3b hold, ack-before-any-model, barge-in, and never going silent.

The last two were guarded by the walking skeleton's own tests until Task 2.10 deleted it. A
turn runs as a task nobody awaits, so an exception inside it is swallowed by the event loop
and the browser is left after `audio_out start` with nothing at all — which is how an unset
SMALLEST_VOICE_ID presented in production. The guarantees move here with the code.
"""

import asyncio

import pytest

from scout.config import Settings
from scout.contract.outcome import Answered
from scout.contract.viewmodels import AnsweredViewModel
from scout.conversation.live import LiveSession
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

    async def handle_text(self, session, text):
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
