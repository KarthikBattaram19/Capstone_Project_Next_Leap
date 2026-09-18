"""The speech lifecycle around a barge-in (production, 2026-09-18).

Conversation 2 had a turn with `stt.final`, `ack` and `shortlist.rendered` but no
`tts.first_byte`: the cards were drawn and nothing was said, with
`barge-in trigger=words state=speaking` in the same log flush. Conversation 3 had a
`trigger=words` barge-in whose turn DID speak, so it is a race, not a rule.

The page (`frontend/src/app/page.tsx`) mutes the mic on `audio_out start` and un-mutes only
when playback finishes. So the one window in which Deepgram can hear the renter while the
server counts itself SPEAKING is between the outcome and the first TTS byte — which is
exactly where those two `trigger=words state=speaking` lines can have come from. Words heard
there are the tail of the utterance that produced this very reply; they must not silence it.

These drive the real Speaker, the real TurnOrchestrator (`_speak_later`, `cancel_speech`) and
the real LiveSession, with a fake TTS and a recording sink.
"""

import asyncio
import types

import pytest

from scout.config import Settings
from scout.contract.outcome import Answered
from scout.contract.viewmodels import AnsweredViewModel
from scout.conversation.live import LiveSession
from scout.conversation.orchestrator import TurnOrchestrator
from scout.conversation.session import Session, SessionManager
from scout.conversation.speaker import Speaker
from scout.conversation.state import TurnState


class FakeStt:
    async def start(self):
        pass

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


class GatedTts:
    """A TTS whose first byte waits on `go`, the way a real provider call does."""

    def __init__(self, chunks: int = 1, gap: float = 0.0) -> None:
        self.go = asyncio.Event()
        self._chunks, self._gap = chunks, gap

    async def stream(self, text: str):
        await self.go.wait()
        for _ in range(self._chunks):
            yield b"\x01" * 320
            if self._gap:
                await asyncio.sleep(self._gap)


class SpeakingOrch:
    """Only what LiveSession calls on the orchestrator — the real methods."""

    cancel_speech = TurnOrchestrator.cancel_speech
    _speak_later = TurnOrchestrator._speak_later
    _start_speech = TurnOrchestrator._start_speech
    _speak = staticmethod(TurnOrchestrator._speak)

    def __init__(self) -> None:
        self.store = types.SimpleNamespace(localities=["Koramangala"])
        self.speaker_factory = None

    async def handle_text(self, session, text, confidence=1.0):
        out = Answered(view_model=AnsweredViewModel(), spoken="I found 3 listings.")
        self._speak_later(session, out)
        return out


def _reply(spoken: str) -> Answered:
    return Answered(view_model=AnsweredViewModel(), spoken=spoken)


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(LiveSession, "_make_stt", lambda self: FakeStt())

    def build(tts):
        s = Settings(_env_file=None, cors_allowed_origins="http://localhost:3000")
        sink = RecordingSink()
        session = LiveSession(s, sink, SpeakingOrch(), SessionManager(60))
        session.session.speaker_factory = lambda: Speaker(tts, sink)
        session.state = TurnState.CAPTURING
        return session, sink

    return build


async def _until(predicate, timeout: float = 3.0) -> bool:
    for _ in range(int(timeout / 0.01)):
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return predicate()


def _kinds(sink) -> list[str]:
    return [e[0] for e in sink.events]


async def test_words_before_the_first_byte_do_not_silence_the_reply_they_asked_for(live):
    """Conversation 2's silent turn: cards drawn, nothing said.

    The reply is decided, the outcome is out, the server is SPEAKING — and not one audio byte
    has gone yet, so the page has not muted the mic. The tail of the renter's own sentence
    lands there. It must not cancel the answer to that very sentence.
    """
    tts = GatedTts(chunks=2)
    session, sink = live(tts)

    await session._final("a 2BHK in Koramangala")
    assert await _until(lambda: session.state is TurnState.SPEAKING), session.state
    assert "audio_start" not in _kinds(sink), "the TTS gate did not hold the first byte"

    await session._interim("in Koramangala")  # the tail of the same utterance

    tts.go.set()
    await _until(lambda: "audio_end" in _kinds(sink))

    assert "audio_start" in _kinds(sink), "the reply to the sentence that interrupted was silenced"
    assert "audio_stop" not in _kinds(sink), "a reply the renter cannot have heard was cancelled"


async def test_words_once_the_reply_is_playing_still_barge_in(live, capsys):
    """The other half: from the first byte on, words are a real interruption and win."""
    tts = GatedTts(chunks=400, gap=0.01)
    session, sink = live(tts)

    await session._final("a 2BHK in Koramangala")
    assert await _until(lambda: session.state is TurnState.SPEAKING)
    tts.go.set()
    assert await _until(lambda: "audio_chunk" in _kinds(sink)), "the reply never started playing"

    await session._interim("no wait, three BHK")

    assert "audio_stop" in _kinds(sink), "the renter spoke over the reply and it kept talking"
    assert session.state is TurnState.CAPTURING
    err = capsys.readouterr().err
    assert "barge-in trigger=words state=speaking" in err
    assert "wait" not in err, "logs carry no transcript text"


async def test_a_cancel_aimed_at_an_older_turn_leaves_the_new_reply_alone():
    """Speech carries the turn it belongs to; a cancel aimed at an older one does nothing."""
    sink = RecordingSink()
    first, second = GatedTts(chunks=1), GatedTts(chunks=1)
    session = Session(id="s")
    orch = SpeakingOrch()

    session.speaker_factory = lambda: Speaker(first, sink)
    orch._speak_later(session, _reply("The older reply."))
    stale_turn = session.speech_turn

    session.speaker_factory = lambda: Speaker(second, sink)
    orch._speak_later(session, _reply("The newer reply."))

    await orch.cancel_speech(session, stale_turn)

    second.go.set()
    await _until(lambda: "audio_end" in _kinds(sink))
    assert "audio_start" in _kinds(sink), "a stale cancel silenced the turn that came after it"


async def test_new_speech_stops_the_audio_the_page_is_still_playing():
    """One speaker at a time. The server leaves SPEAKING when it has finished SENDING, while
    the page plays on for seconds; if the next reply simply started, the page would queue it
    behind audio the renter had already moved past. `audio_out stop` goes first."""
    sink = RecordingSink()
    slow, quick = GatedTts(chunks=400, gap=0.01), GatedTts(chunks=1)
    session = Session(id="s")
    orch = SpeakingOrch()

    session.speaker_factory = lambda: Speaker(slow, sink)
    orch._speak_later(session, _reply("The reply the page is still playing."))
    slow.go.set()
    assert await _until(lambda: "audio_chunk" in _kinds(sink))

    session.speaker_factory = lambda: Speaker(quick, sink)
    orch._speak_later(session, _reply("The next reply."))
    quick.go.set()
    await _until(lambda: _kinds(sink).count("audio_start") == 2)

    kinds = _kinds(sink)
    assert "audio_stop" in kinds, "the next reply was queued behind the one still playing"
    assert kinds.index("audio_stop") < kinds.index("audio_start", kinds.index("audio_start") + 1)
