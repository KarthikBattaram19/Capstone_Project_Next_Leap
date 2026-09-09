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
