"""The harness itself: the settings gate fails rather than skips, and the driver is wired."""

from __future__ import annotations

import pytest

from evals.conftest import required_keys, resolve_settings

# Whatever Job 1 is configured to use, plus Anthropic for Job 2.
JOB1_ENV = next(k for k in required_keys() if k != "ANTHROPIC_API_KEY")
KEYS = {JOB1_ENV: "job1-test-key", "ANTHROPIC_API_KEY": "sk-ant-test"}


def test_missing_keys_fail_the_run_and_name_both_env_names(tmp_path):
    with pytest.raises(pytest.UsageError) as e:
        resolve_settings(str(tmp_path), {JOB1_ENV: "x"}, allow_skip=False)
    assert "ANTHROPIC_API_KEY" in str(e.value) and "ALLOW_EVAL_SKIP=1" in str(e.value)
    with pytest.raises(pytest.UsageError) as e:
        resolve_settings(str(tmp_path), {}, allow_skip=False)
    assert f"{JOB1_ENV}, ANTHROPIC_API_KEY" in str(e.value)


def test_missing_keys_skip_only_when_the_operator_asked(tmp_path):
    with pytest.raises(pytest.skip.Exception):
        resolve_settings(str(tmp_path), {}, allow_skip=True)


def test_present_keys_reach_the_settings_without_reading_env(tmp_path):
    s = resolve_settings(str(tmp_path), KEYS, allow_skip=False)
    job1_attr = required_keys()[JOB1_ENV]
    assert (getattr(s, job1_attr), s.anthropic_api_key) == ("job1-test-key", "sk-ant-test")
    assert s.bundle_dir == str(tmp_path) and s.origins == ["http://localhost:3000"]


# ---- preflight: a refused provider aborts the run before a case spends quota


def _settings(**kw):
    return resolve_settings("/tmp/bundle", KEYS, allow_skip=False).model_copy(update=kw)


async def _ok(settings):
    return None


def test_preflight_passes_when_every_ping_answers():
    from evals.harness.preflight import run_preflight

    run_preflight(_settings(), pings=[_ok, _ok])


def test_preflight_names_every_provider_that_refused():
    from evals.harness.preflight import PreflightError, run_preflight

    async def gemini_429(settings):
        raise PreflightError("gemini: HTTP 429 — spent")

    async def anthropic_401(settings):
        raise PreflightError("anthropic: HTTP 401 — API key is invalid.")

    with pytest.raises(PreflightError) as e:
        run_preflight(_settings(), pings=[gemini_429, _ok, anthropic_401])
    msg = str(e.value)
    assert "gemini: HTTP 429" in msg and "anthropic: HTTP 401" in msg


def test_preflight_pings_gemini_only_when_job1_runs_there():
    from evals.harness.preflight import default_pings, ping_anthropic, ping_gemini

    assert default_pings(_settings(job1_provider="gemini")) == [ping_gemini, ping_anthropic]
    assert default_pings(_settings(job1_provider="groq")) == [ping_anthropic]


async def test_the_gemini_ping_reports_a_status_and_never_the_key(monkeypatch):
    import httpx

    from evals.harness import preflight

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(403, text=f"denied for {request.url}")

    real = httpx.AsyncClient
    monkeypatch.setattr(
        preflight.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    s = _settings(gemini_api_key="AIza-secret-key")
    with pytest.raises(preflight.PreflightError) as e:
        await preflight.ping_gemini(s)
    assert "gemini: HTTP 403" in str(e.value)
    assert "AIza-secret-key" not in str(e.value)
    assert "key=AIza-secret-key" in seen["url"]  # the key went to Google, not the log
