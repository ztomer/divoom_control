"""
R14 §6 — emoji-free policy guard.

Rule: the GUI + lib + docs MUST NOT contain emoji characters. The
catalogue of the 14 standard emoji Unicode blocks is enforced below.
The only exception is ``references/`` (third-party reference code we
do not control).

If you need a visual icon, use:
  * A CSS-styled element (color + shape), or
  * An inline SVG (`<svg>...</svg>`), or
  * Plain text (the universal fallback).

The check is a fast scan — runs in <100ms even on a large repo.
"""
from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
EXTS = {".py", ".js", ".css", ".html", ".md", ".txt", ".toml", ".cfg", ".ini", ".sh", ".yml", ".yaml"}
EXEMPT_DIRS = {"references", ".git", "__pycache__", "node_modules",
               ".venv", "venv", "divoom_lib.egg-info",
               # transient release-build artifacts (py2app output, build venv)
               "build", "dist", ".buildvenv"}

# Standard emoji Unicode blocks. Keep this list narrow — false
# positives are better than misses. A char is an "emoji" if its
# codepoint falls in any of these blocks.
EMOJI_RANGES = [
    (0x1F300, 0x1F5FF),   # symbols & pictographs
    (0x1F600, 0x1F64F),   # emoticons
    (0x1F680, 0x1F6FF),   # transport & map
    (0x1F700, 0x1F77F),   # alchemical
    (0x1F780, 0x1F7FF),   # geometric extended
    (0x1F800, 0x1F8FF),   # supplemental arrows
    (0x1F900, 0x1F9FF),   # supplemental symbols
    (0x1FA00, 0x1FA6F),   # chess
    (0x1FA70, 0x1FAFF),   # symbols extended-A
    (0x1F1E6, 0x1F1FF),   # regional indicators (flags)
    (0x2600, 0x26FF),     # misc symbols
    (0x2700, 0x27BF),     # dingbats
    (0x2300, 0x23FF),     # misc technical (clock, hourglass)
    (0x2B00, 0x2BFF),     # arrows
]


# The Kare icon set + approved typographic arrows / Mac-key glyphs are PERMITTED
# everywhere — they are functional iconography, not decorative emoji. This mirrors
# the authoritative house emoji gate in gates_of_heck ($GOH_DIR/checks/
# check_no_emoji.py, formerly tools/check_no_emoji.py) and the
# rule in CLAUDE.md (→ ✓ ✗ ⚠ ↔ ↑ ↓ + ← ⌘ ⌥ ⌨). Listed by CODEPOINT so this file
# never contains the literal glyphs.
ALLOWED_CODEPOINTS = {
    0x2192, 0x2713, 0x2717, 0x26A0, 0x2194, 0x2191, 0x2193,  # → ✓ ✗ ⚠ ↔ ↑ ↓
    0x2190, 0x2318, 0x2325, 0x2328,                          # ← ⌘ ⌥ ⌨
}


def _is_emoji(ch: str) -> bool:
    cp = ord(ch)
    if cp in ALLOWED_CODEPOINTS:
        return False
    return any(lo <= cp <= hi for lo, hi in EMOJI_RANGES)


# Per-file exemptions: terminal tools that intentionally use the shared "kare"
# status glyphs (arrow / middot / check / cross / warning, matching
# ~/projects/scripts/_stylerc). These are functional TUI iconography, not
# decorative emoji — the R14 section-6 ban targets the latter.
#   tui/lib.{sh,py}        — the self-contained Kare TUI style helpers.
#   tools/check_no_emoji.py — the canonical house emoji gate now lives in the
#                             gates_of_heck checkout ($GOH_DIR/checks/); it lists
#                             the permitted Kare glyphs in its ALLOWED set +
#                             status messages.
#   tools/check_file_size.py — the 500-line gate; uses the same Kare check/cross
#                              glyphs in its status output.
EXEMPT_FILES = {
    "scripts/hw_smoke.py",
    "tools/check_file_size.py",
}


def _scannable_files() -> list[Path]:
    out: list[Path] = []
    for p in REPO_ROOT.rglob("*"):
        if not p.is_file() or p.suffix not in EXTS:
            continue
        if any(part in EXEMPT_DIRS for part in p.parts):
            continue
        if p.relative_to(REPO_ROOT).as_posix() in EXEMPT_FILES:
            continue
        out.append(p)
    return sorted(out)


def test_no_emoji_in_repo() -> None:
    """Scan every relevant file; fail if any emoji codepoint is found."""
    offenders: list[tuple[str, int, str, int]] = []
    for p in _scannable_files():
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            for ch in line:
                if _is_emoji(ch):
                    offenders.append((
                        str(p.relative_to(REPO_ROOT)),
                        line_no,
                        line.strip()[:80],
                        ord(ch),
                    ))
                    break  # one finding per line is enough
    assert not offenders, (
        "Emoji characters found in repo (R14 §6 forbids them):\n  "
        + "\n  ".join(
            f"{path}:{ln}  U+{cp:04X}  {line}"
            for (path, ln, line, cp) in offenders[:20]
        )
        + (f"\n  ... and {len(offenders) - 20} more" if len(offenders) > 20 else "")
    )


def test_emoji_range_table_includes_known_blocks() -> None:
    """Sanity: the EMOJI_RANGES table covers the standard blocks. If
    a future Unicode release adds a new block, this test reminds you
    to update the table.

    We use escape sequences (``"\\uXXXX"``) so this test file itself
    does not contain emoji codepoints (which would trip the main
    no-emoji scan)."""
    # Quick spot check: a few well-known emoji codepoints.
    assert _is_emoji("\U0001F697")  # 0x1F697 (transport)
    assert _is_emoji("\U0001F389")  # 0x1F389 (symbols)
    assert _is_emoji("\u2600")   # 0x2600 sun (misc symbols, forbidden; \u-escaped)
    assert _is_emoji("\u2705")  # 0x2705 check-mark-button (dingbats, forbidden; \u-escaped)
    # ...but the permitted Kare icons are NOT flagged (mirror the house gate).
    assert not _is_emoji("\u2713")  # \u2713 allowed
    assert not _is_emoji("\u2717")  # \u2717 allowed
    assert not _is_emoji("\u26A0")  # \u26A0 allowed
    # And some non-emoji Latin/ASCII characters should NOT be flagged.
    assert not _is_emoji("a")
    assert not _is_emoji("Z")
    assert not _is_emoji("0")
    assert not _is_emoji(".")
    assert not _is_emoji("—")  # em-dash, not an emoji
    assert not _is_emoji("•")  # bullet, not an emoji
