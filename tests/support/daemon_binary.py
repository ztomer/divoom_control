"""One place that answers "which divoomd should this test run?".

Three test modules used to answer it three different ways -- release-only,
debug-then-release, and newest-first -- and the differences were invisible until
they bit.

`target/release/divoomd` is the trap. Nothing in this repo rebuilds it:
`cargo build` and CI both produce `debug`, and only `scripts/build_release.sh`
(i.e. cutting a release) refreshes `release`. So a release binary sits there at
whatever version was last shipped, and any test preferring it silently exercises
old code. On 2026-08-30 a version bump turned that into seven confusing errors
across two files -- `DaemonClient`'s version guard correctly stopped the "stale
daemon" it had just been handed, and the tests reported "socket never came up"
and "[Errno 2] No such file or directory", neither of which names the cause.

The failing direction was the lucky one. The same hole silently passes tests
against code that was never compiled.

Two rules, both needed:

* pick by RECENCY, so the ordinary case is right;
* assert the running daemon's IDENTITY, so the extraordinary case says so.

Recency alone still runs a stale binary when it happens to be the newest one.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def find_divoomd() -> Path | None:
    """The most recently BUILT divoomd, or None if nothing is built."""
    built = [REPO_ROOT / "target" / flavour / "divoomd" for flavour in ("release", "debug")]
    built = [p for p in built if p.exists()]
    if not built:
        return None
    return max(built, key=lambda p: p.stat().st_mtime)


def require_divoomd() -> Path:
    """The binary to test, or skip -- never silently fall back to a stale one."""
    found = find_divoomd()
    if found is None:
        pytest.skip("divoomd binary not built. Run: cargo build -p divoomd")
    return found


def expected_version() -> str | None:
    """The daemon version this tree expects, or None when it cannot be known."""
    try:
        from divoom_client.daemon_version import expected_daemon_version

        return expected_daemon_version()
    except Exception:
        return None


def assert_daemon_is_current(client, bin_path: Path, *, on_mismatch=None) -> None:
    """Fail with the REASON when the spawned daemon is not this tree's version.

    `DaemonClient` restarts a daemon whose version does not match. That is
    correct for the app and catastrophic for a test: the daemon the test just
    spawned gets stopped underneath it, and every later call fails with a bare
    errno that names a socket rather than a version.

    `on_mismatch` is a teardown callback, and passing it matters. This is
    typically called from a fixture's setup; raising without stopping the
    daemon leaves it holding the socket (and, since R68, an advisory startup
    lock), so the next test fails with "another divoomd is starting up" and the
    real reason is buried under a cascade of misleading ones.
    """
    expected = expected_version()
    if not expected:
        return  # an unknown expectation never justifies failing a run
    reply = client.send_command("get_status", {})
    running = (reply or {}).get("daemon_version")
    if running == expected:
        return
    if on_mismatch is not None:
        on_mismatch()
    pytest.fail(
        f"{bin_path} reports daemon_version {running!r}, but this tree expects "
        f"{expected!r}. The client's version guard will stop it mid-test and the "
        f"failures will look like socket errors. Rebuild: cargo build -p divoomd"
    )
