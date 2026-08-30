"""Resolve the house TUI helpers, wherever they happen to live.

The canonical implementation is `gates_of_heck/tui/lib.py`, found via `GOH_DIR`.
That works on a dev machine and NOWHERE ELSE: CI checks the repo out into
`$GITHUB_WORKSPACE/goh` and sets no `GOH_DIR`, so a gate that imports
`tui.lib` directly dies with `ModuleNotFoundError: No module named 'tui'`
before it checks anything.

Four gates added in R67 did exactly that. They passed locally and would have
been unusable in CI — a local gate stronger than CI's is the mirror of the
"local gate weaker than CI" trap the house rules already name, and just as bad:
it means the two disagree about what "green" means.

Resolution order: `GOH_DIR`, then the CI checkout paths, then a plain-text
fallback so a gate still RUNS and still reports pass/fail without the icons.
Losing colour is acceptable; refusing to check anything is not.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _candidate_dirs() -> list[Path]:
    dirs = []
    if os.environ.get("GOH_DIR"):
        dirs.append(Path(os.environ["GOH_DIR"]))
    ws = os.environ.get("GITHUB_WORKSPACE")
    if ws:
        dirs.append(Path(ws) / "goh")
    # A `goh/` checkout beside the repo root, which is what the CI job creates.
    dirs.append(Path(__file__).resolve().parent.parent / "goh")
    dirs.append(Path.home() / "Projects" / "gates_of_heck")
    return dirs


def _load():
    for d in _candidate_dirs():
        if (d / "tui" / "lib.py").is_file():
            sys.path.insert(0, str(d))
            try:
                from tui.lib import err, hr, info, ok, section, warn  # noqa
                return err, info, ok, warn, hr, section
            except Exception:
                sys.path.pop(0)
    # Plain fallback: no icons, no colour, same pass/fail semantics.
    def _err(m):
        print(f"FAIL {m}", file=sys.stderr)

    def _info(m):
        print(f"  {m}")

    def _ok(m):
        print(f"OK   {m}")

    def _warn(m):
        print(f"WARN {m}")

    def _hr(width: int = 72):
        print("-" * width)

    def _section(title: str):
        print()
        _hr()
        print(f"  {title}")
        _hr()

    return _err, _info, _ok, _warn, _hr, _section


err, info, ok, warn, hr, section = _load()
