"""Live provider pings. Skipped unless real keys are present (conventions: integration tests).

Run with a populated backend/.env:  python -m pytest backend/tests/integration -q
CI never runs these — its pytest target is backend/tests/unit.
"""

import pytest

from scout.config import ENV_FILE, Settings

# Ask the same source the code under test asks. os.getenv() sees only the process
# environment, so with keys in backend/.env — where the conventions put them — these
# would skip forever while looking like they had run.
_S = Settings()
_MISSING = [
    name
    for name, value in (
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


async def test_groq_returns_strict_json():
    from scout.conversation.stub_turn import STUB_SCHEMA
    from scout.providers.groq_job1 import GroqJob1Client

    out = await GroqJob1Client(Settings()).complete_json(
        "Echo as JSON.", "hello", "echo", STUB_SCHEMA
    )
    assert set(out) == {"echo"}


async def test_anthropic_streams_json():
    from scout.conversation.stub_turn import STUB_J2_SCHEMA
    from scout.providers.anthropic_job2 import AnthropicJob2Client

    buf = ""
    async for delta in AnthropicJob2Client(Settings()).stream_json(
        "Two sentences as JSON.", "Koramangala", STUB_J2_SCHEMA
    ):
        buf += delta
    assert '"sentences"' in buf


async def test_tts_yields_bytes():
    from scout.providers.smallest_tts import SmallestTts

    chunks = [c async for c in SmallestTts(Settings()).stream("Hello.")]
    assert chunks
    assert all(isinstance(c, bytes) for c in chunks)
