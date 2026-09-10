"""Job 1 on Gemini — the same contract as the Groq client: strict JSON in, dict out.

Shape verified by running it against generativelanguage.googleapis.com on 2026-09-10, not
copied from a doc page: the published "structured output" page describes a newer
input/response_format surface, while the `:generateContent` endpoint these model ids serve
takes systemInstruction / contents / generationConfig. What is below is what answered 200.

Deliberately raw HTTP rather than the google-genai SDK. That SDK declares
`websockets<17.0` for its Live API, and this project pins `websockets==17.1` for the
Deepgram stream (Task 0.8); installing it downgraded websockets and broke the pin. Nothing
here needs the SDK — httpx is already a dependency, and one endpoint is the whole surface.
"""

from __future__ import annotations

import asyncio
import json
import random
from typing import ClassVar

import httpx

from scout.config import Settings
from scout.platform import telemetry

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
RETRIES = 4
RETRYABLE = frozenset({408, 429, 500, 502, 503, 504})


class GeminiError(RuntimeError):
    """A Gemini failure with the API key stripped out of it.

    This endpoint takes the key as a QUERY PARAMETER, and httpx puts the full request URL
    into HTTPStatusError's message. Job 1 logs the provider's reason to stderr, so the
    default exception would print the secret into the logs on every 429 — which is exactly
    what happened on 2026-09-10 before this existed. Never raise the httpx error as-is.
    """


def _redact(resp: httpx.Response) -> str:
    """Status plus the provider's own message. No URL, so no key."""
    detail = ""
    try:
        detail = str(resp.json().get("error", {}).get("message", ""))[:200]
    except (ValueError, AttributeError):
        detail = resp.text[:200]
    return f"{resp.status_code} from Gemini: {detail}".strip()


def _retry_after(resp: httpx.Response, attempt: int) -> float:
    """How long the provider says to wait.

    Gemini puts it in the BODY as a RetryInfo detail ("retryDelay": "48s"), not in a
    Retry-After header. Backing off on a header that is never sent meant waiting 16 s when
    the API had asked for 48 and burning the retry budget on requests that could not
    succeed — and a 429 still costs a request against the quota.
    """
    header = resp.headers.get("retry-after")
    if header:
        try:
            return min(float(header), 60.0)
        except ValueError:
            pass
    try:
        for detail in resp.json().get("error", {}).get("details", []):
            delay = detail.get("retryDelay")
            if delay and delay.endswith("s"):
                return min(float(delay[:-1]) + 1.0, 60.0)
    except (ValueError, AttributeError, TypeError):
        pass
    return min(2.0**attempt, 16.0) + random.uniform(0, 0.5)


class _Pacer:
    """Keeps requests under a per-minute cap instead of discovering it with a 429.

    The free tier allows 15 requests per minute per model, and a rejected request still
    counts against that, so retrying into the limit makes it worse. Spacing calls costs the
    same wall-clock and wastes no quota. Set job1_gemini_rpm to 0 on a paid tier, where the
    cap is high enough that pacing only adds latency.

    Shared per (model, rpm), not per client: the quota belongs to the PROJECT, so a pacer
    living on the client instance resets every time something builds a new one. The eval
    driver builds one per turn batch, which let the real rate run well over the cap and then
    stall in 48-second retry backoffs — a suite that had been passing hung for ten minutes
    on its seventh case (2026-09-10).
    """

    _shared: ClassVar[dict[tuple[str, int], _Pacer]] = {}

    @classmethod
    def shared(cls, model: str, rpm: int) -> _Pacer:
        key = (model, rpm)
        if key not in cls._shared:
            cls._shared[key] = cls(rpm)
        return cls._shared[key]

    def __init__(self, rpm: int) -> None:
        self._interval = 60.0 / rpm if rpm > 0 else 0.0
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._next_at = 0.0

    async def wait(self) -> None:
        if not self._interval:
            return
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            # A fresh event loop (every pytest test gets one) needs its own lock: an
            # asyncio.Lock binds to the loop it was first awaited on.
            self._loop, self._lock = loop, asyncio.Lock()
        async with self._lock:
            now = loop.time()
            sleep_for = max(0.0, self._next_at - now)
            self._next_at = max(now, self._next_at) + self._interval
        if sleep_for:
            await asyncio.sleep(sleep_for)


class GeminiJob1Client:
    """Job 1 — fast structured extraction on Gemini. temperature=0, strict JSON schema."""

    def __init__(self, settings: Settings) -> None:
        self._model = settings.job1_gemini_model
        self._thinking = settings.job1_gemini_thinking
        self._key = settings.gemini_api_key
        self._pacer = _Pacer.shared(self._model, settings.job1_gemini_rpm)
        # Built on first use, not here: constructing one costs real time, and something
        # builds a client per request batch (the eval driver) or per app (create_app) long
        # before any call is made. Once built it is kept open — P2 wants connection reuse,
        # and a fresh TLS handshake per turn measured ~0.45 s on top of a ~1.0 s call.
        self._http: httpx.AsyncClient | None = None

    async def complete_json(self, system: str, user: str, schema_name: str, schema: dict) -> dict:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                # responseJsonSchema, not responseSchema: the former takes real JSON Schema,
                # including the ["string", "null"] unions JOB1_SCHEMA uses for its nullable
                # fields. Verified accepted 2026-09-10.
                "responseJsonSchema": schema,
                "thinkingConfig": {"thinkingLevel": self._thinking},
            },
        }
        resp = await self._post_with_retries(body)
        payload = resp.json()
        candidate = payload["candidates"][0]
        # A blocked or truncated candidate has no parts. Let the KeyError/IndexError surface:
        # Job1 retries once and then declares understanding down, which is the honest answer.
        text = candidate["content"]["parts"][0]["text"]
        return _loads(text, schema_name)

    def _session(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=5.0),
                limits=httpx.Limits(max_keepalive_connections=4, keepalive_expiry=300.0),
            )
        return self._http

    async def _post_with_retries(self, body: dict) -> httpx.Response:
        """POST, retrying a rate limit the way the Groq client does (max_retries=4).

        A 429 on the free tier is a per-minute pace limit, so a short backoff turns it into
        a slower turn rather than "I didn't catch that".
        """
        url = f"{BASE_URL}/{self._model}:generateContent"
        last: Exception | None = None
        timeouts = 0
        for attempt in range(RETRIES + 1):
            await self._pacer.wait()
            with telemetry.span("external.gemini"):
                try:
                    resp = await self._session().post(url, params={"key": self._key}, json=body)
                except httpx.TimeoutException as e:
                    # One retry on a timeout, no more: the free tier occasionally sits on a
                    # request past the 30 s read timeout (an eval case lost this way on
                    # 2026-09-10), and a second wait would be a minute the renter does not
                    # have. Type only — httpx's message carries the URL, and the URL the key.
                    timeouts += 1
                    if timeouts > 1 or attempt == RETRIES:
                        raise GeminiError(f"{type(e).__name__} from Gemini") from None
                    continue
            if resp.status_code < 400:
                return resp
            if resp.status_code not in RETRYABLE or attempt == RETRIES:
                raise GeminiError(_redact(resp))
            last = GeminiError(_redact(resp))
            await asyncio.sleep(_retry_after(resp, attempt))
        raise last  # unreachable; kept so the type is honest

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None


def _loads(text: str, schema_name: str) -> dict:
    data = json.loads(text)
    if isinstance(data, dict):
        return data
    # A list or scalar where an object was asked for is a schema violation, and Job1's
    # retry-once path is exactly what should handle it (spec §6.32).
    raise ValueError(f"{schema_name}: expected an object, got {type(data).__name__}")
