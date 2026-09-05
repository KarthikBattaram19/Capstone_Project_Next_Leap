"""Where Settings looks for the .env file, and that it does not depend on the cwd."""

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3]
REPO = BACKEND.parent


def _read_key_from(cwd: Path) -> str:
    """Start a fresh interpreter in `cwd` and report the groq key Settings resolves."""
    out = subprocess.run(
        [sys.executable, "-c", "from scout.config import Settings; print(Settings().groq_api_key)"],
        cwd=cwd,
        capture_output=True,
        check=False,  # the assertion below reports stderr, which is more useful than a raise
        text=True,
        # Remove the variable rather than blanking it: an empty env var is still *set*,
        # and a set variable outranks the env file in pydantic-settings.
        env={k: v for k, v in os.environ.items() if k != "GROQ_API_KEY"}
        | {"PYTHONPATH": str(BACKEND)},
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_backend_env_is_found_from_any_working_directory(tmp_path):
    # The conventions put secrets in backend/.env and run commands from the repo root.
    # A cwd-relative env_file would silently ignore the file in exactly that case: the
    # integration tests would skip and the boot check would report the secrets missing,
    # with the file sitting right there.
    env = BACKEND / ".env"
    if env.exists():
        pytest_skip = True  # never clobber a developer's real secrets
    else:
        pytest_skip = False
        env.write_text("GROQ_API_KEY=sentinel_from_backend_env\n", encoding="utf-8")
    try:
        if pytest_skip:
            import pytest

            pytest.skip("backend/.env exists; not overwriting real secrets")
        assert _read_key_from(REPO) == "sentinel_from_backend_env"
        assert _read_key_from(BACKEND) == "sentinel_from_backend_env"
        assert _read_key_from(tmp_path) == "sentinel_from_backend_env"
    finally:
        if not pytest_skip:
            env.unlink()
