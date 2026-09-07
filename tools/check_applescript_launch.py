#!/usr/bin/env python3
"""Fail if any tracked source addresses an application by NAME in AppleScript
without first checking that it is running.

    python3 tools/check_applescript_launch.py            # all tracked sources
    python3 tools/check_applescript_launch.py --staged   # pre-commit scope

THE CLASS. `tell application "X"` does not "talk to X" -- it asks LaunchServices
to resolve the string "X" to whichever registered bundle currently answers to
that name, and to LAUNCH it if it is not already running. The identity of the
thing that gets launched is a property of the user's machine, not of our code.

The instance that earned this gate (2026-09-07): `gui_main.main()` focused an
already-running Control Center with

    osascript -e 'tell application "Python" to activate'

On a machine with TeX Live Utility installed, "Python" resolves to its embedded
`Python.framework/Versions/3.9/Resources/Python.app` (org.python.python 3.9.10).
Gatekeeper app-translocates that nested bundle into $TMPDIR, which breaks its
`@rpath/Versions/3.9/Python`, and it SIGABRTs in dyld before main -- a crash
report for the user every time, while the window it meant to focus never moved.

THE TWO SAFE FORMS, both of which this gate permits:

  1. `System Events` -- the faceless OS scripting bridge. Addressing a target
     through it by `unix id` (see divoom_gui/single_instance.py) can only front
     a process that already exists, so it cannot launch anything.
  2. A tell guarded by `application "X" is running` in the same file, which is
     how divoom_gui/permissions.py primes Automation without ever launching
     Music or Spotify. `is running` sends no Apple Event and starts nothing.

COMMENTS AND DOCSTRINGS ARE NOT CODE -- the same lesson check_no_allow.py and
check_positional_args.py both learned by reddening CI on their own rationale.
A gate whose subject is a string literal attracts prose quoting that literal:
this file, and single_instance.py's module docstring, both spell out the exact
banned line. Python is scanned via `ast` over non-docstring string constants
(comments never reach the AST at all), Rust through the shared comment
stripper, shell with full-line comments dropped.

SCOPE IS PER FILE, deliberately: the guard and the tell it protects can sit in
different string literals of the same function, and no cheap static scope is
narrower without being wrong. A file that guards one tell of "X" and leaves
another unguarded therefore passes. That is one known limit of this instrument.

THE OTHER LIMIT, stated rather than papered over: a COMPUTED app name --
`f'tell application "{app}" ...'` -- is invisible here, and deliberately so. A
first cut reported any literal fragment ending at the open quote, and it could
not tell AppleScript from an ordinary message: this file's own
`f'{rel}: tell application "{name}" (unguarded)'` diagnostic tripped it, and
then passed again only because the help text below happens to contain the words
`application "X" is running`. An instrument that reads identically for a
violation and for a log line is not measuring the property, so that rule was
removed rather than shipped. The one dynamic caller in this repo,
divoom_gui/permissions.py, is covered directly by tests/test_permissions.py,
which asserts it never launches a player.

THE ONE EXEMPTION, and why it cannot be used as a rug. A gate needs a file full
of violating fixtures to prove it can go red, so a file may opt out by carrying
`check-applescript-launch: fixtures` -- but ONLY under `tests/`. Shipped code
has no opt-out at all, and `--staged` sees the marker the same way, so nothing
can be waved through by adding a comment to a module. Exactly one file carries
it today: tests/test_applescript_launch_gate.py.

NOTE ON SCOPE: `git ls-files` means an untracked new file is invisible to the
default run until it is staged or committed -- the same property every
tools/check_*.py gate here has. `--staged` is what closes that in pre-commit.
"""
from __future__ import annotations

import ast
import re
import subprocess
import warnings
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _srcscan import strip_rust_comments  # noqa: E402

# Faceless scripting bridges that are always present and are the sanctioned way
# to address a process by identity. Keep this list at exactly what is needed.
ALLOWED_TARGETS = {"System Events"}

# Honoured only under tests/ -- see "THE ONE EXEMPTION" above.
FIXTURE_MARKER = "check-applescript-launch: fixtures"


def is_exempt(rel: str, text: str) -> bool:
    """A tests/ file may declare itself a fixture holder. Nothing else may."""
    return rel.startswith("tests/") and FIXTURE_MARKER in text

# `tell application "X"`, `activate application "X"`, `launch application "X"`,
# and the bundle-id form `tell application id "com.x"` -- every spelling that
# hands a name to LaunchServices and lets it start a process.
_TELL = re.compile(
    r'(?:tell|activate|launch|run)\s+application\s+(?:id\s+)?"([^"]+)"',
    re.IGNORECASE,
)


def _guard_for(name: str) -> re.Pattern[str]:
    return re.compile(
        r'application\s+(?:id\s+)?"' + re.escape(name) + r'"\s+is\s+running',
        re.IGNORECASE,
    )


def _python_code_strings(text: str) -> list[str]:
    """Every string constant in a Python source EXCEPT prose, as separate parts.

    SEPARATE, not joined: joining manufactured a match that exists in no actual
    string. This gate's own `hits.append(f'{rel}: tell application "{name}" ...')`
    is an f-string, so the AST hands back the fragments `: tell application "`
    and `" (unguarded)`; glued together they read as a tell of an app literally
    named newline, and the gate failed on itself. A concrete app name must be
    found inside ONE literal, which is the only place it can really occur.

    Comments are absent from the AST by construction, so nothing filters them.
    Prose is "a string literal standing alone as a statement" -- module, class
    and function docstrings, and also the ATTRIBUTE docstring that follows a
    bare assignment. Scoping this to `body[0]` of the four docstring-bearing
    node types was not enough: `divoom_lib/utils/media_players.py` documents a
    field as 'the name used in `tell application "..."`' and the gate read its
    own subject matter as a violation on the first run. A string that is never
    bound or passed cannot reach osascript, so every `Expr` string is prose.
    """
    try:
        with warnings.catch_warnings():   # a stray invalid escape elsewhere in
            warnings.simplefilter("ignore")   # the tree is not this gate's news
            tree = ast.parse(text)
    except SyntaxError:
        return []
    prose = {
        id(n.value) for n in ast.walk(tree)
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
        and isinstance(n.value.value, str)
    }
    return [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in prose
    ]


def _strip_shell_comments(text: str) -> str:
    return "\n".join("" if ln.lstrip().startswith("#") else ln for ln in text.splitlines())


def _code_parts(text: str, suffix: str) -> list[str]:
    """The source reduced to its executable text, as independently scannable
    chunks. Rust and shell are contiguous text, so they are one chunk."""
    if suffix == ".py":
        return _python_code_strings(text)
    if suffix == ".rs":
        return [strip_rust_comments(text)]
    return [_strip_shell_comments(text)]


def scan_text(text: str, suffix: str) -> list[str]:
    """Violating app targets in one source.

    A guard is looked for across the WHOLE file (permissions.py builds the
    `is running` line and the tell it protects in different literals), while a
    tell must be found within a single chunk (see `_python_code_strings`).
    """
    parts = _code_parts(text, suffix)
    whole = "\n".join(parts)
    bad = [
        name for part in parts for name in _TELL.findall(part)
        if name not in ALLOWED_TARGETS and not _guard_for(name).search(whole)
    ]
    return list(dict.fromkeys(bad))   # de-duped, order kept


def _split(out: bytes) -> list[str]:
    return [n.decode("utf-8", "replace") for n in out.split(b"\0") if n]


def _files(root: Path, staged: bool) -> list[Path]:
    cmd = (["git", "-C", str(root), "diff", "--cached", "--name-only", "-z", "--diff-filter=ACM"]
           if staged else ["git", "-C", str(root), "ls-files", "-z"])
    out = subprocess.run(cmd, capture_output=True, check=True)
    return [root / f for f in _split(out.stdout) if f.endswith((".py", ".rs", ".sh"))]


def main() -> None:
    staged = "--staged" in sys.argv
    root = Path.cwd()
    files = [p for p in _files(root, staged) if p.exists()]
    # A gate that inspected nothing has not passed, it has abstained -- a rename
    # or a changed layout would retire it in silence (gates_of_heck's
    # check_empty_scope.py polices exactly this). `--staged` is exempt: a commit
    # touching no .py/.rs/.sh legitimately has an empty scope.
    if not staged and not files:
        print("✗ [applescript_launch] inspected 0 files — the scope is gone, not clean")
        sys.exit(1)
    hits = []
    for p in files:
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        rel = p.relative_to(root).as_posix()
        if is_exempt(rel, text):
            continue
        for name in scan_text(text, p.suffix):
            hits.append(f"{rel}: tell application \"{name}\" (unguarded)")
    if hits:
        print(f"✗ [applescript_launch] {len(hits)} unguarded AppleScript app target(s):")
        for h in hits[:40]:
            print(f"    {h}")
        print('address the process by identity (System Events + `unix id`), or guard the')
        print('tell with `if application "X" is running then`. Never let LaunchServices')
        print("pick the bundle -- see tools/check_applescript_launch.py for the crash.")
        sys.exit(1)
    print(f"✓ [applescript_launch] OK — {len(files)} files clean")


if __name__ == "__main__":
    main()
