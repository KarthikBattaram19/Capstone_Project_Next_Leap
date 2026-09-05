"""One Deepgram WebSocket per browser session, kept open for the whole session (P2, arch §7.2)."""

# Signature verified against deepgram-sdk 7.8.0 on 2026-09-05:
#   AsyncDeepgramClient(api_key=...).listen.v1.connect(
#       *, callback, callback_method, channels, detect_entities, diarize, diarize_model,
#       dictation, encoding, endpointing, extra, interim_results, keyterm, keywords,
#       language, mip_opt_out, model (REQUIRED), multichannel, numerals, profanity_filter,
#       punctuate, redact, replace, sample_rate, search, smart_format, tag,
#       utterance_end_ms, vad_events, version, authorization, request_options
#   ) -> AsyncIterator[AsyncV1SocketClient]
# Every parameter this module passes exists. `connect` is an async context manager.
# AsyncV1SocketClient exposes exactly: on, recv, send_close_stream, send_finalize,
# send_keep_alive, send_media, start_listening — all four used below are present.

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from deepgram import AsyncDeepgramClient
from deepgram.core.events import EventType

from scout.config import Settings
from scout.platform import telemetry

Handler = Callable[[str], Awaitable[None]]


class DeepgramStream:
    def __init__(
        self,
        settings: Settings,
        keyterms: list[str],
        *,
        on_interim: Handler,
        on_final: Handler,
        on_speech_started: Callable[[], Awaitable[None]],
        on_utterance_end: Callable[[], Awaitable[None]],
    ) -> None:
        self._s = settings
        self._keyterms = keyterms
        self._on_interim = on_interim
        self._on_final = on_final
        self._on_speech_started = on_speech_started
        self._on_utterance_end = on_utterance_end
        self._client = AsyncDeepgramClient(api_key=settings.deepgram_api_key)
        self._cm = None
        self._conn = None
        self._listener: asyncio.Task | None = None

    async def start(self) -> None:
        self._cm = self._client.listen.v1.connect(
            model=self._s.deepgram_model,
            encoding="linear16",
            sample_rate=self._s.audio_sample_rate,
            channels=1,
            language="en",
            interim_results=True,
            smart_format=True,
            numerals=True,
            vad_events=True,
            endpointing=self._s.deepgram_endpointing_ms,  # P3: 400, no shorter
            utterance_end_ms=self._s.utterance_end_ms,  # P3b hard stop ~1 s
            keyterm=self._keyterms,  # every locality name
        )
        self._conn = await self._cm.__aenter__()
        self._conn.on(EventType.MESSAGE, self._on_message)
        self._conn.on(EventType.ERROR, lambda e: print("deepgram error:", e))
        self._listener = asyncio.create_task(self._conn.start_listening())

    async def _on_message(self, msg) -> None:
        kind = getattr(msg, "type", None)
        if kind == "SpeechStarted":
            await self._on_speech_started()
        elif kind == "UtteranceEnd":
            await self._on_utterance_end()
        elif kind == "Results":
            text = msg.channel.alternatives[0].transcript
            if not text:
                return
            if msg.is_final:
                telemetry.mark(telemetry.STT_FINAL)
                await self._on_final(text)
            else:
                telemetry.mark(telemetry.STT_INTERIM)
                await self._on_interim(text)

    async def send_audio(self, pcm16: bytes) -> None:
        await self._conn.send_media(pcm16)

    async def keepalive(self) -> None:
        await self._conn.send_keep_alive()

    async def close(self) -> None:
        try:
            await self._conn.send_close_stream()
        finally:
            if self._listener:
                self._listener.cancel()
            if self._cm:
                await self._cm.__aexit__(None, None, None)
