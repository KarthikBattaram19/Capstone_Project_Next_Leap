"""Speech recognition lost (spec §6.23): one transparent reconnect, then say which capability is down.

Found reading the fault switch's Deepgram path (Task 4.2): the reconnect's own `start()` ran
without a guard, so a second failure escaped `LiveSession.audio`, the WebSocket endpoint
caught nothing but a disconnect, and the socket died. The browser then showed "can't reach
the service" (§6.12) for what was a speech-recognition outage, and the typed fallback the
"unavailable" line offers was gone with it. A stream that refused to open at session start
did the same.
"""

from scout.config import Settings
from scout.contract.outcome import Answered
from scout.contract.viewmodels import AnsweredViewModel
from scout.conversation.live import LiveSession
from scout.conversation.session import SessionManager


class DeadStt:
    """A Deepgram stream that will not open and, if asked, will not carry audio."""

    async def start(self):
        raise ConnectionError("deepgram refused the stream")

    async def close(self):
        pass

    async def send_audio(self, pcm):
        raise ConnectionError("socket gone")

    async def keepalive(self):
        pass


class OpenThenDropStt(DeadStt):
    async def start(self):
        pass


class PayloadSink:
    def __init__(self):
        self.outcomes = []

    async def outcome(self, payload):
        self.outcomes.append(payload["outcome"])

    async def transcript(self, text, final):
        pass

    async def ack(self, text):
        pass

    async def audio_start(self):
        pass

    async def audio_chunk(self, pcm):
        pass

    async def audio_end(self):
        pass

    async def audio_stop(self):
        pass


class TypedOrch:
    store = type("S", (), {"manifest": type("M", (), {"localities": {"Koramangala": 1}})()})()

    def __init__(self):
        self.heard = []

    async def handle_text(self, session, text):
        self.heard.append(text)
        return Answered(view_model=AnsweredViewModel(), spoken="ok")

    async def cancel_speech(self, session):
        pass


def _session(monkeypatch, *streams):
    queue = list(streams)
    monkeypatch.setattr(LiveSession, "_make_stt", lambda self: queue.pop(0))
    s = Settings(_env_file=None, cors_allowed_origins="http://localhost:3000")
    sink, orch = PayloadSink(), TypedOrch()
    return LiveSession(s, sink, orch, SessionManager(60)), sink, orch


def _speech_in(sink):
    return [o for o in sink.outcomes if o.get("capability") == "speech_in"]


async def test_a_failed_reconnect_says_speech_is_unavailable_instead_of_raising(monkeypatch):
    live, sink, _ = _session(monkeypatch, OpenThenDropStt(), DeadStt())
    await live.start()

    await live.audio(b"\x00\x00")  # the stream drops; the one reconnect is refused

    told = _speech_in(sink)
    assert len(told) == 1
    assert told[0]["kind"] == "failed"
    assert "Speech recognition is unavailable" in told[0]["tell_renter"]
    await live.close()


async def test_audio_after_speech_is_down_is_dropped_and_told_only_once(monkeypatch):
    live, sink, _ = _session(monkeypatch, OpenThenDropStt(), DeadStt())
    await live.start()

    for _ in range(50):  # the browser keeps streaming mic frames at ~50 a second
        await live.audio(b"\x00\x00")

    assert len(_speech_in(sink)) == 1
    await live.close()


async def test_a_stream_that_will_not_open_leaves_the_session_usable_by_typing(monkeypatch):
    live, sink, orch = _session(monkeypatch, DeadStt())

    await live.start()  # must not raise: the socket stays up for the typed fallback (§6.13)

    told = _speech_in(sink)
    assert len(told) == 1
    assert "You can type instead" in told[0]["tell_renter"]
    await live.text("two BHK in Koramangala")
    await live._turn
    assert orch.heard == ["two BHK in Koramangala"]
    await live.close()


async def test_a_successful_reconnect_asks_for_the_lost_words_again(monkeypatch):
    live, sink, _ = _session(monkeypatch, OpenThenDropStt(), OpenThenDropStt())
    await live.start()

    await live.audio(b"\x00\x00")

    told = _speech_in(sink)
    assert len(told) == 1
    assert "Please say it again" in told[0]["tell_renter"]
    await live.close()
