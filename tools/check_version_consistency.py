#!/usr/bin/env python3
"""check_version_consistency.py — one version, declared once, agreed everywhere.

R67: the shipped app reported **0.24.3** while the repo was at **v0.26.0**.
`pyproject.toml` is the source `release.sh` reads and `divoom.spec` stamps into
`CFBundleShortVersionString`, and its instruction is "bump it there first" — a
manual step, skipped for two consecutive releases. So v0.25.0 and v0.26.0 both
shipped a bundle whose About box, cask, and DMG name said 0.24.3.

That is the same shape as the other R67 classes: one fact declared in several
places with nothing keeping them in step, and a manual convention where a
structural gate belongs (house rule: gates are structural, not disciplinary).

Checked here:
  * `pyproject.toml` version == the newest `## vX.Y.Z` stanza in CHANGELOG.md
  * if the repo has tags, that version is also the newest release tag
  * the PRODUCT crates (divoomd, divoom-menubar) carry that same version

The crate check exists because `divoomd` reports its version over the wire in
`get_status`, and it said 0.1.0 while the product was 0.26.0 — the same stale
stamp that shipped in two DMGs, one layer down. `nowplaying/` is deliberately
NOT checked: it is a standalone reusable library and versions independently.

The tag check is skipped in a shallow clone or a fresh repo with no tags, and it
deliberately allows the version to be AHEAD of the newest tag: that is the
normal state between bumping and tagging. Being BEHIND is the failure.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tui import err, info, ok  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
CHANGELOG_HEADING = re.compile(r"^##\s+v(\d+\.\d+\.\d+)", re.M)
CRATE_VERSION = re.compile(r'^version\s*=\s*"([^"]+)"', re.M)

# Crates that ARE the product and must carry its version. `nowplaying` is a
# standalone library and is deliberately absent.
PRODUCT_CRATES = ("divoomd", "divoom-menubar")


def parse_version(text: str) -> tuple[int, ...]:
    return tuple(int(p) for p in text.split("."))


def project_version() -> str:
    with open(REPO / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]["version"]


def newest_changelog_version() -> str | None:
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8", errors="replace")
    m = CHANGELOG_HEADING.search(text)
    return m.group(1) if m else None


def newest_tag_version() -> str | None:
    """Newest vX.Y.Z tag, or None when the repo has no tags."""
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "tag", "--list", "v*", "--sort=-v:refname"],
            capture_output=True, text=True, timeout=15,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        m = re.fullmatch(r"v(\d+\.\d+\.\d+)", line.strip())
        if m:
            return m.group(1)
    return None


def main() -> int:
    version = project_version()
    failures: list[str] = []

    changelog = newest_changelog_version()
    if changelog is None:
        failures.append("CHANGELOG.md has no `## vX.Y.Z` stanza to check against")
    elif changelog != version:
        failures.append(
            f"pyproject.toml says {version} but the newest CHANGELOG stanza is "
            f"v{changelog}. The bundle stamps pyproject's value into "
            f"CFBundleShortVersionString, so the shipped app would report "
            f"{version}."
        )

    for crate in PRODUCT_CRATES:
        manifest = REPO / crate / "Cargo.toml"
        if not manifest.is_file():
            continue
        m = CRATE_VERSION.search(manifest.read_text(encoding="utf-8"))
        if not m:
            failures.append(f"{crate}/Cargo.toml has no version")
        elif m.group(1) != version:
            failures.append(
                f"{crate}/Cargo.toml says {m.group(1)} but pyproject says "
                f"{version}. divoomd reports this over the wire in get_status, "
                f"so a stale value misinforms every client.")

    tag = newest_tag_version()
    if tag is not None and parse_version(version) < parse_version(tag):
        failures.append(
            f"pyproject.toml says {version} but v{tag} is already tagged — the "
            f"version is BEHIND a release that shipped."
        )

    if failures:
        err("[version] inconsistent")
        for f in failures:
            info(f)
        return 1

    detail = f"pyproject {version}, changelog v{changelog}"
    if tag:
        detail += f", newest tag v{tag}"
    ok(f"[version] OK — {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
