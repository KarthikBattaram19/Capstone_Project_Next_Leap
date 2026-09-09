"""The Gemini Job 1 client sends what the endpoint actually accepts, and hides nothing.

The request shape was verified against generativelanguage.googleapis.com on 2026-09-10 (the
published structured-output page describes a different, newer surface). These tests pin the
shape so a refactor cannot quietly change it back to something that only looks right.
"""

import asyncio
import json

import httpx
import pytest

from scout.config import Settings
from scout.providers import make_job1_client
from scout.providers.gemini_job1 import GeminiError, GeminiJob1Client
from scout.providers.groq_job1 import GroqJob1Client

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["intent", "email"],
    "properties": {
        "intent": {"type": "string", "enum": ["a", "b"]},
        "email": {"type": ["string", "null"]},
    },
}


def _client(monkeypatch, handler) -> GeminiJob1Client:
    # rpm=0 turns the pacer off: these tests exercise the request shape against a mock
    # transport, and real pacing would make each one sleep four seconds. The pacer has its
    # own test below.
    c = GeminiJob1Client(Settings(_env_file=None, gemini_api_key="k-test", job1_gemini_rpm=0))
    monkeypatch.setattr(c, "_http", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return c


def _reply(payload: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]},
    )


async def test_it_sends_the_shape_the_endpoint_accepts(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return _reply({"intent": "a", "email": None})

    out = await _client(monkeypatch, handler).complete_json("SYS", "USER", "job1", SCHEMA)

    assert out == {"intent": "a", "email": None}
    assert "gemini-3.5-flash-lite:generateContent" in seen["url"]
    assert "key=k-test" in seen["url"]
    body = seen["body"]
    assert body["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert body["contents"][0]["parts"][0]["text"] == "USER"
    cfg = body["generationConfig"]
    assert cfg["temperature"] == 0
    assert cfg["responseMimeType"] == "application/json"
    # responseJsonSchema, not responseSchema: only the former takes the ["string","null"]
    # unions JOB1_SCHEMA uses for every nullable field.
    assert cfg["responseJsonSchema"] == SCHEMA
    assert "responseSchema" not in cfg
    assert cfg["thinkingConfig"]["thinkingLevel"] == "MINIMAL"


async def test_a_rate_limit_is_retried_then_reaches_the_caller(monkeypatch):
    # Job1 turns the final failure into Job1Down -> Failed(capability="understanding").
    # Swallowing it here would surface a 429 as a renter-facing "nothing found" (spec §6).
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(
            429, json={"error": {"message": "quota"}}, headers={"retry-after": "0"}
        )

    with pytest.raises(GeminiError, match="429"):
        await _client(monkeypatch, handler).complete_json("s", "u", "job1", SCHEMA)
    assert len(calls) == 5, "a rate limit should be retried, not given up on immediately"


async def test_a_transient_rate_limit_recovers(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(
                429, json={"error": {"message": "slow down"}}, headers={"retry-after": "0"}
            )
        return _reply({"intent": "a", "email": None})

    out = await _client(monkeypatch, handler).complete_json("s", "u", "job1", SCHEMA)
    assert out == {"intent": "a", "email": None}
    assert len(calls) == 2


async def test_a_failure_never_carries_the_api_key(monkeypatch):
    """This endpoint takes the key as a QUERY PARAMETER.

    httpx's own HTTPStatusError message embeds the full request URL, and Job 1 prints the
    provider's reason to stderr — so raising it unchanged printed the live key into the
    terminal on every 429 (observed 2026-09-10). The error must never carry it.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "denied"}})

    c = GeminiJob1Client(
        Settings(_env_file=None, gemini_api_key="SUPERSECRET-do-not-log", job1_gemini_rpm=0)
    )
    c._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(GeminiError) as e:
        await c.complete_json("s", "u", "job1", SCHEMA)
    message = str(e.value)
    assert "SUPERSECRET" not in message
    assert "key=" not in message
    assert "403" in message and "denied" in message


async def test_a_blocked_candidate_raises_rather_than_returning_half_an_answer(monkeypatch):
    # A safety-blocked or truncated candidate carries no parts. Job1 retries once and then
    # declares understanding down — better than parsing a shape that is not there.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": [{"finishReason": "SAFETY"}]})

    with pytest.raises((KeyError, IndexError)):
        await _client(monkeypatch, handler).complete_json("s", "u", "job1", SCHEMA)


async def test_a_non_object_reply_is_refused(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "[1, 2]"}]}}]}
        )

    with pytest.raises(ValueError, match="expected an object"):
        await _client(monkeypatch, handler).complete_json("s", "u", "job1", SCHEMA)


def test_the_factory_follows_the_configured_provider():
    gem = Settings(_env_file=None, job1_provider="gemini", gemini_api_key="k")
    groq = Settings(_env_file=None, job1_provider="groq", groq_api_key="k")
    assert isinstance(make_job1_client(gem), GeminiJob1Client)
    assert isinstance(make_job1_client(groq), GroqJob1Client)


def test_an_unknown_provider_is_refused_by_name():
    with pytest.raises(ValueError, match="openai"):
        make_job1_client(Settings(_env_file=None, job1_provider="openai"))


async def test_the_pacer_spaces_calls_under_the_per_minute_cap():
    # The free tier allows 15 requests a minute per model and a REJECTED request still
    # counts against it, so retrying into the limit makes it worse. 60 rpm = 1s apart.
    from scout.providers.gemini_job1 import _Pacer

    pacer = _Pacer(60)
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    for _ in range(3):
        await pacer.wait()
    assert loop.time() - t0 >= 2.0, "three calls at 60 rpm must span at least two seconds"


async def test_the_pacer_is_off_when_rpm_is_zero():
    from scout.providers.gemini_job1 import _Pacer

    pacer = _Pacer(0)
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    for _ in range(5):
        await pacer.wait()
    assert loop.time() - t0 < 0.1


def test_the_retry_delay_is_read_from_the_body_not_a_header():
    # Gemini sends RetryInfo in the body ("retryDelay": "48s"); there is no Retry-After
    # header. Backing off on the header alone waited 16s when the API asked for 48.
    from scout.providers.gemini_job1 import _retry_after

    resp = httpx.Response(
        429,
        json={
            "error": {
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "48s"}
                ]
            }
        },
    )
    assert 48.0 <= _retry_after(resp, attempt=0) <= 60.0


def test_the_default_provider_is_gemini():
    s = Settings(_env_file=None)
    assert s.job1_provider == "gemini"
    assert s.job1_gemini_model == "gemini-3.5-flash-lite"
    assert s.job1_gemini_thinking == "MINIMAL"
