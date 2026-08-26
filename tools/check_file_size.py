#!/usr/bin/env python3
"""Fail if any git-tracked source file exceeds the 500-line house limit.

Policy (project, AGENTS.md / CLAUDE.md): every source file stays under 500 lines.
Long files get split into cohesive modules. This is a deterministic, app-free gate
run by CI and (optionally) the pre-commit hook so the rule can't silently regress
the way it did for the Rust native port (`live_jobs.rs` reached 965 lines unnoticed
because nothing enforced it).

    python3 tools/check_file_size.py            # all tracked source files (CI gate)
    python3 tools/check_file_size.py --staged   # only staged files (pre-commit hook)

Counts physical lines. Tests, generated code, and vendored trees are exempt (see
EXCLUDE_PREFIXES / EXEMPT) — the limit is about authored production source.
"""
import os, subprocess, sys

MAX_LINES = 500

# Source extensions the rule applies to.
SOURCE_EXTS = (".rs", ".py", ".js", ".css", ".sh", ".c", ".h")

# Trees we don't author or that are intentionally exempt from the source limit:
#   tests/, **/tests/      — test files may legitimately be long (fixtures/cases)
#   docs/divoom_docs/      — captured Divoom API responses (vendor data)
#   target/ — Rust build output (one workspace dir since R66)
EXCLUDE_PREFIXES = ("tests/", "docs/divoom_docs/")
EXCLUDE_SUBSTRINGS = ("/tests/", "/target/", "/__pycache__/")

# Specific files exempt by path (generated, or a documented exception).
EXEMPT = set()


def _root() -> str:
    return subprocess.run(["git", "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True).stdout.strip()


def _is_source(f: str) -> bool:
    if not f.endswith(SOURCE_EXTS):
        return False
    if f in EXEMPT or f.startswith(EXCLUDE_PREFIXES):
        return False
    return not any(s in f for s in EXCLUDE_SUBSTRINGS)


def _files(root: str, staged: bool):
    # `-z` + NUL splitting is load-bearing: without it git QUOTES paths holding
    # non-ASCII ("caf\303\251.py"), a name open() can never resolve — those
    # files were silently unpoliced (open() failed and the loop continued).
    cmd = (["git", "diff", "--cached", "--name-only", "-z", "--diff-filter=ACM"]
           if staged else ["git", "ls-files", "-z"])
    out = subprocess.run(cmd, cwd=root, capture_output=True).stdout
    names = [n.decode("utf-8", "replace") for n in out.split(b"\0")]
    return [f for f in names if f and _is_source(f)]


def main() -> int:
    staged = "--staged" in sys.argv
    root = _root()
    if not root:
        print("[file_size] not a git repo — skipping"); return 0
    files = _files(root, staged)
    bad = []
    for f in files:
        try:
            with open(os.path.join(root, f), encoding="utf-8", errors="replace") as fh:
                n = sum(1 for _ in fh)
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            continue
        if n > MAX_LINES:
            bad.append((n, f))
    if bad:
        scope = "staged" if staged else "tracked"
        print(f"✗ {len(bad)} source file(s) over {MAX_LINES} lines ({scope}) — "
              f"split into cohesive modules:")
        for n, f in sorted(bad, reverse=True):
            print(f"  {f}: {n} lines")
        return 1
    print(f"✓ [file_size] OK — {len(files)} source files within {MAX_LINES} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
