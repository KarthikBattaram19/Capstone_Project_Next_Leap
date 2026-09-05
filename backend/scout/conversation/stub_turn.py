"""Walking-skeleton turn: real providers, placeholder logic. Replaced by the orchestrator in 2.10."""

from __future__ import annotations

import asyncio
import re
import sys

from scout.config import Settings
from scout.platform import telemetry
from scout.providers.anthropic_job2 import AnthropicJob2Client
from scout.providers.deepgram_stt import DeepgramStream
from scout.providers.groq_job1 import GroqJob1Client
from scout.providers.smallest_tts import SmallestTts

STUB_SCHEMA = {
    "type": "object",
    "properties": {"echo": {"type": "string"}},
    "required": ["echo"],
    "additionalProperties": False,
}

STUB_J2_SCHEMA = {
    "type": "object",
    "properties": {"sentences": {"type": "array", "items": {"type": "string"}}},
    "required": ["sentences"],
    "additionalProperties": False,
}


class StubSession:
    def __init__(self, settings: Settings, sink) -> None:
        self.s, self.sink = settings, sink
        self.groq = GroqJob1Client(settings)
        self.claude = AnthropicJob2Client(settings)
        self.tts = SmallestTts(settings)
        self.stt = DeepgramStream(
            settings,
            keyterms=["Koramangala", "Indiranagar", "HSR Layout"],
            on_interim=self._interim,
            on_final=self._final,
            on_speech_started=self._noop,
            on_utterance_end=self._noop,
        )
        self._turn: asyncio.Task | None = None

    async def start(self) -> None:
        await self.stt.start()

    async def audio(self, pcm: bytes) -> None:
        await self.stt.send_audio(pcm)

    async def text(self, text: str) -> None:
        await self._final(text)

    async def close(self) -> None:
        await self.stt.close()

    async def _noop(self) -> None:
        pass

    async def _interim(self, text: str) -> None:
        await self.sink.transcript(text, final=False)

    async def _final(self, text: str) -> None:
        turn_type = "B" if re.search(r"\bwhy\b|what.*like|commute", text, re.IGNORECASE) else "A"
        self._turn = asyncio.create_task(self._run(text, turn_type))

    async def _speak(self, sentence: str) -> None:
        await self.sink.audio_start()
        async for chunk in self.tts.stream(sentence):
            await self.sink.audio_chunk(chunk)
        await self.sink.audio_end()

    async def _run(self, text: str, turn_type: str) -> None:
        # A turn runs as a bare task that nobody awaits, so without this the event loop
        # swallows any exception and the browser is left after `audio_out start` with
        # no chunks, no end and no outcome — silence that looks like a hang. Spec §6
        # requires a failure to be shown, and shown differently from "nothing found".
        try:
            await self._turn_body(text, turn_type)
        except Exception as e:  # noqa: BLE001 -- the whole point is that NOTHING
            # escapes this task unreported; narrowing it would restore the silence.
            # Type only: a provider's message can quote the utterance back, and logs
            # carry no transcript text (spec §3.2, §5.3).
            print(f"turn failed ({turn_type}): {type(e).__name__}", file=sys.stderr)
            await self.sink.outcome({"kind": "failed", "reason": type(e).__name__})

    async def _turn_body(self, text: str, turn_type: str) -> None:
        with telemetry.trace(turn_type=turn_type):
            await self.sink.transcript(text, final=True)
            await self.sink.ack(text)  # L1 — before any model call
            telemetry.mark(telemetry.ACK)

            if turn_type == "A":
                data = await self.groq.complete_json(
                    "Echo the user's words as JSON.", text, "echo", STUB_SCHEMA
                )
                await self._speak(f"You said {data['echo']}.")  # L2
                await self.sink.outcome({"kind": "answered", "view_model": {"stub": True}})
                telemetry.mark(telemetry.SHORTLIST_RENDERED)  # L4
            else:
                opener = (
                    "It's thirty-five thousand rupees for a 2BHK, "
                    "about 1.1 km by route to the metro."
                )
                speak_first = asyncio.create_task(
                    self._speak(opener)
                )  # P8: sound before Job 2 (L3)
                buf = ""
                async for delta in self.claude.stream_json(
                    "Reply with two short sentences about Koramangala as JSON.",
                    text,
                    STUB_J2_SCHEMA,
                ):
                    buf += delta
                await speak_first
                await self.sink.outcome(
                    {"kind": "answered", "view_model": {"stub": True, "raw": buf}}
                )
                telemetry.mark(telemetry.EXPLANATION_RENDERED)  # L5
