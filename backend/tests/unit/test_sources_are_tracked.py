"""No source file may be swallowed by .gitignore.

Task 0.10 shipped with evals/latency/ entirely untracked: the rule `latency/` was
written for the spike's output directory at the repo root, but a pattern with no
leading slash matches at any depth, so it also hid the scorer and its tests. The
suite passed locally because the files were on disk; the repository had none of them.
"""

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SOURCE_DIRS = ("evals", "scripts", "backend/scout", "backend/tests")


def _ignored(paths: list[Path]) -> list[str]:
    """The subset of `paths` that git would ignore."""
    if not paths:
        return []
    rel = [str(p.relative_to(REPO)).replace("\\", "/") for p in paths]
    out = subprocess.run(
        ["git", "check-ignore", "--stdin"],
        cwd=REPO,
        input="\n".join(rel),
        capture_output=True,
        text=True,
        check=False,  # exit 1 just means "nothing ignored", which is the passing case
    )
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def test_no_python_source_is_gitignored():
    files = [
        p
        for d in SOURCE_DIRS
        for p in (REPO / d).rglob("*.py")
        if "__pycache__" not in p.parts and ".venv" not in p.parts
    ]
    assert files, "found no source files to check — the glob is wrong"
    assert _ignored(files) == [], "source files hidden by .gitignore"
