"""The harness itself: the settings gate fails rather than skips, and the driver is wired."""

from __future__ import annotations

import pytest

from evals.conftest import resolve_settings

KEYS = {"GROQ_API_KEY": "gsk_test", "ANTHROPIC_API_KEY": "sk-ant-test"}


def test_missing_keys_fail_the_run_and_name_both_env_names(tmp_path):
    with pytest.raises(pytest.UsageError) as e:
        resolve_settings(str(tmp_path), {"GROQ_API_KEY": "x"}, allow_skip=False)
    assert "ANTHROPIC_API_KEY" in str(e.value) and "ALLOW_EVAL_SKIP=1" in str(e.value)
    with pytest.raises(pytest.UsageError) as e:
        resolve_settings(str(tmp_path), {}, allow_skip=False)
    assert "GROQ_API_KEY, ANTHROPIC_API_KEY" in str(e.value)


def test_missing_keys_skip_only_when_the_operator_asked(tmp_path):
    with pytest.raises(pytest.skip.Exception):
        resolve_settings(str(tmp_path), {}, allow_skip=True)


def test_present_keys_reach_the_settings_without_reading_env(tmp_path):
    s = resolve_settings(str(tmp_path), KEYS, allow_skip=False)
    assert (s.groq_api_key, s.anthropic_api_key) == ("gsk_test", "sk-ant-test")
    assert s.bundle_dir == str(tmp_path) and s.origins == ["http://localhost:3000"]
