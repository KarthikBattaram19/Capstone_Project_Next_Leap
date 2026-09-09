"""Job 1 — fast structured extraction on Groq. temperature=0, strict JSON schema (spec §5.1)."""

# Signature verified against groq 1.7.0 on 2026-09-05:
#   AsyncGroq(api_key=...).chat.completions.create(
#       *, messages, model, ..., response_format, temperature, ...
#   ) -> ChatCompletion | AsyncStream[ChatCompletionChunk]
# All four parameters used below exist. The installed model Literal includes
# "openai/gpt-oss-120b", which is Settings.job1_model, so the pinned id is accepted.

from __future__ import annotations

import json

from groq import AsyncGroq

from scout.config import Settings
from scout.platform import telemetry

# gpt-oss-120b is a reasoning model: it spends completion tokens thinking before it writes
# the JSON. Capping max_completion_tokens at 512 to shrink the rate-limit reservation cut
# the reply off mid-object and Groq rejected its own generation against the strict schema
# (measured 2026-09-09). The completion is left uncapped for that reason.


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

    async def complete_json(self, system: str, user: str, schema_name: str, schema: dict) -> dict:
        with telemetry.span("external.groq"):
            resp = await self._client.chat.completions.create(
                model=self._model,
                temperature=0,
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
