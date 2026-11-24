#!/usr/bin/env python3
"""check_socket_paths.py -- a unix socket under a temp dir goes through the helper.

`sun_path` holds 104 bytes on macOS, and the temp dir is whatever the caller's
environment says. The push gate gives each step its own TMPDIR under
`/var/folders/.../T/goh.noindex/step.NN/` (69 bytes before a name), so a socket
named `temp_dir()/divoomd_bind_<pid>_lockinherited.sock` bound on a laptop and
was refused in the gate (`PathTooLong { len: 106, max: 103 }`), and
`mkdtemp(prefix="divoomd_events_")/daemon.sock` the same in Python: 4 of 33
push-gate steps red on 2026-11-23 (DV.SOCKETFLAKE). Which name was "short
enough" was luck: sixteen more test sites sat a few bytes under the limit.

So a socket path built ON a temp dir is refused here; it is built by
`divoomd::socket_path::{scratch_socket_path, scratch_socket_dir}` (Rust) or
`divoom_client.socket_path.{scratch_socket_path, scratch_socket_dir}`
(Python), which fall back to a short base when the temp dir is too deep.

HONEST SCOPE: textual, not a parser.
  * Rust: a `.sock"` literal in the same statement (lines up to `;`) as
    `temp_dir()` or `tempdir()`.
  * Python: a `.sock` string literal on the same line as `gettempdir()`,
    `mkdtemp(` or `TemporaryDirectory(`, or on a line naming a variable the
    same file assigned from one of those.
  A path passed through a function parameter is not followed; `tmp_path`
  (pytest) is not flagged, because its base is past `sun_path` on every
  machine, so a test that binds there is red everywhere, not only in a gate.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _empty_scope import scope_is_empty
from _tui import counted, err, info, ok

REPO = Path(__file__).resolve().parent.parent

# The helpers themselves, which ARE the temp-dir join this gate funnels into,
# and this gate's own test, whose fixtures are the shapes it refuses.
HELPERS = {"divoomd/src/socket_path.rs", "divoom_client/socket_path.py", "tests/test_check_socket_paths.py"}

RUST_TEMP = re.compile(r"\btemp_dir\(\)|\btempdir\(\)")
RUST_SOCK = re.compile(r'\.sock"')
PY_TEMP = re.compile(r"\bgettempdir\(\)|\bmkdtemp\(|\bTemporaryDirectory\(")
PY_SOCK = re.compile(r"""\.sock['"]""")
PY_ASSIGN = re.compile(
    r"^\s*(?:self\.)?([A-Za-z_]\w*)\s*(?::[^=]+)?=\s*.*?(?:\bgettempdir\(\)|\bmkdtemp\(|\bTemporaryDirectory\()"
)
PY_WITH = re.compile(r"\b(?:TemporaryDirectory|mkdtemp)\([^)]*\)\s+as\s+([A-Za-z_]\w*)")


def tracked(*patterns: str) -> list[str]:
    r = subprocess.run(
        ["git", "ls-files", "--", *patterns],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    return [p for p in r.stdout.splitlines() if p.strip()] if r.returncode == 0 else []


def rust_findings(rel: str, text: str) -> list[str]:
    out: list[str] = []
    stmt: list[tuple[int, str]] = []
    for n, line in enumerate(text.splitlines(), 1):
        code = "" if line.lstrip().startswith("//") else line
        stmt.append((n, code))
        if ";" in code or code.strip().endswith(("{", "}")):
            joined = " ".join(c for _, c in stmt)
            if RUST_TEMP.search(joined) and RUST_SOCK.search(joined):
                out.append(f"{rel}:{stmt[0][0]}: a socket named under the temp dir -- use divoomd::socket_path")
            stmt = []
    return out


def python_findings(rel: str, text: str) -> list[str]:
    out: list[str] = []
    lines = text.splitlines()
    names: set[str] = set()
    for line in lines:
        for rx in (PY_ASSIGN, PY_WITH):
            m = rx.search(line)
            if m:
                names.add(m.group(1))
    for n, line in enumerate(lines, 1):
        code = "" if line.lstrip().startswith("#") else line
        if not PY_SOCK.search(code):
            continue
        via_name = any(re.search(rf"\b{re.escape(v)}\b", code) for v in names)
        if PY_TEMP.search(code) or via_name:
            out.append(f"{rel}:{n}: a socket named under the temp dir -- use divoom_client.socket_path")
    return out


def main() -> int:
    findings: list[str] = []
    seen = 0
    for rel in tracked("*.rs", "*.py"):
        if rel in HELPERS or rel.startswith(("references/", "examples/")):
            continue
        path = REPO / rel
        try:
            text = path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            continue
        if ".sock" not in text:
            continue
        seen += 1
        findings += rust_findings(rel, text) if rel.endswith(".rs") else python_findings(rel, text)
    if scope_is_empty("socket_paths", seen):
        return 1
    if findings:
        err(f"[socket_paths] {counted(len(findings), 'socket path')} built on a temp dir (sun_path is 104 bytes):")
        for f in findings:
            info(f"  {f}")
        return 1
    ok(f"[socket_paths] {counted(seen, 'file')} naming a socket: none built on a raw temp dir")
    return 0


if __name__ == "__main__":
    sys.exit(main())
