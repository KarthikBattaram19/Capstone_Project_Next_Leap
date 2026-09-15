"""Job 1 — fast structured extraction on Groq. temperature=0, strict JSON schema (spec §5.1)."""

# Signature verified against groq 1.7.0 on 2026-09-05, re-checked 2026-09-09:
#   AsyncGroq(api_key=...).chat.completions.create(
#       *, messages, model, ..., reasoning_effort, response_format, temperature, ...
#   ) -> ChatCompletion | AsyncStream[ChatCompletionChunk]
# All five parameters used below exist; reasoning_effort is
# Optional[Literal['none','default','low','medium','high']]. The installed model Literal
# includes "openai/gpt-oss-120b", which is Settings.job1_model, so the pinned id is accepted.

from __future__ import annotations

import json

import httpx
from groq import APIConnectionError, APITimeoutError, AsyncGroq, RateLimitError

from scout.config import Settings
from scout.platform import faults, telemetry

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# gpt-oss-120b is a reasoning model: it spends completion tokens thinking before it writes
# the JSON. Two ways of shortening that were measured on 2026-09-09:
#
#   max_completion_tokens=512  REJECTED. It caps the whole completion, reasoning included,
#                              so the reply was cut off mid-object and Groq rejected its own
#                              generation against the strict schema. Left uncapped.
#   reasoning_effort="low"     ADOPTED (Settings.job1_effort). Reasoning tokens fell from 268
#                              to 45-81 and the call from 1,147 to 886 tokens — a 23% cut —
#                              with 5/5 correct on the extractions that had previously failed
#                              (the property type in "2BHK apartment", the 1,75,000 deposit).
#                              Fewer generated tokens also means a faster turn, which is the
#                              L2 budget's direction of travel.
#
# Why not move Job 1 to Claude Haiku 4.5, which has no daily cap on the paid Anthropic plan:
# measured 3.73 s median against Groq's 1.50 s on the same machine. Job 1 must finish before
# the shortlist exists, so first audio would land near 4.2 s against an L2 target of 3.5 s.
# Groq's speed is the reason it was chosen (spec §5.1); latency won. See Docs/GATE_L.md.


class GroqJob1Client:
    def __init__(self, settings: Settings) -> None:
        # A 429 on the on-demand tier asks for a wait of a few hundred milliseconds; the SDK
        # honours Retry-After, so a handful of retries turns a transient rate limit into a
        # slower turn instead of "I didn't catch that". A schema violation is still retried
        # exactly once, by Job1 itself (spec §6.32) — this is the transport, not the schema.
        self._client = AsyncGroq(
            api_key=settings.groq_api_key, max_retries=4
        )  # keep-alive pool (P2)
        self._model = settings.job1_model
        self._effort = settings.job1_effort

    async def aclose(self) -> None:
        await self._client.close()

    async def complete_json(self, system: str, user: str, schema_name: str, schema: dict) -> dict:
        if mode := faults.active("groq"):
            raise _injected(mode)
        with telemetry.span("external.groq"):
            resp = await self._client.chat.completions.create(
                model=self._model,
                temperature=0,
                reasoning_effort=self._effort,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "strict": True, "schema": schema},
                },
            )
        return json.loads(resp.choices[0].message.content)


def _injected(mode: str) -> Exception:
    """What the SDK raises when Groq really fails that way (Task 4.2 fault switch).

    Built offline: the request is never sent. A schema violation is the JSONDecodeError
    json.loads raises above on malformed content, which Job1 retries once (§6.32).
    """
    request = httpx.Request("POST", GROQ_URL)
    if mode == "schema_violation":
        return json.JSONDecodeError("fault injected", "{", 1)
    if mode == "timeout":
        return APITimeoutError(request=request)
    if mode == "429":
        return RateLimitError(
            "fault injected: 429", response=httpx.Response(429, request=request), body=None
        )
    return APIConnectionError(message="fault injected: connection error", request=request)
