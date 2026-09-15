"""An injected fault raises the wrapper's REAL error class, and nothing leaves the process.

The §6 walkthrough (Task 4.2) is only evidence if a fault travels the path a real outage
takes, so each test pins the class the caller's existing handler already catches: Job1's
retry-then-Job1Down, Job2Down, Speaker's tts_failed, LiveSession's reconnect, the
calendar's 503 handler, the mail sender's "failed". Every provider's network entry point is
replaced with something that fails the test if it is reached.
"""

import json
from types import SimpleNamespace

import anthropic
import groq
import httpx
import pytest
from deepgram.core.api_error import ApiError as DeepgramApiError
from smallestai.core.api_error import ApiError as SmallestApiError
from websockets.exceptions import ConnectionClosedError

from scout.config import Settings
from scout.conversation.job1 import Job1, Job1Down
from scout.conversation.job2 import Job2, Job2Down
from scout.conversation.speaker import Speaker
from scout.domain.constraints import ConstraintSet
from scout.platform import faults
from scout.providers.anthropic_job2 import AnthropicJob2Client
from scout.providers.deepgram_stt import DeepgramStream
from scout.providers.gemini_job1 import GeminiError, GeminiJob1Client
from scout.providers.gmail import GmailAdapter, MailError
from scout.providers.google_calendar import (
    CalendarAuthError,
    CalendarError,
    GoogleCalendarAdapter,
)
from scout.providers.groq_job1 import GroqJob1Client
from scout.providers.smallest_tts import SmallestTts

REACHED: list[str] = []


@pytest.fixture(autouse=True)
def switch():
    REACHED.clear()
    faults.configure(True)
    yield faults
    faults.configure(False)
    # Recorded, not just raised: the calendar and mail adapters wrap ANY exception in their
    # own error class, so a raise alone would let a missing fault check pass these tests.
    assert REACHED == [], "a faulted call reached the provider"


def _unreachable(*_a, **_kw):
    REACHED.append("provider")
    raise AssertionError("a faulted call reached the provider")


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, job1_gemini_rpm=0, **kw)


# ---- Gemini (Job 1)


def _gemini(monkeypatch) -> GeminiJob1Client:
    c = GeminiJob1Client(_settings(gemini_api_key="k-test"))
    monkeypatch.setattr(c, "_build_session", _unreachable)
    return c


@pytest.mark.parametrize(
    ("mode", "error", "text"),
    [
        ("down", GeminiError, "503 from Gemini"),
        ("429", GeminiError, "429 from Gemini"),
        ("timeout", GeminiError, "ReadTimeout from Gemini"),
        ("schema_violation", ValueError, "expected an object"),
    ],
)
async def test_gemini_fault_raises_the_clients_own_error(monkeypatch, mode, error, text):
    faults.set_fault("gemini", mode, 1)
    with pytest.raises(error, match=text):
        await _gemini(monkeypatch).complete_json("s", "u", "job1", {"type": "object"})


async def test_a_schema_violation_twice_is_understanding_down_not_a_partial_parse(monkeypatch):
    # One turn is one call: Job1 retries a schema violation once (§6.32), so it takes two.
    faults.set_fault("gemini", "schema_violation", 2)
    with pytest.raises(Job1Down, match="schema violation twice"):
        await Job1(_gemini(monkeypatch), ["Koramangala"]).extract("2bhk", ConstraintSet())
    assert faults.active("gemini") is None


# ---- Groq (Job 1 fallback)


@pytest.mark.parametrize(
    ("mode", "error"),
    [
        ("down", groq.APIConnectionError),
        ("429", groq.RateLimitError),
        ("timeout", groq.APITimeoutError),
        ("schema_violation", json.JSONDecodeError),
    ],
)
async def test_groq_fault_raises_the_sdks_error(monkeypatch, mode, error):
    c = GroqJob1Client(_settings())
    monkeypatch.setattr(c._client.chat.completions, "create", _unreachable)
    faults.set_fault("groq", mode, 1)
    with pytest.raises(error):
        await c.complete_json("s", "u", "job1", {"type": "object"})


async def test_groq_429_carries_the_status(monkeypatch):
    c = GroqJob1Client(_settings())
    monkeypatch.setattr(c._client.chat.completions, "create", _unreachable)
    faults.set_fault("groq", "429", 1)
    with pytest.raises(groq.RateLimitError) as e:
        await c.complete_json("s", "u", "job1", {})
    assert e.value.status_code == 429


# ---- Anthropic (Job 2)


def _anthropic(monkeypatch) -> AnthropicJob2Client:
    c = AnthropicJob2Client(_settings())
    monkeypatch.setattr(c._client.messages, "stream", _unreachable)
    return c


@pytest.mark.parametrize(
    ("mode", "error"),
    [
        ("down", anthropic.APIConnectionError),
        ("429", anthropic.RateLimitError),
        ("timeout", anthropic.APITimeoutError),
    ],
)
async def test_anthropic_fault_raises_the_sdks_error(monkeypatch, mode, error):
    faults.set_fault("anthropic", mode, 1)
    with pytest.raises(error):
        async for _ in _anthropic(monkeypatch).stream_json("s", "u", {}):
            pass


async def test_anthropic_down_reaches_lane_b_as_job2_down(monkeypatch):
    faults.set_fault("anthropic", "down", 1)
    bundle = SimpleNamespace(listing_id="kor-001", locality="Koramangala", facts={}, chunks=[])
    with pytest.raises(Job2Down):
        async for _ in Job2(_anthropic(monkeypatch)).explain(bundle, "why this one?"):
            pass


async def test_anthropic_schema_violation_is_a_truncated_stream_with_no_whole_sentence(
    monkeypatch,
):
    faults.set_fault("anthropic", "schema_violation", 1)
    bundle = SimpleNamespace(listing_id="kor-001", locality="Koramangala", facts={}, chunks=[])
    said = [s async for s in Job2(_anthropic(monkeypatch)).explain(bundle, "why?")]
    assert said == []


# ---- Smallest (TTS)


@pytest.mark.parametrize(
    ("mode", "error"),
    [("down", SmallestApiError), ("429", SmallestApiError), ("timeout", httpx.ReadTimeout)],
)
async def test_smallest_fault_raises_the_sdks_error(monkeypatch, mode, error):
    tts = SmallestTts(_settings())
    monkeypatch.setattr(tts._client.waves, "synthesize_tts", _unreachable)
    faults.set_fault("smallest", mode, 1)
    with pytest.raises(error):
        async for _ in tts.stream("hello"):
            pass


async def test_smallest_down_is_tts_failed_and_the_answer_still_stands(monkeypatch):
    tts = SmallestTts(_settings())
    monkeypatch.setattr(tts._client.waves, "synthesize_tts", _unreachable)
    faults.set_fault("smallest", "down", 1)

    class Sink:
        async def audio_start(self):
            raise AssertionError("no audio should start")

        async def audio_end(self):
            pass

    assert (await Speaker(tts, Sink()).speak(["Hello."])).tts_failed


# ---- Deepgram (STT)


def _deepgram(monkeypatch) -> DeepgramStream:
    async def noop(*_):
        pass

    st = DeepgramStream(
        _settings(),
        keyterms=[],
        on_interim=noop,
        on_final=noop,
        on_speech_started=noop,
        on_utterance_end=noop,
    )
    monkeypatch.setattr(st._client.listen.v1, "connect", _unreachable)
    return st


@pytest.mark.parametrize(
    ("mode", "error", "status"),
    [
        ("down", DeepgramApiError, 503),
        ("429", DeepgramApiError, 429),
        ("timeout", TimeoutError, None),
    ],
)
async def test_deepgram_fault_on_connect_raises_the_sdks_error(monkeypatch, mode, error, status):
    faults.set_fault("deepgram", mode, 1)
    with pytest.raises(error) as e:
        await _deepgram(monkeypatch).start()
    if status is not None:
        assert e.value.status_code == status


async def test_deepgram_fault_mid_stream_is_a_closed_socket(monkeypatch):
    st = _deepgram(monkeypatch)
    st._conn = SimpleNamespace(send_media=_unreachable)
    faults.set_fault("deepgram", "down", 1)
    with pytest.raises(ConnectionClosedError):
        await st.send_audio(b"\x00\x00")


# ---- Google Calendar


def _calendar() -> GoogleCalendarAdapter:
    service = SimpleNamespace(freebusy=_unreachable, events=_unreachable)
    return GoogleCalendarAdapter.with_service(service, "T", "O")


@pytest.mark.parametrize(
    ("mode", "error", "status"),
    [
        ("down", CalendarError, 503),
        ("429", CalendarError, 429),
        ("timeout", CalendarError, None),
        ("auth", CalendarAuthError, 401),
    ],
)
async def test_calendar_fault_raises_the_adapters_error(mode, error, status):
    faults.set_fault("calendar", mode, 1)
    with pytest.raises(error) as e:
        await _calendar().find_by_code("ABC123")
    assert type(e.value) is error and e.value.status == status


async def test_a_calendar_timeout_is_not_mistaken_for_an_auth_failure():
    faults.set_fault("calendar", "timeout", 1)
    with pytest.raises(CalendarError) as e:
        await _calendar().delete("T", "evt1")  # delete swallows only 404/410
    assert not isinstance(e.value, CalendarAuthError)


# ---- Gmail


@pytest.mark.parametrize("mode", ["down", "429", "timeout", "auth"])
async def test_gmail_fault_raises_mail_error(mode):
    gmail = GmailAdapter.with_service(SimpleNamespace(users=_unreachable), "from@x")
    faults.set_fault("gmail", mode, 1)
    with pytest.raises(MailError):
        await gmail.send_pdf("to@x", "subject", "body", b"%PDF", "visit.pdf")


# ---- no fault, no interference


async def test_a_fault_on_one_provider_leaves_the_others_untouched(monkeypatch):
    faults.set_fault("anthropic", "down", 1)
    seen = []

    async def fake_create(**kwargs):
        seen.append(kwargs["model"])
        return SimpleNamespace(
            choices=(SimpleNamespace(message=SimpleNamespace(content='{"ok": true}')),)
        )

    c = GroqJob1Client(_settings())
    monkeypatch.setattr(c._client.chat.completions, "create", fake_create)
    assert await c.complete_json("s", "u", "job1", {}) == {"ok": True}  # a fake, not Groq
    assert seen and faults.active("anthropic") == "down"
