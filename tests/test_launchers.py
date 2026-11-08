"""Guard against launcher/build path drift (the R17 gui/ -> divoom_gui/ rename
left run_gui.sh + Makefile pointing at dead paths; R20 moved the dylib).

These assert that the *referenced* files actually exist on disk, so a future
move/rename that forgets a script fails the suite instead of the user.
"""

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]

# Patterns that capture a repo-relative path argument from shell/Make recipes.
_RUNNERS = re.compile(r"""(?:python3?|bash|sh)\s+([A-Za-z0-9_./-]+\.(?:py|sh))""")


def _referenced_paths(text: str) -> list[str]:
    return _RUNNERS.findall(text)


def test_run_gui_points_at_existing_entrypoint():
    script = _REPO / "run_gui.sh"
    assert script.exists(), "run_gui.sh is missing"
    refs = _referenced_paths(script.read_text(encoding="utf-8"))
    assert refs, "run_gui.sh references no python/bash script — parser drift?"
    for rel in refs:
        assert (_REPO / rel).exists(), f"run_gui.sh points at a missing file: {rel}"
    # Specifically the GUI entrypoint (post-R17 location).
    assert "divoom_gui/gui_main.py" in refs


def test_makefile_referenced_scripts_exist():
    mk = _REPO / "Makefile"
    assert mk.exists()
    for rel in _referenced_paths(mk.read_text(encoding="utf-8")):
        assert (_REPO / rel).exists(), f"Makefile points at a missing file: {rel}"


def test_no_stale_gui_path_in_launchers():
    """No launcher/build file may reference the pre-R17 top-level `gui/` dir."""
    offenders = []
    for name in ("run_gui.sh", "Makefile"):
        p = _REPO / name
        if not p.exists():
            continue
        for ln, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            # match a bare `gui/` token that is NOT `divoom_gui/`
            if re.search(r"(?<![A-Za-z_])gui/", line) and "divoom_gui/" not in line:
                offenders.append(f"{name}:{ln}: {line.strip()}")
    assert not offenders, "stale pre-R17 gui/ path in launchers:\n  " + "\n  ".join(offenders)
