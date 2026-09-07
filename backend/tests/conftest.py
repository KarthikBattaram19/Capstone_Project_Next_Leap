import shutil
import sys
from pathlib import Path

import pytest

# Make `scout` importable even if the editable install is missing in CI.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def bundle_min(tmp_path_factory) -> str:
    """A throwaway copy of fixtures/bundle_min for anything that opens its Chroma store.

    chromadb 1.5.9 appends a row to its sqlite `acquire_write` table on every
    PersistentClient open (measured 2026-09-07: two opens, two new rows), so loading the
    committed copy directly would dirty the fixture on every test run.
    """
    dst = tmp_path_factory.mktemp("bundle") / "bundle_min"
    shutil.copytree(FIXTURES / "bundle_min", dst)
    return str(dst)
