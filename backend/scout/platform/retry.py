"""One retry with backoff when a provider says 429 (spec §6.54).

The scope is deliberately narrow: §6.54 is about quota and rate limits, not about outages.
A refused connection is §6.23 (speech), §6.11 (a model) or §6.53 (voice), and each of those
has its own renter-facing line — retrying them here would only delay the sentence the renter
actually needs to hear. So this retries a 429 and nothing else.

**Where the fault check goes.** Callers keep `faults.active(...)` INSIDE the retried block,
which makes a `429` fault behave exactly as Job 1's already does (see `faults.py`): `turns=1`
is recovered by the retry, `turns=2` is what makes the capability go down. A `down` or
`timeout` fault is not a 429, so it is never retried and every recipe already written for
those rows keeps its meaning.

**Why the wait is this short.** §6.54 requires the retry to fit inside the turn's budget, and
Gate L gives first spoken audio 3.5 s and a booking 5 s. One number here rather than four
spelled out across the wrappers, so the cost is visible in one place.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

RATE_LIMITED = 429

# Off the spoken turn's clock: Calendar and Gmail (a booking has 5 s) and opening the
# Deepgram stream (session open, before any turn). Half a second buys a real recovery.
RATE_LIMIT_BACKOFF_S = 0.5

# Inside the spoken turn: TTS is the only retried wrapper the renter waits on, and Gate L
# gives first spoken audio 3.5 s — 0.5 s there would spend 14% of the budget on one retry.
# 175 ms is chosen to be recoverable without being felt, and it is a number picked by
# judgement, not measurement: no rate-limited TTS turn has been timed.
TTS_RATE_LIMIT_BACKOFF_S = 0.175

__all__ = [
    "RATE_LIMITED",
    "RATE_LIMIT_BACKOFF_S",
    "TTS_RATE_LIMIT_BACKOFF_S",
    "retry_once_on_rate_limit",
]


async def retry_once_on_rate_limit[T](
    attempt: Callable[[], Awaitable[T]],
    is_rate_limited: Callable[[BaseException], bool],
    *,
    backoff_s: float = RATE_LIMIT_BACKOFF_S,
) -> T:
    """Run `attempt`; if it fails a rate limit, wait `backoff_s` and run it exactly once more.

    The second failure propagates unchanged, whatever it is — §6.54's "report exhaustion as
    itself" is the wrappers' existing behaviour and this must not disturb it. `attempt` is a
    callable rather than an awaitable because an awaitable cannot be awaited twice.
    """
    try:
        return await attempt()
    except Exception as e:
        if not is_rate_limited(e):
            raise
    await asyncio.sleep(backoff_s)
    return await attempt()
