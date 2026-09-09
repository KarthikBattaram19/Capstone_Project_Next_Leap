"""Job 1 asks Groq for low reasoning effort, and that is not an accident.

gpt-oss-120b spends completion tokens deliberating before it writes the JSON. At the
default effort one call costs 1,147 tokens; at "low" it costs 886 with no measured loss of
accuracy (2026-09-09). That 23% is what makes a 60-case eval run fit inside the account's
daily allowance, so a silent revert would put the suites back over the wall.
"""

import pytest

from scout.config import Settings
from scout.providers.groq_job1 import GroqJob1Client


class _FakeMessage:
    content = '{"ok": true}'


class _FakeChoice:
    message = _FakeMessage()


class _FakeCompletion:
    choices = (_FakeChoice(),)


def test_the_default_effort_is_low():
    assert Settings(_env_file=None).job1_effort == "low"


async def test_the_effort_reaches_the_provider(monkeypatch):
    seen = {}

    async def fake_create(**kwargs):
        seen.update(kwargs)
        return _FakeCompletion()

    client = GroqJob1Client(Settings(_env_file=None))
    monkeypatch.setattr(client._client.chat.completions, "create", fake_create)

    await client.complete_json("sys", "user", "job1", {"type": "object"})

    assert seen["reasoning_effort"] == "low"
    assert seen["temperature"] == 0
    assert seen["response_format"]["json_schema"]["strict"] is True


async def test_the_effort_is_configurable_not_hardcoded(monkeypatch):
    seen = {}

    async def fake_create(**kwargs):
        seen.update(kwargs)
        return _FakeCompletion()

    client = GroqJob1Client(Settings(_env_file=None, job1_effort="high"))
    monkeypatch.setattr(client._client.chat.completions, "create", fake_create)

    await client.complete_json("sys", "user", "job1", {"type": "object"})
    assert seen["reasoning_effort"] == "high"


@pytest.mark.parametrize("effort", ["none", "default", "low", "medium", "high"])
def test_every_configured_effort_is_one_the_sdk_accepts(effort):
    # The SDK types this as Literal['none','default','low','medium','high']; a typo in
    # .env would otherwise only surface as a 400 mid-conversation.
    import inspect

    from groq.resources.chat.completions import AsyncCompletions

    annotation = str(inspect.signature(AsyncCompletions.create).parameters["reasoning_effort"])
    assert f"'{effort}'" in annotation
