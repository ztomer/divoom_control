#!/usr/bin/env python3
"""bump_version.py VERSION -- move the product's one version to VERSION, in every place it lives.

The places are the ones tools/check_version_consistency.py holds together: pyproject.toml's
`[project] version`, the `[package] version` of the two product crates (divoomd, divoom-menubar)
and their two `[[package]]` entries in Cargo.lock. Cargo.lock is edited in place rather than
through `cargo update --workspace`, which needs the registry index; a workspace member's lock
entry is its name and version, so the edit is exact and offline.

Refuses a version that is not above the current one (a release moves forward), and a file whose
version line it cannot find (a bump that silently touched nothing is the failure this replaces).
Prints nothing on success; exit 0 changed, 2 refused.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
CRATES = ("divoomd", "divoom-menubar")


def parse(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.split("."))


def current() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def sub_once(text: str, pattern: str, repl: str, where: str) -> str:
    new, n = re.subn(pattern, repl, text, count=1, flags=re.M)
    if n != 1:
        raise SystemExit(f"bump_version: no version line found in {where}")
    return new


def bump(version: str, root: Path = ROOT) -> None:
    files: dict[Path, str] = {}
    files[root / "pyproject.toml"] = sub_once(
        (root / "pyproject.toml").read_text(encoding="utf-8"),
        r'^version\s*=\s*"[^"]+"',
        f'version = "{version}"',
        "pyproject.toml",
    )
    for crate in CRATES:
        path = root / crate / "Cargo.toml"
        files[path] = sub_once(
            path.read_text(encoding="utf-8"), r'^version\s*=\s*"[^"]+"', f'version = "{version}"', str(path)
        )
    lock = root / "Cargo.lock"
    text = lock.read_text(encoding="utf-8")
    for crate in CRATES:
        text = sub_once(
            text, rf'(^name = "{re.escape(crate)}"\nversion = )"[^"]+"', rf'\1"{version}"', f"Cargo.lock ({crate})"
        )
    files[lock] = text
    for path, content in files.items():
        path.write_text(content, encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not SEMVER.match(argv[1]):
        print("usage: bump_version.py X.Y.Z", file=sys.stderr)
        return 2
    if parse(argv[1]) <= parse(current()):
        print(f"bump_version: {argv[1]} is not above the current {current()}", file=sys.stderr)
        return 2
    bump(argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
