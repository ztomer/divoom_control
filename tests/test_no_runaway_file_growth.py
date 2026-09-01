"""No tracked text file may reach a size that only corruption explains.

**R73, written from a live incident.** A scripted edit turned `docs/ROADMAP.md`
from 373 lines into **370,588** and it was committed clean. The mechanism is
worth naming because it is a general Python trap, not a typo:

    old = s[s.index(A):s.index(B)]      # A actually appears AFTER B
    s = s.replace(old, new)

When `s.index(A) > s.index(B)` the slice is `""`, and `str.replace("", new)`
inserts `new` **between every character in the file** -- one copy per character,
24,681 of them here. Nothing raises. The edit reports success.

It reached a commit because the house 500-line cap in `structural.sh` excludes
`docs/`, so the one gate that measures file size was looking the other way. The
gap is real for every excluded path, which is why this is a ceiling on ALL
tracked text rather than another rule about docs.

The threshold is deliberately far above anything legitimate (CHANGELOG.md, the
largest real file, is ~6.8k and append-only) -- this is a corruption detector,
not a style rule. The 500-line cap remains the thing that shapes source files.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CEILING = 15_000
TEXT_SUFFIXES = {".md", ".py", ".rs", ".js", ".html", ".css", ".sh",
                 ".toml", ".json", ".yml", ".yaml", ".txt"}


def tracked_text_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO,
                         capture_output=True, text=True, timeout=60)
    files = []
    for rel in out.stdout.split("\0"):
        if not rel:
            continue
        p = REPO / rel
        if p.suffix.lower() in TEXT_SUFFIXES and p.is_file():
            files.append(p)
    return files


def line_count(p: Path) -> int:
    try:
        with p.open("rb") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def test_no_tracked_text_file_is_absurdly_large():
    oversized = [(p.relative_to(REPO), n) for p in tracked_text_files()
                 if (n := line_count(p)) > CEILING]
    assert not oversized, (
        "tracked text file(s) past the corruption ceiling of "
        f"{CEILING:,} lines:\n"
        + "\n".join(f"  {rel}: {n:,} lines" for rel, n in oversized)
        + "\nA file this size is almost never intentional. The R73 case was "
          "`s.replace('', new)` from a reversed index slice, which inserts the "
          "replacement between every character."
    )


def test_the_scan_actually_sees_the_repo():
    """Calibration: an empty file list would make the gate above vacuous."""
    files = tracked_text_files()
    assert len(files) > 100, len(files)
    assert any(p.name == "CHANGELOG.md" for p in files)
    # And the ceiling must actually sit above the largest legitimate file,
    # or this gate is a tripwire on normal work.
    biggest = max(line_count(p) for p in files)
    assert biggest < CEILING, f"largest tracked file is already {biggest:,}"
    assert biggest > 1_000, f"suspiciously small maximum: {biggest}"
