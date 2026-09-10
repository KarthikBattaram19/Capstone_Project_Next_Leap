"""Shared fixtures for the eval suites: the frozen fixture slice and the provider settings."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from scout.config import Settings
from scout.platform.artefacts import ArtefactStore

FIXTURES = Path(__file__).parent / "fixtures" / "bundle"


def required_keys() -> dict[str, str]:
    """Env name -> Settings attribute for the keys an eval run actually needs.

    Job 1's key follows `job1_provider`: asking for a Groq key when Job 1 runs on Gemini
    would fail a run over a credential nothing calls, and — worse — letting the Gemini key
    go unset ran a whole suite against `?key=` and reported 20 assertion failures that were
    really one 403 (2026-09-10).
    """
    job1 = (
        ("GEMINI_API_KEY", "gemini_api_key")
        if Settings().job1_provider == "gemini"
        else ("GROQ_API_KEY", "groq_api_key")
    )
    return {job1[0]: job1[1], "ANTHROPIC_API_KEY": "anthropic_api_key"}


@pytest.fixture(scope="session")
def fixture_bundle(tmp_path_factory) -> str:
    """A throwaway copy of the committed slice.

    chromadb 1.5.9 appends a row to its sqlite `acquire_write` table on every
    PersistentClient open (Task 1.4 hazard a), so loading `evals/fixtures/bundle` in place
    would dirty the committed sqlite on every run.
    """
    dst = tmp_path_factory.mktemp("evals") / "bundle"
    shutil.copytree(FIXTURES, dst)
    return str(dst)


@pytest.fixture(scope="session")
def store(fixture_bundle: str) -> ArtefactStore:
    return ArtefactStore.load(fixture_bundle)


def provider_keys() -> dict[str, str]:
    """Read the two keys the way the backend does: backend/.env via Settings, then the env."""
    from_env_file = Settings()
    return {
        env_name: getattr(from_env_file, attr) or os.getenv(env_name, "")
        for env_name, attr in required_keys().items()
    }


def resolve_settings(bundle_dir: str, keys: dict[str, str], allow_skip: bool) -> Settings:
    required = required_keys()
    missing = [k for k in required if not keys.get(k)]
    if missing:
        # Fail, never skip: a skipped suite reports green, and sign-off claims "60/60 on
        # three consecutive CI runs" (spec §7.3). ALLOW_EVAL_SKIP=1 is for a local run
        # where the operator knows what they are giving up; CI never sets it.
        msg = (
            f"eval suites need {', '.join(missing)}; set them, or set ALLOW_EVAL_SKIP=1 "
            "to skip deliberately"
        )
        if allow_skip:
            pytest.skip(msg)
        raise pytest.UsageError(msg)
    return Settings(
        _env_file=None,
        cors_allowed_origins="http://localhost:3000",
        bundle_dir=bundle_dir,
        **{attr: keys[env_name] for env_name, attr in required.items()},
    )


@pytest.fixture(scope="session")
def settings(fixture_bundle: str) -> Settings:
    return resolve_settings(
        fixture_bundle, provider_keys(), allow_skip=os.getenv("ALLOW_EVAL_SKIP") == "1"
    )


@pytest.fixture(scope="session")
def job2_drops(pytestconfig) -> dict[str, dict[str, int]]:
    """Per-case assembler counts, collected across the run and printed in the summary.

    Docs/JOB2_SCORES.md wants "dropped sentences per case" recorded before the third
    sign-off pass. Counts only — no sentence text (spec §5.3).
    """
    return pytestconfig.__dict__.setdefault("_job2_drops", {})


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    rows = getattr(config, "_job2_drops", None)
    if rows is None:  # no suite in this run asked for the fixture
        return
    from evals.harness.dropreport import render

    terminalreporter.write_line("")
    for line in render(rows):
        terminalreporter.write_line(line)


def load_cases(suite: str) -> list[dict]:
    d = Path(__file__).parent / "cases" / suite
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))]
