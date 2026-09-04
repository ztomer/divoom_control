"""Read the daemon's structured bind-failure report.

# Why this exists

The daemon is spawned DETACHED with stdout/stderr redirected to a log file (see
``spawn_daemon``), so when it refuses to start, its explanation goes somewhere
no user will look. The client then waited out its timeout and logged

    Daemon did not become ready within 8.0s

which is a description of the client's patience, not of the problem. The user
saw "no daemon" and had nothing to act on -- for a stale socket, a directory in
the way, or a permission problem alike.

``divoomd`` now writes ``<socket>.failure`` on any fatal bind failure, with a
reason and a remedy, and deletes it the moment it successfully binds. This
module turns that file into something the client and GUI can show.

Reading the report rather than re-deriving the diagnosis in Python is
deliberate: the daemon is the process that actually tried to bind, it holds the
real errno, and a second implementation here would be free to drift from it.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: Exit codes divoomd uses for bind outcomes that are not configuration errors.
EXIT_ALREADY_RUNNING = 3
EXIT_STARTUP_IN_PROGRESS = 4


def failure_path(socket_path: str) -> str:
    """Sidecar path the daemon writes its bind failure to."""
    return f"{socket_path}.failure"


@dataclass(frozen=True)
class SocketFailure:
    """A refusal to bind, as reported by the daemon itself."""

    reason: str
    remedy: str
    transient: bool

    def message(self) -> str:
        """One string fit to show a user, reason first."""
        if self.remedy:
            return f"{self.reason}. {self.remedy}"
        return self.reason


def read_socket_failure(socket_path: str) -> SocketFailure | None:
    """Return the daemon's last bind failure for ``socket_path``.

    ``None`` when there is no report -- which is the normal case, and also what
    you get when the daemon never ran at all (a missing binary, a crash before
    bind). Callers must therefore keep their own fallback message rather than
    assuming a reason is always available.
    """
    path = failure_path(socket_path)
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except OSError:
        return None

    fields: dict[str, str] = {}
    for line in raw.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()

    reason = fields.get("reason", "").strip()
    if not reason:
        # A malformed report is worse than none: it would replace a truthful
        # "unknown" with an empty explanation.
        return None
    return SocketFailure(
        reason=reason,
        remedy=fields.get("remedy", "").strip(),
        transient=fields.get("transient", "").strip().lower() == "true",
    )


def clear_socket_failure(socket_path: str) -> None:
    """Delete a stale report.

    The daemon clears its own on a successful bind. This is for the client-side
    case where the user has fixed the problem by hand and we do not want the old
    reason resurfacing.
    """
    try:
        os.unlink(failure_path(socket_path))
    except OSError:
        pass


def explain_daemon_failure(socket_path: str, fallback: str) -> str:
    """The best available explanation for why no daemon is reachable.

    Falls back to ``fallback`` when the daemon left no report, so the caller
    always has something to show.
    """
    failure = read_socket_failure(socket_path)
    if failure is None:
        return fallback
    return failure.message()
