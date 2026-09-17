"""Live provider pings. Skipped unless real keys are present (conventions: integration tests).

Run with a populated backend/.env:  python -m pytest backend/tests/integration -q
CI never runs these — its pytest target is backend/tests/unit.
"""

import asyncio
import json

import pytest

from scout.config import ENV_FILE, Settings

# Ask the same source the code under test asks. os.getenv() sees only the process
# environment, so with keys in backend/.env — where the conventions put them — these
# would skip forever while looking like they had run.
_S = Settings()
_MISSING = [
    name
    for name, value in (
        ("DEEPGRAM_API_KEY", _S.deepgram_api_key),
        ("GROQ_API_KEY", _S.groq_api_key),
        ("ANTHROPIC_API_KEY", _S.anthropic_api_key),
        ("SMALLEST_API_KEY", _S.smallest_api_key),
        ("SMALLEST_VOICE_ID", _S.smallest_voice_id),
    )
    if not value
]
pytestmark = pytest.mark.skipif(
    bool(_MISSING),
    reason=f"provider keys not set: {', '.join(_MISSING)} (looked in the environment and {ENV_FILE})",
)


SENTENCES_SCHEMA = {
    "type": "object",
    "properties": {"sentences": {"type": "array", "items": {"type": "string"}}},
    "required": ["sentences"],
    "additionalProperties": False,
}

ECHO_SCHEMA = {
    "type": "object",
    "properties": {"echo": {"type": "string"}},
    "required": ["echo"],
    "additionalProperties": False,
}


async def test_groq_returns_strict_json():
    from scout.providers.groq_job1 import GroqJob1Client

    out = await GroqJob1Client(Settings()).complete_json(
        "Echo as JSON.", "hello", "echo", ECHO_SCHEMA
    )
    assert set(out) == {"echo"}


async def test_anthropic_streams_json():
    from scout.providers.anthropic_job2 import AnthropicJob2Client

    buf = ""
    async for delta in AnthropicJob2Client(Settings()).stream_json(
        "Two sentences as JSON.", "Koramangala", SENTENCES_SCHEMA
    ):
        buf += delta
    assert '"sentences"' in buf


async def test_tts_yields_bytes():
    from scout.providers.smallest_tts import SmallestTts

    chunks = [c async for c in SmallestTts(Settings()).stream("Hello.")]
    assert chunks
    assert all(isinstance(c, bytes) for c in chunks)


# --- Google (Task 3.2's credentials, checked before Phase 3 is built on them) ------------------
#
# Read-only on purpose. The two writes that actually prove booking will work — inserting and
# deleting a calendar event, and sending one mail — were run by hand on 2026-09-09 and both
# passed; see the Task 3.2 status bullet in Docs/Implementation_Plan.md. They are deliberately
# NOT automated here: a test suite that books and emails on every run is a test suite nobody
# can run twice in a day.

_GOOGLE_MISSING = [
    name
    for name, value in (
        ("GOOGLE_OAUTH_CREDENTIALS", _S.google_oauth_credentials),
        ("GOOGLE_TENANT_CALENDAR_ID", _S.google_tenant_calendar_id),
        ("GOOGLE_OWNER_CALENDAR_ID", _S.google_owner_calendar_id),
    )
    if not value
]
google = pytest.mark.skipif(
    bool(_GOOGLE_MISSING), reason=f"Google config not set: {', '.join(_GOOGLE_MISSING)}"
)

REQUIRED_SCOPES = {
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.send",
}


async def _google_access_token(s: Settings) -> str:
    import httpx

    c = json.loads(s.google_oauth_credentials)
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": c["client_id"],
                "client_secret": c["client_secret"],
                "refresh_token": c["refresh_token"],
                "grant_type": "refresh_token",
            },
            timeout=20,
        )
    assert r.status_code == 200, f"refresh token rejected: {r.text[:200]}"
    return r.json()


@google
async def test_the_refresh_token_still_works_and_carries_both_scopes():
    tok = await _google_access_token(Settings())
    granted = set(tok.get("scope", "").split())
    # A missing gmail.send is invisible until the confirmation PDF fails to send, which is
    # the last step of a booking — exactly where a failure is most expensive (spec 6).
    assert REQUIRED_SCOPES <= granted, f"missing scopes: {REQUIRED_SCOPES - granted}"


@google
async def test_both_calendars_exist_are_writable_and_are_on_ist():
    import httpx

    s = Settings()
    tok = await _google_access_token(s)
    h = {"Authorization": f"Bearer {tok['access_token']}"}
    async with httpx.AsyncClient(headers=h, timeout=20) as client:
        for cal in (s.google_tenant_calendar_id, s.google_owner_calendar_id):
            meta = await client.get(f"https://www.googleapis.com/calendar/v3/calendars/{cal}")
            assert meta.status_code == 200, f"{cal}: {meta.text[:200]}"
            # Every slot this service offers is stated in IST (spec 2.4); a calendar in
            # another zone would silently shift every visit it writes.
            assert meta.json().get("timeZone") == "Asia/Kolkata"

            entry = await client.get(
                f"https://www.googleapis.com/calendar/v3/users/me/calendarList/{cal}"
            )
            assert entry.status_code == 200, f"{cal}: {entry.text[:200]}"
            assert entry.json().get("accessRole") in ("owner", "writer")


async def test_deepgram_opens_a_stream_with_the_production_keyterm_list():
    """The check that would have caught the first Phase 2 deploy: every locality as a keyterm
    made Deepgram refuse the socket (400) before a word was heard. Since 2026-09-17 the
    production list is the domain terms only (spec §5.1)."""
    from scout.providers.deepgram_stt import DeepgramStream, build_keyterms

    async def noop(*a, **k):
        pass

    st = DeepgramStream(
        _S,
        build_keyterms(),
        on_interim=noop,
        on_final=noop,
        on_speech_started=noop,
        on_utterance_end=noop,
    )
    await asyncio.wait_for(st.start(), 20)
    await st.close()
