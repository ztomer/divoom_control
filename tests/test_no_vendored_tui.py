"""The house TUI library is gates_of_heck's, never a copy (D.VENDOR).

A copy of `tui/lib.sh` / `tui/lib.py` / `tui/stylerc` is frozen at the day it was
copied: this repo carried one that had already drifted from the shared library
(it lacked the single-write `report`, the bootstrap seam and the trampoline),
while `run_gui.sh` sourced it through `$(dirname "$0")` and three hardware
scripts imported it through the repo root, so the copy -- not the house library --
styled their output. Scripts source `${GOH_DIR:-$HOME/Projects/gates_of_heck}/tui/lib.sh`
and Python puts GOH_DIR on `sys.path` before `from tui.lib import ...`.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COPY = re.compile(r"(^|/)tui/(lib\.sh|lib\.py|stylerc)$")
# A source of the library through a path that is not the shared checkout.
LOCAL_SOURCE = re.compile(
    r"""(?:source|\.)\s+["']?(?:\$\(dirname[^)]*\)|\$\{?SCRIPT_DIR\}?|\.{1,2})/(?:\.\./)?tui/lib\.sh"""
)


def tracked() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL
    )
    return out.stdout.splitlines()


def test_no_copy_of_the_house_tui_is_tracked() -> None:
    copies = [name for name in tracked() if COPY.search(name)]
    assert not copies, "a vendored copy of the house TUI is tracked (use $GOH_DIR/tui):\n" + "\n".join(copies)


def test_no_script_sources_a_repo_local_tui() -> None:
    hits = []
    for name in tracked():
        if not name.endswith((".sh", ".bash")) and name not in ("run_gui.sh",):
            continue
        for number, line in enumerate((REPO / name).read_text(encoding="utf-8").splitlines(), 1):
            if LOCAL_SOURCE.search(line):
                hits.append(f"{name}:{number}: {line.strip()}")
    assert not hits, "scripts source a repo-local TUI instead of $GOH_DIR/tui/lib.sh:\n" + "\n".join(hits)


def test_the_local_source_detector_sees_the_old_spelling() -> None:
    assert LOCAL_SOURCE.search('source "$(dirname "$0")/tui/lib.sh"')
    assert LOCAL_SOURCE.search('. "$SCRIPT_DIR/tui/lib.sh"')
    assert not LOCAL_SOURCE.search('source "${GOH_DIR:-$HOME/Projects/gates_of_heck}/tui/lib.sh"')
