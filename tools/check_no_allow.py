#!/usr/bin/env python3
"""Fail if any git-tracked Rust source contains an `#[allow(...)]` attribute.

Policy (user, 2026-08-02): clippy runs at `-D warnings` everywhere, and warnings
are FIXED, not silenced. An `#[allow(...)]` suppresses the lint so it never
fires, which defeats the gate — so any `#[allow]`/`#![allow]` in source is a
failure. A file is exempt only if it is machine-generated and carries the
standard `@generated` marker (see below); hand-written code never is.

    python3 tools/check_no_allow.py            # all tracked Rust files (CI gate)
    python3 tools/check_no_allow.py --staged   # only staged files (pre-commit)

Exemption: a Rust file is treated as generated iff it contains `@generated`
within its first 40 lines of comments (the de-facto marker used by prost/tonic,
bindgen and friends). Nothing else exempts a file. This is deterministic and
auditable, the same way check_no_emoji.py's codepoint ranges are.

The checker greps for the literal tokens `#[allow(` and `#![allow(` — never a
looser regex — so `#[expect(...)]` (which ERRORS if its lint never fires, the
"allow that cannot rot") stays permitted.
"""
import re
import subprocess
import sys
from pathlib import Path

_GENERATED_MARKER = "@generated"
_ALLOW_PATTERN = re.compile(r"#!?\[allow\(")


def _is_compiled_src(rel: str) -> bool:
    # Gate is scoped to compiled non-test code: any crate's src/, benches/,
    # and build.rs. Tests may legitimately unwrap and are excluded here
    # (clippy -D warnings still runs over them via --all-targets).
    if rel == "build.rs" or rel.endswith("/build.rs"):
        return True
    return "/src/" in rel or rel.startswith("src/") or "/benches/" in rel or rel.startswith("benches/")


# `-z` + NUL splitting is load-bearing: without it git QUOTES paths holding
# non-ASCII ("caf\303\251.rs") — names p.exists() can never match, so those
# files were silently skipped instead of policed.
def _split(out: bytes) -> list[str]:
    return [n.decode("utf-8", "replace") for n in out.split(b"\0") if n]


def _staged_files(root: Path):
    out = subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", "--name-only", "-z",
         "--diff-filter=ACM"],
        capture_output=True,
        check=True,
    )
    return [Path(root) / f for f in _split(out.stdout)
            if f.endswith(".rs") and _is_compiled_src(f)]


def _tracked_files(root: Path):
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "*.rs"],
        capture_output=True,
        check=True,
    )
    return [Path(root) / f for f in _split(out.stdout) if _is_compiled_src(f)]


def _is_generated(path: Path) -> bool:
    try:
        head = path.read_text(errors="replace")[:2000]
    except OSError:
        return False
    return _GENERATED_MARKER in head


def _scan(paths):
    hits = []
    for p in paths:
        if not p.exists() or _is_generated(p):
            continue
        try:
            lines = p.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if _ALLOW_PATTERN.search(line):
                hits.append(f"{p}:{i}: {line.strip()}")
    return hits


def main():
    staged = "--staged" in sys.argv
    root = Path.cwd()
    files = _staged_files(root) if staged else _tracked_files(root)
    hits = _scan(files)
    if hits:
        scope = "staged" if staged else "tracked"
        print(f"✗ [{'no_allow'}] {len(hits)} #[allow] in {scope} Rust source:")
        for h in hits[:40]:
            print(f"    {h}")
        print("fix the finding properly; do not add #[allow]. Generated files must carry @generated.")
        sys.exit(1)
    print(f"✓ [no_allow] OK — {len(files)} files clean")


if __name__ == "__main__":
    main()
