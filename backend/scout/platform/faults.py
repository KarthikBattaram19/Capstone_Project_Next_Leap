"""Fault injection for the §6 walkthrough (Task 4.2). Off unless FAULT_INJECTION=1.

Rows 6.23, 6.46 and 6.54 need a real outage, which cannot be ordered on demand. A fault
makes one provider wrapper raise, at the top of its call, the error that wrapper already
raises when the provider really fails that way — so what gets exercised is the
orchestrator's own failure handling, not a path built for the demo. Nothing here reaches a
provider.

Two locks on the door: the route that sets a fault is registered only when
FAULT_INJECTION=1 (scout/main.py), and it answers only to the operator token
(scout/api/http.py). With the switch off, `active` returns None for every provider even if
something calls `set_fault` directly — it refuses.

A "turn" is one call to that provider's wrapper, because that is the only unit a wrapper
can see. Job 1 retries a schema violation once (spec §6.32), so `turns=1` is recovered by
the retry and `turns=2` is what makes understanding go down. The calendar is called five
times per booking (freebusy, a code lookup on each calendar, two inserts), so a calendar
fault fails the free-slot read first; the background repair loop's retries spend turns too.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scout.config import Settings

Provider = Literal["deepgram", "gemini", "groq", "anthropic", "smallest", "calendar", "gmail"]
Mode = Literal["down", "429", "timeout", "schema_violation", "auth"]

_TRANSPORT = frozenset({"down", "429", "timeout"})

# What each provider can really do wrong. Speech and mail have no schema to violate, and
# only Google's OAuth grant can be revoked mid-session (spec §6.46). A fault a provider
# cannot have would exercise a failure path that does not exist.
MODES: dict[str, frozenset[str]] = {
    "deepgram": _TRANSPORT,
    "gemini": _TRANSPORT | {"schema_violation"},
    "groq": _TRANSPORT | {"schema_violation"},
    "anthropic": _TRANSPORT | {"schema_violation"},
    "smallest": _TRANSPORT,
    "calendar": _TRANSPORT | {"auth"},
    "gmail": _TRANSPORT | {"auth"},
}


class FaultRequest(BaseModel):
    """POST /admin/fault. Operator-only, so it is not part of the frontend contract."""

    model_config = ConfigDict(extra="forbid")

    provider: Provider
    mode: Mode
    turns: int = Field(ge=0, le=1000)  # 0 clears the provider's fault


_enabled = False
_faults: dict[str, tuple[str, int]] = {}  # provider -> (mode, calls left)


def enabled_by(settings: Settings) -> bool:
    return settings.fault_injection == "1"


def configure(enabled: bool) -> None:
    """Called once by create_app. Always clears, so a new app never inherits a fault."""
    global _enabled
    _enabled = enabled
    _faults.clear()


def set_fault(provider: str, mode: str, turns: int) -> None:
    if not _enabled:
        raise RuntimeError("fault injection is off (FAULT_INJECTION is not 1)")
    if mode not in MODES[provider]:
        raise ValueError(f"{provider} has no {mode!r} failure; it can be {sorted(MODES[provider])}")
    if turns == 0:
        _faults.pop(provider, None)
    else:
        _faults[provider] = (mode, turns)


def active(provider: str) -> str | None:
    """The fault this call must raise, consuming one turn of it; None almost always."""
    if not _enabled:
        return None
    entry = _faults.get(provider)
    if entry is None:
        return None
    mode, left = entry
    if left <= 1:
        del _faults[provider]
    else:
        _faults[provider] = (mode, left - 1)
    return mode
