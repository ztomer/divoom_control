#!/usr/bin/env python3
"""Single-instance lock for the Control Center, and focusing the incumbent.

Extracted from ``gui_main`` (which sits at the 500-line file cap) because the
two halves are one concern: the lock decides that another Control Center owns
the session, and the *pid it records* is the only honest way to bring that one
forward.

THE CLASS OF BUG THIS MODULE EXISTS TO PREVENT: addressing a process by
LaunchServices NAME instead of by the identity we already hold. The previous
focus path ran::

    osascript -e 'tell application "Python" to activate'

which asks LaunchServices to resolve the *name* "Python" to some registered
bundle and LAUNCH it. It never consulted the running GUI at all. On a machine
with TeX Live Utility installed, that name resolves to its embedded
``Python.framework/Versions/3.9/Resources/Python.app`` (``org.python.python``
3.9.10). Gatekeeper app-translocates that nested bundle into ``$TMPDIR``, which
breaks its ``@rpath/Versions/3.9/Python``, so it SIGABRTs in dyld before ``main``
-- one user-visible crash report per attempted "focus", while the real window
never came forward. Verified on 2026-09-07: four crash reports, each preceded
50ms earlier by this process's ``osascript`` asking LaunchServices to launch.

``System Events`` addressed by ``unix id`` cannot launch anything: it can only
front a process that already exists. That is the invariant, and
``tools/check_applescript_launch.py`` gates it repo-wide.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("divoom_gui.single_instance")

_GUI_LOCK_FH = None  # kept open for the process lifetime to hold the lock


def lock_path() -> str:
    import tempfile
    return os.path.join(tempfile.gettempdir(), "divoom_gui.lock")


def ensure_single_instance() -> bool:
    """True if we got the single-instance lock; False if a Control Center is
    already running (R24 #1 -- prevents the menubar 'Launch Dashboard' ->
    dashboard -> menubar runaway).

    Opened O_CREAT|O_RDWR rather than ``"w"``: ``open(path, "w")`` truncates
    IMMEDIATELY, before ``flock`` has decided anything, so the losing process
    wiped the incumbent's pid on its way out and :func:`running_gui_pid` found an
    empty file. The pid is the whole input to :func:`focus_running_gui`, so that
    truncation would have silently reduced focusing to a no-op. Truncate only
    once the lock is ours.
    """
    global _GUI_LOCK_FH
    try:
        import fcntl
        fd = os.open(lock_path(), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fh = os.fdopen(fd, "r+")
        except OSError:
            os.close(fd)
            raise
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:      # BlockingIOError included -- someone else holds it
            fh.close()
            return False
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()))
        fh.flush()
        _GUI_LOCK_FH = fh
        return True
    except (OSError, BlockingIOError):
        return False


def running_gui_pid() -> int | None:
    """The pid recorded in the lock file by the Control Center that holds it,
    or None when the file is missing, empty or unparseable."""
    try:
        with open(lock_path()) as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def focus_running_gui(pid: int | None) -> None:
    """Bring the already-running Control Center (``pid``) to the front.

    Addressed by unix id, never by application name -- see the module docstring
    for the crash that the name form caused. With no pid we do NOTHING: there is
    no safe name-based fallback, and a missing pid is not worth a crash report.
    """
    if pid is None:
        logger.info("No pid in the single-instance lock; not focusing.")
        return
    script = (
        'tell application "System Events"\n'
        f'    set procs to (every process whose unix id is {pid})\n'
        '    if procs is not {} then set frontmost of item 1 of procs to true\n'
        'end tell'
    )
    try:
        import subprocess
        subprocess.run(["osascript", "-e", script],
                       check=False, capture_output=True, timeout=5)
    except Exception as e:
        logger.debug("focus of pid %s skipped: %s", pid, e)
