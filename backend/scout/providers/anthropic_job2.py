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

from scout.config import Settings
from scout.platform import telemetry


class AnthropicJob2Client:
    def __init__(self, settings: Settings) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=1)
        self._model = settings.job2_model
        self._effort = settings.job2_effort
        self._max_tokens = settings.job2_max_tokens

    async def stream_json(self, system: str, user: str, schema: dict) -> AsyncIterator[str]:
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
