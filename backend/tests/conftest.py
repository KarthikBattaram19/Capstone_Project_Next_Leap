import sys
from pathlib import Path

# Make `scout` importable even if the editable install is missing in CI.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
