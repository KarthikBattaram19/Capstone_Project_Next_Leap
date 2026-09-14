"""One cheap call per provider before a pass spends its quota.

A pass is 146 Job 1 calls against a 500-a-day Gemini allowance (Docs/JOB2_SCORES.md). On
2026-09-14 a full pass ran on an Anthropic key that had already been revoked: Suites A and
B passed, every Suite C case degraded, and the run cost a third of the day for nothing.
Two requests here — one to each provider, a few tokens each — abort that run before it
starts, and name the provider and the HTTP status that refused.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx
from scout.config import Settings

Ping = Callable[[Settings], Awaitable[None]]


class PreflightError(RuntimeError):
    """A provider refused its ping. The message carries provider, status and reason only."""


def _redact(text: str, secret: str) -> str:
    return text.replace(secret, "<key>") if secret else text


async def ping_anthropic(settings: Settings) -> None:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=0)
    try:
        await client.messages.create(
            model=settings.job2_model,
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
    except anthropic.APIStatusError as e:
        raise PreflightError(f"anthropic: HTTP {e.status_code} — {e.message}") from None
    except anthropic.APIConnectionError as e:
        raise PreflightError(f"anthropic: no connection — {type(e).__name__}") from None
    finally:
        await client.close()


async def ping_gemini(settings: Settings) -> None:
    from scout.providers.gemini_job1 import BASE_URL

    key = settings.gemini_api_key
    url = f"{BASE_URL}/{settings.job1_gemini_model}:generateContent"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as http:
            resp = await http.post(
                url,
                params={"key": key},
                json={"contents": [{"parts": [{"text": "Reply with the single word OK."}]}]},
            )
    except httpx.HTTPError as e:
        # httpx embeds the URL, and the URL carries the key as a query parameter.
        raise PreflightError(f"gemini: no connection — {type(e).__name__}") from None
    if resp.status_code == 429:
        raise PreflightError(
            "gemini: HTTP 429 — the per-minute or per-day quota is already spent; a pass "
            "started now stalls in backoffs and fails cases that are quota, not code"
        )
    if resp.status_code != 200:
        raise PreflightError(f"gemini: HTTP {resp.status_code} — {_redact(resp.text[:200], key)}")


def default_pings(settings: Settings) -> list[Ping]:
    pings: list[Ping] = [ping_anthropic]
    if settings.job1_provider == "gemini":
        pings.insert(0, ping_gemini)
    return pings


def run_preflight(settings: Settings, pings: list[Ping] | None = None) -> None:
    """Run every ping; raise one PreflightError naming every provider that refused."""

    async def _all() -> list[str]:
        failures: list[str] = []
        for ping in pings if pings is not None else default_pings(settings):
            try:
                await ping(settings)
            except PreflightError as e:
                failures.append(str(e))
        return failures

    failures = asyncio.run(_all())
    if failures:
        raise PreflightError("; ".join(failures))
