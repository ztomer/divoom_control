#!/usr/bin/env python3
"""check_built_binaries.py — a built binary carries the app version, or it is stale.

`check_version_consistency.py` keeps the DECLARED versions in step: pyproject,
the CHANGELOG stanza, the tag, and the two product crates' `Cargo.toml`. It says
nothing about what is actually COMPILED on disk, and that is the gap that bit:

  * `target/release/divoomd` is refreshed only by `scripts/build_release.sh`.
    Nothing else in this repo touches it, so after a version bump it sits at the
    previously shipped version indefinitely. On 2026-08-30 the tree was 0.28.2
    and that binary was 0.27.0.
  * `spawn_daemon` preferred `target/release` unconditionally, and the version
    guard in `ensure_daemon` shuts down a daemon whose version does not match —
    then respawns from the same stale path. Spawn, mismatch, kill, repeat.

Declared parity was green through all of it, because the manifests were right;
only the artifacts were wrong. So this gate checks the artifacts.

**The rule: `divoomd` and `divoom-menubar` always report the app version.
Anything else is stale, and stale means rebuild.** `nowplaying` is a standalone
library crate and versions independently — the same exclusion
`check_version_consistency.py` makes.

Not built is not a failure. CI builds only what it needs, and a fresh checkout
has nothing at all; failing there would make the gate fire on the absence of a
problem. A binary that EXISTS and disagrees is the failure.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _tui import err, info, ok  # noqa: E402

from divoom_client.binary_resolver import (  # noqa: E402
    PRODUCT_BINARIES,
    binary_version,
    built_candidates,
    rebuild_hint,
)
from divoom_client.daemon_version import expected_daemon_version  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def main() -> int:
    expected = expected_daemon_version()
    if not expected:
        # Same reasoning as everywhere else this question is asked: an unknown
        # expectation is not evidence of a problem, so it must not fail a run.
        ok("[built-bins] SKIP — the expected version cannot be determined")
        return 0

    failures: list[str] = []
    checked = 0
    for name in PRODUCT_BINARIES:
        for path in built_candidates(name):
            checked += 1
            got = binary_version(path)
            if got == expected:
                continue
            # Shorten for readability only. A path outside the repo is not a
            # reason to raise from inside a FAILURE branch — that would replace
            # the diagnosis with a traceback, which is precisely the failure
            # mode this gate exists to prevent elsewhere.
            try:
                rel: Path | str = path.relative_to(REPO)
            except ValueError:
                rel = path
            if got is None:
                failures.append(
                    f"{rel} does not answer --version — it predates the flag, "
                    f"so it is older than {expected}. Rebuild: {rebuild_hint(name)}")
            else:
                failures.append(
                    f"{rel} reports {got}, but this tree is {expected}. "
                    f"Rebuild: {rebuild_hint(name)}")

    if failures:
        err("[built-bins] stale binaries on disk")
        for f in failures:
            info(f)
        return 1

    if checked == 0:
        ok("[built-bins] OK — nothing built to check")
    else:
        ok(f"[built-bins] OK — {checked} built binaries all report {expected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
