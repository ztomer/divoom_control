"""The 500-LOC rule, enforced (see ARCHITECTURE.md + docs/REVIEW_2026-06.md §1).

No tracked source file under divoom_lib / divoom_client / divoom_gui may exceed
500 lines. Existing offenders are pinned in ALLOWLIST as acknowledged debt — the
list may only SHRINK. A new oversized file fails the suite; shrinking an allowed
file below 500 and not removing it from the list also fails (so the debt is
actively retired, not forgotten).
"""
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_DIRS = ["divoom_lib", "divoom_client", "divoom_gui"]
_EXTS = {".py", ".c", ".js", ".css"}
_LIMIT = 500

# Acknowledged debt. SHRINK ONLY — split a file, then delete its entry. Do not
# add to this list; oversized new files must be split instead.
# 2026-06: fully retired — every divoom_* source file is now under 500 LOC.
ALLOWLIST: set[str] = set()


def _tracked_sources() -> list[Path]:
    files: list[Path] = []
    for d in _DIRS:
        for p in (_REPO / d).rglob("*"):
            if p.suffix in _EXTS and "__pycache__" not in p.parts and "node_modules" not in p.parts:
                files.append(p)
    return files


def _loc(p: Path) -> int:
    return sum(1 for _ in p.open("r", encoding="utf-8", errors="ignore"))


def test_no_unlisted_file_over_500_loc():
    offenders = []
    for p in _tracked_sources():
        rel = p.relative_to(_REPO).as_posix()
        if _loc(p) > _LIMIT and rel not in ALLOWLIST:
            offenders.append(f"{rel} ({_loc(p)} LOC)")
    assert not offenders, (
        "These files exceed 500 LOC and are not in the allow-list — split them "
        "(see docs/REVIEW_2026-06.md §1):\n  " + "\n  ".join(sorted(offenders))
    )


def test_allowlist_has_no_stale_entries():
    """Every allow-listed file must still exist and still be over 500 LOC.
    Once split below the limit, remove it from ALLOWLIST (debt retired)."""
    stale = []
    for rel in ALLOWLIST:
        p = _REPO / rel
        if not p.exists():
            stale.append(f"{rel} (missing — remove from ALLOWLIST)")
        elif _loc(p) <= _LIMIT:
            stale.append(f"{rel} (now {_loc(p)} LOC ≤ {_LIMIT} — remove from ALLOWLIST)")
    assert not stale, "ALLOWLIST is stale (it must shrink as files are split):\n  " + "\n  ".join(sorted(stale))
