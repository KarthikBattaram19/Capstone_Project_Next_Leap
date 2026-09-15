"""Smallest.ai Waves — streaming; the first sentence is sent alone, never the whole answer (P4)."""

# Signature verified against smallestai 5.12.0 on 2026-09-05:
#   AsyncSmallestAI(api_key=...).waves.synthesize_tts(
#       *, text, voice_id, model, sample_rate, speed, language,
#       number_pronunciation_language, output_format, pronunciation_dicts,
#       word_timestamps, session_id, request_id, request_options
#   ) -> AsyncIterator[bytes]
# The addendum asked whether this SDK takes model=/sample_rate= here. It does, so both
# are passed from Settings rather than left to the provider's default.

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
from smallestai import AsyncSmallestAI
from smallestai.core.api_error import ApiError

from scout.config import Settings
from scout.platform import faults, telemetry


class SmallestTts:
    def __init__(self, settings: Settings) -> None:
        self._client = AsyncSmallestAI(api_key=settings.smallest_api_key)
        self._voice = settings.smallest_voice_id
        self._model = settings.smallest_model
        self.sample_rate = settings.smallest_sample_rate

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        if mode := faults.active("smallest"):
            raise _injected(mode)
        first = True
        async for chunk in self._client.waves.synthesize_tts(
            text=text,
            voice_id=self._voice,
            model=self._model,
            sample_rate=self.sample_rate,
        ):
            if first:
                telemetry.mark(telemetry.TTS_FIRST_BYTE)
                first = False
                if chunk[:4] == b"RIFF":
                    # Strip a WAV header; the browser plays raw PCM16.
                    chunk = chunk[44:]
            if chunk:
                yield chunk


def _injected(mode: str) -> Exception:
    """What the SDK raises when Smallest really fails that way (Task 4.2 fault switch).

    smallestai 5.12.0's async synthesize_tts raises ApiError(status_code=...) for any status
    it has no named class for (429 and 503 included), and its httpx transport raises the
    timeout. Speaker catches either and the answer still renders as text (§6.53).
    """
    if mode == "timeout":
        return httpx.ReadTimeout("fault injected")
    status = 429 if mode == "429" else 503
    return ApiError(status_code=status, body="fault injected")
