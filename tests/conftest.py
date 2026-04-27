"""Test wiring: put `src/` on the import path and provide fixture loaders."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def load_fixture(name: str) -> dict:
    """Load a JSON fixture by filename (with or without .json suffix)."""
    if not name.endswith(".json"):
        name = f"{name}.json"
    with (FIXTURES / name).open() as f:
        return json.load(f)
