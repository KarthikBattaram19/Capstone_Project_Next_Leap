"""requirements.lock is what the Docker image installs. Guard what must not be in it."""

import tomllib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
LOCK = BACKEND / "requirements.lock"
PYPROJECT = BACKEND / "pyproject.toml"


def _lines():
    return [
        ln.strip()
        for ln in LOCK.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def test_no_editable_or_vcs_requirement():
    # `pip freeze` records the project's own editable install as a git+https line
    # pinned to a commit. The Dockerfile runs `pip install -r requirements.lock` on
    # python:3.12-slim, which has no git, so that line fails the image build; and if
    # it did resolve it would install a stale copy of scout over the one COPYed in.
    # The app is not one of its own dependencies.
    bad = [ln for ln in _lines() if ln.startswith("-e ") or "git+" in ln or "file:" in ln]
    assert bad == [], f"lockfile carries un-installable requirement(s): {bad}"


def test_every_declared_dependency_is_pinned_in_the_lock():
    declared = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["dependencies"]
    names = {d.split("==")[0].split("[")[0].lower() for d in declared}
    locked = {ln.split("==")[0].strip().lower() for ln in _lines() if "==" in ln}
    missing = sorted(names - locked)
    assert missing == [], f"declared but not in requirements.lock: {missing}"
