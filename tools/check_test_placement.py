#!/usr/bin/env python3
"""check_test_placement.py — tests live in tests/, Rust test modules are cfg-gated.

Phase 1 of docs/PLANNING_TEST_REORG.md moved three stray pytest files into
tests/ and gated four ungated `pub mod *_tests` declarations in
divoomd/src/lib.rs. Without a gate both rot back: a helper lands next to
the code it tests, and a new `pub mod foo_tests` ships an empty public
module in release while advertising an API that only exists under
`cargo test`.

Two checks, both over TRACKED files (`git ls-files` — untracked scratch
is not this gate's subject):

  1. every tracked `test_*.py` / `*_test.py` lives under `tests/`.
  2. every file-backed test-module declaration (`mod foo_tests;`,
     `mod tests;`) in the workspace crates is gated by a `#[cfg(...test...)]`
     attribute. Inline `mod tests { ... }` blocks are out of scope.

HONEST SCOPE: check 2 is line-based, not a Rust parser. Attributes may
stack (`#[cfg(test)]` above `#[path = "..."]` above `mod`), so consecutive
attribute lines above the declaration all count. Anything fancier than
that needs rustc, which is what `cargo clippy --all-targets` (also in
GOH_CI_STEPS) is for; this gate catches the declaration-level regression
without compiling.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tui import err, info, ok  # noqa: E402
from _empty_scope import scope_is_empty  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
RUST_SRC_DIRS = ("divoomd/src", "divoom-menubar/src", "nowplaying/src")

# The tree holds ~110 .rs files; below half of that the file pattern is
# not reading what it thinks it is, and "all clean" would be compliance
# over nothing (same argument as check_hw_verify_methods.py's floor).
MIN_RS_FILES = 50

MOD_DECL_RE = re.compile(r"^\s*(pub\s+)?mod\s+([A-Za-z_][\w]*)\s*;\s*$")
CFG_TEST_RE = re.compile(r"#\[cfg\(([^]]*)\]")
ATTR_RE = re.compile(r"^\s*#\[")


def tracked(pattern: str) -> list[str]:
    r = subprocess.run(
        ["git", "ls-files", pattern],
        cwd=str(REPO), capture_output=True, text=True,
    )
    if r.returncode != 0:
        return []
    return [l for l in r.stdout.splitlines() if l.strip()]


def check_python_placement(failures: list[str]) -> int:
    """Every tracked *test*.py lives under tests/. Returns files inspected."""
    count = 0
    for f in tracked("*.py"):
        base = f.rsplit("/", 1)[-1]
        if base.startswith("test_") or base.endswith("_test.py"):
            count += 1
            if not (f == "tests/" or f.startswith("tests/")):
                failures.append(f"{f}: test file outside tests/")
    return count


def declaration_gated(lines: list[str], idx: int) -> bool:
    """Whether a `mod ...;` at lines[idx] carries a cfg(test) attribute.

    Walks up over consecutive attribute lines (#[cfg(test)], #[path],
    #[allow], doc comments); gated if any cfg attribute mentions test.
    """
    j = idx - 1
    seen_attr = False
    while j >= 0:
        line = lines[j].strip()
        if ATTR_RE.match(lines[j]):
            seen_attr = True
            m = CFG_TEST_RE.search(line)
            if m and re.search(r"\btest\b", m.group(1)):
                return True
            # cfg_attr(test, ...) also gates, but only under test:
            if "cfg_attr" in line and "test" in line:
                return True
            j -= 1
            continue
        if line.startswith("///") or line.startswith("//!") or line == "":
            j -= 1
            continue
        break
    return False


def check_rust_gating(failures: list[str]) -> int:
    """Every file-backed test module declaration is cfg(test)-gated."""
    rs_files = [
        f for d in RUST_SRC_DIRS
        for f in tracked(f"{d}/*.rs")
    ]
    for f in rs_files:
        try:
            lines = (REPO / f).read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines):
            m = MOD_DECL_RE.match(line)
            if not m:
                continue
            name = m.group(2)
            if name != "tests" and not name.endswith("_tests"):
                continue
            if not declaration_gated(lines, i):
                failures.append(
                    f"{f}:{i + 1}: `mod {name};` without #[cfg(test)] — "
                    f"ships an empty public module in release"
                )
    return len(rs_files)


def main() -> int:
    failures: list[str] = []
    n_py = check_python_placement(failures)
    n_rs = check_rust_gating(failures)

    if scope_is_empty("test-placement", n_py + n_rs, unit="files"):
        return 1
    if n_rs < MIN_RS_FILES:
        err(f"[test-placement] only {n_rs} .rs files scanned "
            f"(floor {MIN_RS_FILES}) — the file pattern is blind, not clean")
        return 1
    if failures:
        err(f"[test-placement] {len(failures)} problem(s)")
        for fl in failures:
            info(fl)
        return 1
    ok(f"[test-placement] OK — {n_py} test files under tests/, "
       f"{n_rs} .rs files all gated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
