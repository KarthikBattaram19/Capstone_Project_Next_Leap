"""One trace per turn, one span per component (arch §13.3). No PII, no transcript text."""

from __future__ import annotations

import contextvars
import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

# Span names the specification's measurement rules use (spec §5.2):
STT_INTERIM = "stt.interim"
STT_FINAL = "stt.final"
RETRIEVAL = "retrieval"
LLM_FIRST_TOKEN = "llm.first_token"
LLM_LAST_TOKEN = "llm.last_token"
TTS_FIRST_BYTE = "tts.first_byte"
ACK = "ack"
SHORTLIST_RENDERED = "shortlist.rendered"
EXPLANATION_RENDERED = "explanation.rendered"


@dataclass
class Span:
    name: str
    start_ms: float
    end_ms: float = 0.0

    @property
    def duration_ms(self) -> float:
        return self.end_ms - self.start_ms


@dataclass
class Mark:
    name: str
    at_ms: float


@dataclass
class Trace:
    turn_type: str
    turn_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    t0: float = field(default_factory=time.perf_counter)
    spans: list[Span] = field(default_factory=list)
    marks: list[Mark] = field(default_factory=list)
    cold_start: bool = False

    def now_ms(self) -> float:
        return (time.perf_counter() - self.t0) * 1000

    def mark_at(self, name: str, at: float) -> None:
        """A mark for a moment already past, given as a `time.perf_counter()` reading."""
        self.marks.append(Mark(name=name, at_ms=(at - self.t0) * 1000))

    def to_json(self) -> str:
        # Names and durations only. Nothing the renter said reaches this line
        # (spec §3.2, §5.3).
        return json.dumps(
            {
                "turn_id": self.turn_id,
                "turn_type": self.turn_type,
                "cold_start": self.cold_start,
                "spans": [
                    {
                        "name": s.name,
                        "start_ms": round(s.start_ms, 1),
                        "end_ms": round(s.end_ms, 1),
                    }
                    for s in self.spans
                ],
                "marks": [{"name": m.name, "at_ms": round(m.at_ms, 1)} for m in self.marks],
            }
        )


_current: contextvars.ContextVar[Trace | None] = contextvars.ContextVar("trace", default=None)
_log_path: Path | None = None
# The first turn this process serves is the cold start (spec §5.2, §6.56): reported
# separately and never inside the p99s. Nothing set the flag before Task 4.1.
_cold = True


def configure(log_path: str | None) -> None:
    global _log_path
    _log_path = Path(log_path) if log_path else None


def current() -> Trace | None:
    return _current.get()


@contextmanager
def trace(turn_type: str, t0: float | None = None):
    """One turn. `t0` (a perf_counter reading) starts the clock earlier than now - at
    end-of-speech - so the final transcript and the ack, which precede the turn's task, can be
    placed on it with `mark_at`."""
    global _cold
    tr = Trace(turn_type=turn_type, cold_start=_cold)
    _cold = False
    if t0 is not None:
        tr.t0 = t0
    token = _current.set(tr)
    try:
        yield tr
    finally:
        _current.reset(token)
        if _log_path is not None:
            _log_path.parent.mkdir(parents=True, exist_ok=True)
            with _log_path.open("a", encoding="utf-8") as fh:
                fh.write(tr.to_json() + "\n")


@contextmanager
def span(name: str):
    tr = _current.get()
    if tr is None:
        # Timing outside a turn is not an error: the code under it still runs.
        yield
        return
    s = Span(name=name, start_ms=tr.now_ms())
    tr.spans.append(s)
    try:
        yield s
    finally:
        s.end_ms = tr.now_ms()


def mark(name: str) -> None:
    tr = _current.get()
    if tr is not None:
        tr.marks.append(Mark(name=name, at_ms=tr.now_ms()))
