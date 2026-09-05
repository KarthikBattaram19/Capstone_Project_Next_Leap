"""A turn that raises must tell the browser, not go silent.

The stub runs each turn as a bare asyncio task. Nobody awaits it, so an exception
inside it is swallowed by the event loop: the browser gets `audio_out start` and
then nothing at all — no chunks, no end, no outcome, no error. That is how an unset
SMALLEST_VOICE_ID presented in production: the page simply never spoke.
"""

import asyncio

from scout.config import Settings
from scout.conversation.stub_turn import StubSession


class RecordingSink:
    def __init__(self):
        self.events = []

    async def transcript(self, text, final):
        self.events.append(("transcript", final))

    async def ack(self, text):
        self.events.append(("ack", None))

    async def audio_start(self):
        self.events.append(("audio_start", None))

    async def audio_chunk(self, pcm):
        self.events.append(("audio_chunk", len(pcm)))

    async def audio_end(self):
        self.events.append(("audio_end", None))

    async def audio_stop(self):
        self.events.append(("audio_stop", None))

    async def outcome(self, payload):
        self.events.append(("outcome", payload.get("kind")))


class ExplodingTts:
    sample_rate = 24000

    async def stream(self, text):
        raise RuntimeError("voice_id is not available on this model")
        yield b""  # pragma: no cover - makes this an async generator


async def test_a_failing_tts_reports_a_failed_outcome_instead_of_silence():
    session = StubSession(Settings(_env_file=None), RecordingSink())
    session.tts = ExplodingTts()

    async def echo(system, user, schema_name, schema):
        return {"echo": user}

    session.groq.complete_json = echo

    await session._run("two bhk in koramangala", "A")

    kinds = [name for name, _ in session.sink.events]
    assert "ack" in kinds, "the acknowledgement must still go out"
    assert ("outcome", "failed") in session.sink.events, (
        f"expected a failed outcome; got {session.sink.events}"
    )


async def test_the_turn_task_never_swallows_an_exception():
    # _final schedules the turn as a task. If that task dies unobserved the browser
    # waits forever, which is exactly what happened on the deployed skeleton.
    session = StubSession(Settings(_env_file=None), RecordingSink())
    session.tts = ExplodingTts()

    async def boom(*a, **k):
        raise RuntimeError("job 1 is down")

    session.groq.complete_json = boom

    await session._final("anything")
    assert session._turn is not None
    await asyncio.wait_for(session._turn, timeout=5)
    assert ("outcome", "failed") in session.sink.events
