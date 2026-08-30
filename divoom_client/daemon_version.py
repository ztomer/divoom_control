"""Daemon version guard — is the running daemon the one this client expects?

R67: `ensure_daemon` used to check only that SOMETHING answered on the socket. A
daemon left over from an older install answers `get_status` perfectly well and
then silently lacks whatever was added since. That cost three debugging cycles
in one round — most memorably a `players` call that returned an empty list
because the running daemon predated the command, with nothing in the reply to
say so.

Split out of `daemon_client.py` when that file crossed the house 500-line cap.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from divoom_client.daemon_protocol import DEFAULT_SOCKET_PATH, DaemonClient

logger = logging.getLogger("divoom_client.daemon_version")


def _daemon_alive(socket_path: str, timeout: float = 0.5) -> bool:
    """Local copy of the liveness probe, to avoid a circular import."""
    try:
        reply = DaemonClient(socket_path, timeout=timeout).send_command("get_status")
        return isinstance(reply, dict) and bool(reply.get("success"))
    except Exception:
        return False


def expected_daemon_version() -> str | None:
    """The daemon version this client expects, or None if it cannot be known.

    `divoomd`'s crate version is kept equal to the product version by
    `tools/check_version_consistency.py`, so the product version IS the expected
    daemon version.

    **pyproject.toml wins over installed package metadata**, and the order
    matters more than it looks: `importlib.metadata` reads the dist-info left by
    the last `pip install`, which on a working checkout is routinely stale. On
    this machine it reported 0.22.21 while the tree was at 0.26.0 — so metadata
    first would have made this function declare the CORRECT daemon wrong and
    kill it on every single startup. A version check that restarts a current
    daemon is worse than no version check at all.

    Returning None (rather than guessing) matters for the same reason: an
    unknown expectation must never justify killing something that might be fine.
    """
    # Source checkout: pyproject is the gated source of truth.
    try:
        import tomllib
        root = Path(__file__).resolve().parent.parent
        pyproject = root / "pyproject.toml"
        if pyproject.is_file():
            with open(pyproject, "rb") as f:
                v = tomllib.load(f)["project"]["version"]
            if isinstance(v, str) and v:
                return v
    except Exception:
        pass
    # Shipped bundle: no pyproject, so the packaged metadata is what there is.
    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            return version("divoom-control")
        except PackageNotFoundError:
            return None
    except Exception:
        return None


def running_daemon_version(socket_path: str = DEFAULT_SOCKET_PATH,
                           timeout: float = 1.0) -> str | None:
    """The version a live daemon reports, or None if it reports none.

    A daemon built before R67 has no `daemon_version` field at all, so None
    means "older than versioning existed" — which is itself a stale daemon.
    """
    try:
        reply = DaemonClient(socket_path, timeout=timeout).send_command("get_status")
    except Exception:
        return None
    if not isinstance(reply, dict):
        return None
    v = reply.get("daemon_version")
    return v if isinstance(v, str) and v else None


def _stop_stale_daemon(socket_path: str, running: str | None, expected: str) -> bool:
    """Ask a stale daemon to exit so a current one can take the socket.

    Uses the daemon's own `shutdown` command rather than a signal: it unlinks
    its socket only if it still owns it (R67/C5), so a clean exit leaves nothing
    behind for the replacement to trip over.
    """
    logger.warning(
        "daemon on %s reports version %s but %s is expected — restarting it",
        socket_path, running or "<none>", expected)
    try:
        DaemonClient(socket_path, timeout=2.0).send_command("shutdown")
    except Exception as e:
        logger.debug("shutdown command failed: %s", e)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _daemon_alive(socket_path, timeout=0.3):
            return True
        time.sleep(0.1)
    logger.error("stale daemon on %s did not exit; leaving it alone", socket_path)
    return False
