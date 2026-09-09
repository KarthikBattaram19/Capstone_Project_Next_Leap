"""Speech synthesis starts on the first sentence, not the finished answer (P4)."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass

# One of . ? ! followed by whitespace, but only when the next thing looks like a new
# sentence — and never after "Rs", "sq" or a digit, so "₹35,000." decimals, "Rs." and
# "sq. ft." survive intact.
_BOUNDARY = re.compile(r"(?<!\bRs)(?<!\bsq)(?<!\d)([.?!])\s+(?=[A-Z₹\"'(])")


def split_sentences(text: str) -> list[str]:
    parts, last = [], 0
    for m in _BOUNDARY.finditer(text):
        parts.append(text[last : m.end(1)].strip())
        last = m.end()
    tail = text[last:].strip()
    if tail:
        parts.append(tail)
    return [p for p in parts if p]


@dataclass
class SpeechResult:
    cancelled: bool = False
    tts_failed: bool = False


class Speaker:
    def __init__(self, tts, sink) -> None:
        self._tts, self._sink = tts, sink
        self._cancel = asyncio.Event()

    async def cancel(self) -> None:
        self._cancel.set()
        await self._sink.audio_stop()

    async def speak(self, sentences: AsyncIterator[str] | Iterable[str]) -> SpeechResult:
        self._cancel.clear()
        res = SpeechResult()
        started = False
        it = sentences if hasattr(sentences, "__aiter__") else _aiter(sentences)
        try:
            async for sentence in it:
                if self._cancel.is_set():
                    res.cancelled = True
                    break
                try:
                    async for chunk in self._tts.stream(sentence):
                        if self._cancel.is_set():
                            res.cancelled = True
                            break
                        if not started:
                            await self._sink.audio_start()
                            started = True
                        await self._sink.audio_chunk(chunk)
                except Exception:  # noqa: BLE001 -- the answer still renders as text (§6.53)
                    res.tts_failed = True
                    break
                if res.cancelled:
                    break
        finally:
            if started and not res.cancelled:
                await self._sink.audio_end()
        return res


async def _aiter(items: Iterable[str]) -> AsyncIterator[str]:
    for i in items:
        yield i
