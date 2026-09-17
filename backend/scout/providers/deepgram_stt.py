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
from deepgram.core.api_error import ApiError
from deepgram.core.events import EventType
from websockets.exceptions import ConnectionClosedError

from scout.config import Settings
from scout.platform import faults, telemetry
from scout.platform.retry import RATE_LIMITED, retry_once_on_rate_limit

Handler = Callable[[str], Awaitable[None]]

DOMAIN_TERMS = ["BHK", "lakh", "deposit", "maintenance", "semi furnished", "fully furnished"]


# Deepgram refuses the stream (HTTP 400 "Unexpected error when initializing websocket
# connection") once the keyterm list is too long. Measured 2026-09-10 against nova-3 with
# the real locality names: 80 terms opened, 85 did not; 470 (every locality) never opened,
# which is why no voice turn could start on the first Phase 2 deploy. The limit is not
# documented in the SDK and did not track count, characters or words cleanly (150 one-word
# terms and 40 four-word terms both opened), so the budget below sits well inside every
# passing point rather than at the edge.
MAX_KEYTERMS = 60
MAX_KEYTERM_CHARS = 900


def build_keyterms(localities: dict[str, int] | list[str]) -> list[str]:
    """Generated from the dataset's locality field — never typed by hand (spec §5.1).

    Given the manifest's ``{locality: listing_count}`` the localities with the most
    listings come first, so the budget is spent where the renter is most likely to look;
    a plain list is taken in sorted order. The domain terms are always included.
    """
    if isinstance(localities, dict):
        ranked = sorted(localities, key=lambda name: (-localities[name], name))
    else:
        ranked = sorted(set(localities))
    room = MAX_KEYTERMS - len(DOMAIN_TERMS)
    out: list[str] = []
    used = sum(len(t) for t in DOMAIN_TERMS)
    for name in ranked:
        if len(out) >= room or used + len(name) > MAX_KEYTERM_CHARS:
            break
        out.append(name)
        used += len(name)
    return out + DOMAIN_TERMS


def _injected_on_connect(mode: str) -> Exception:
    """What opening the stream raises when Deepgram really fails that way (Task 4.2).

    deepgram-sdk 7.8.0's connect turns a refused handshake into ApiError(status_code=...);
    a handshake that never answers is the TimeoutError websockets raises on its open timeout.
    """
    if mode == "timeout":
        return TimeoutError("fault injected: timed out opening the Deepgram stream")
    status = 429 if mode == "429" else 503
    return _api_error(status)


def _is_rate_limited(e: BaseException) -> bool:
    return isinstance(e, ApiError) and e.status_code == RATE_LIMITED


def _api_error(status: int) -> ApiError:
    return ApiError(
        status_code=status,
        body="fault injected: Unexpected error when initializing websocket connection.",
    )


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
        self._segments: list[str] = []  # finalised segments of the utterance in progress
        self._confidences: list[float] = []  # one per finalised segment (spec §6.20)

    async def start(self) -> None:
        # Spec §6.54: one retry on a 429, and only on a 429. A refused connection is §6.23,
        # which LiveSession already answers with exactly one transparent reconnect — retrying
        # it here as well would double that and delay "speech is unavailable". This runs at
        # session open, not inside a turn, so the backoff costs nothing against Gate L.
        await retry_once_on_rate_limit(self._connect, _is_rate_limited)

    async def _connect(self) -> None:
        if mode := faults.active("deepgram"):
            raise _injected_on_connect(mode)
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
            utterance_end_ms=self._s.utterance_end_ms,  # P3b hard stop ~1.5 s
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
            # P3b, the ~1.5 s hard stop. If endpointing never fired, whatever was heard
            # is still a complete thought and must be delivered, not stranded.
            await self._flush()
            await self._on_utterance_end()
        elif kind == "Results":
            alt = msg.channel.alternatives[0]
            text = alt.transcript
            if not text:
                return
            if msg.is_final:
                # is_final marks the end of a SEGMENT, not of the utterance: Deepgram
                # finalises at every natural pause, so one sentence produces several.
                # Only speech_final means the person stopped talking (that is what the
                # 400 ms endpointing produces). Treating is_final as the end of a turn
                # started a fresh turn mid-sentence — fourteen turns from two spoken
                # utterances on the deployed service, each with its own TTS audio.
                self._segments.append(text)
                # Spec §6.20. Kept per segment because the utterance's confidence is the
                # WORST of its parts: one clean segment must not average away a noisy one
                # that carried the locality or the budget.
                self._confidences.append(float(getattr(alt, "confidence", 1.0)))
                # NOT even speech_final ends the turn. Measured on real speech
                # 2026-09-06: a 700 ms mid-sentence pause — an ordinary breath before
                # a number — makes Deepgram endpoint and set speech_final, so
                # "two BHK in Koramangala <breath> under forty thousand" arrived as
                # two complete utterances and the second had lost the locality. Only
                # UtteranceEnd (utterance_end_ms, ~1.5 s) means the speaker stopped.
                # Show the words as they land; just do not act on them yet.
                telemetry.mark(telemetry.STT_INTERIM)
                await self._on_interim(" ".join(self._segments))
            else:
                telemetry.mark(telemetry.STT_INTERIM)
                await self._on_interim(" ".join([*self._segments, text]))

    async def _flush(self) -> None:
        # The endpointed message carries only the last segment, so the segments are
        # joined: otherwise a turn acts on "need parking" and loses the locality, the
        # bedroom count and the budget that came before the pause.
        if not self._segments:
            return
        text = " ".join(self._segments)
        # The utterance is only as trustworthy as its worst segment (spec §6.20). An
        # utterance with no scored segment is 1.0: absent evidence of noise is not evidence
        # of noise, and treating it as 0 would confirm every turn.
        confidence = min(self._confidences, default=1.0)
        self._segments = []
        self._confidences = []
        telemetry.mark(telemetry.STT_FINAL)
        await self._on_final(text, confidence)

    async def send_audio(self, pcm16: bytes) -> None:
        if faults.active("deepgram"):
            # Mid-stream, every kind of outage looks the same from here: the socket is gone.
            raise ConnectionClosedError(None, None)
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
