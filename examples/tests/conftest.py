"""Fixtures for the legacy suite: the repo root and examples/ on sys.path so
`divoom_lib` (retained core) and `divoom_legacy` both import, and the same
opt-in flags and leak guard the main suite uses (imported, not copied).

    python3 -m pytest examples/tests -q
"""
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
for entry in (str(_REPO), str(_REPO / "examples")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from tests.conftest import *  # noqa: E402,F401,F403 — hooks + fixtures
