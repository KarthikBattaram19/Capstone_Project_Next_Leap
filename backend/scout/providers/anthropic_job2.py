"""Job 2 — grounded explanation on Anthropic. No sampling params, no prefill, effort explicit (P7)."""

# Signature verified against anthropic 1.3.0 on 2026-09-05:
#   AsyncAnthropic(api_key=...).messages.stream(
#       *, max_tokens, messages, model, cache_control, inference_geo, metadata,
#       output_config, output_format, container, service_tier, stop_sequences, system,
#       thinking, tool_choice, tools, user_profile_id, ...
#   ) -> AsyncMessageStreamManager
# Note: `temperature`, `top_p` and `top_k` do not exist on this method at all, so the
# spec's "no sampling parameters" rule is enforced by the SDK, not just by us.
#   APIError(message, request, *, body) — request is positional; None is accepted.

from __future__ import annotations

from collections.abc import AsyncIterator

import anthropic
import httpx2  # anthropic 1.3.0's own transport (locked); its errors carry these types

from scout.config import Settings
from scout.platform import faults, telemetry

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


class AnthropicJob2Client:
    def __init__(self, settings: Settings) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=1)
        self._model = settings.job2_model
        self._effort = settings.job2_effort
        self._max_tokens = settings.job2_max_tokens

    async def stream_json(self, system: str, user: str, schema: dict) -> AsyncIterator[str]:
        if mode := faults.active("anthropic"):
            if mode == "schema_violation":
                # Structured output makes a malformed object unlikely except by truncation,
                # and a truncated stream raises nothing here: the parser simply never sees
                # a whole sentence. That is the real path, so it is the injected one.
                yield '{"sentences": [{"text": "fault injected: cut off mid-sen'
                return
            raise _injected(mode)
        first = True
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            thinking={"type": "adaptive"},
            output_config={
                "effort": self._effort,
                "format": {"type": "json_schema", "schema": schema},
            },
            messages=[{"role": "user", "content": user}],
        ) as stream:
            async for text in stream.text_stream:
                if first:
                    telemetry.mark(telemetry.LLM_FIRST_TOKEN)
                    first = False
                yield text
            final = await stream.get_final_message()
        telemetry.mark(telemetry.LLM_LAST_TOKEN)
        if final.stop_reason == "refusal":
            raise anthropic.APIError("job2 refusal", request=None, body=None)  # caller -> Failed

    async def aclose(self) -> None:
        # The SDK's pooled connection is closed on the loop that opened it. Left to the
        # garbage collector it closes on whatever loop is current — under pytest that loop
        # is already gone, and every eval run ended in "Event loop is closed" noise.
        await self._client.close()


def _injected(mode: str) -> Exception:
    """What the SDK raises when Anthropic really fails that way (Task 4.2 fault switch).

    Built offline: the request is never sent. Job2.explain turns any of these into Job2Down.
    """
    request = httpx2.Request("POST", ANTHROPIC_URL)
    if mode == "timeout":
        return anthropic.APITimeoutError(request=request)
    if mode == "429":
        return anthropic.RateLimitError(
            "fault injected: 429", response=httpx2.Response(429, request=request), body=None
        )
    return anthropic.APIConnectionError(message="fault injected: connection error", request=request)
