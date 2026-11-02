"""Start a helper as its OWN launchd job, outside its launcher's coalition.

D.HELPER (ROADMAP P1.18, 2026-11-02). Divoom.app used to fork its helpers
(`divoomd`, `divoom-menubar`) as plain children. A child stays in its parent's
COALITION however it is detached -- `setsid`, `start_new_session`, a disclaimed
`posix_spawn`: none of them leaves it. The helpers are meant to outlive the
app (the tray, `keep_daemon_alive`), so when the app quit, launchservicesd
kept the dead app's record alive for as long as any coalition member lived
(`lsappinfo list`: ``(exited-with-subordinates)``, ``coalition: 24677 {30138
30142 42068}``). The next AppKit process to draw the app's recycled pid was
bound to that dead record and exited 1 (the D.CFXSBX camoufox failure,
`tests/support/browser_launch.py`).

The way out of a coalition is to be started by launchd: every job gets a
coalition of its own (measured 2026-11-02 -- a directly forked child of this
shell's app appeared in that app's coalition list, a `launchctl bootstrap`ped
job of the same command did not, and `launchctl print` named the job's own
``resource coalition``). So a helper is a job in the user's GUI domain,
bootstrapped from a plist this module writes into the helpers' run directory
(NOT `~/Library/LaunchAgents`: it is not a login item and must not start on
its own; `docs/launchd_jobs.json` declares the agents that dir would hold).

Starting a label boots out whatever that label was running first, so a
relaunch REPLACES the job's process -- it never adds a second.
"""
from __future__ import annotations

import hashlib
import os
import plistlib
import re
import subprocess
import time
from pathlib import Path

from divoom_client import helper_identity

#: The menubar agent's job.
MENUBAR_LABEL = "com.divoom.menubar"
#: The daemon's job on the default socket; another socket gets its own label.
DAEMON_LABEL = "com.divoom.divoomd"

#: Environment the LAUNCHER's launchd job set for itself. Handing them on
#: would tell the helper it is the app (`__CFBundleIdentifier`) or the app's
#: XPC service; launchd sets the job's own.
_LAUNCHER_ONLY = ("XPC_SERVICE_NAME", "XPC_FLAGS", "__CFBundleIdentifier")

_PID = re.compile(r"^\s*pid = (\d+)\s*$", re.MULTILINE)


def domain() -> str:
    """The user's GUI launchd domain."""
    return f"gui/{os.getuid()}"


def daemon_label(socket_path: str, default_socket: str) -> str:
    """The daemon job's label: one per socket, so a test daemon on a private
    socket can never boot out the owner's."""
    if socket_path == default_socket:
        return DAEMON_LABEL
    digest = hashlib.sha256(socket_path.encode()).hexdigest()[:10]
    return f"{DAEMON_LABEL}.{digest}"


def job_plist(label: str, argv: list[str], env: dict[str, str], log_path: str,
              *, interactive: bool = False) -> dict:
    """The job's definition. It runs once, when bootstrapped (no KeepAlive:
    the app decides when a helper runs, launchd only hosts it).

    ``AbandonProcessGroup``: a job's children (the dashboard the tray opens)
    are not the job, so booting the job out must not take them with it.
    """
    plist = {
        "Label": label,
        "ProgramArguments": list(argv),
        "EnvironmentVariables": {
            k: v for k, v in env.items() if k not in _LAUNCHER_ONLY
        },
        "RunAtLoad": True,
        "KeepAlive": False,
        "AbandonProcessGroup": True,
        "StandardInPath": "/dev/null",
        "StandardOutPath": log_path,
        "StandardErrorPath": log_path,
    }
    if interactive:
        plist["ProcessType"] = "Interactive"
    return plist


def plist_path(label: str) -> Path:
    """Where the job's plist is written: the helpers' run directory."""
    return helper_identity.run_dir() / f"{label}.plist"


def running_pid(label: str, run=None) -> int | None:
    """The pid the job is running, or None (not loaded, or not running)."""
    run = run or subprocess.run
    done = run(["/bin/launchctl", "print", f"{domain()}/{label}"],
               capture_output=True, text=True, stdin=subprocess.DEVNULL,
               check=False)
    if done.returncode != 0:
        return None
    m = _PID.search(done.stdout or "")
    return int(m.group(1)) if m else None


def start(label: str, argv: list[str], env: dict[str, str], log_path: str, *,
          interactive: bool = False, run=None,
          wait: float = 3.0) -> int:
    """(Re)start ``argv`` as the job ``label`` and return its pid.

    Any process the label was running is booted out first: one label, one
    process. Raises OSError when launchd refuses the job or it never runs.
    """
    run = run or subprocess.run
    path = plist_path(label)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        plistlib.dump(job_plist(label, argv, env, log_path,
                                interactive=interactive), fh)
    # Not loaded is the normal case; its failure says nothing.
    run(["/bin/launchctl", "bootout", f"{domain()}/{label}"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, check=False)
    done = run(["/bin/launchctl", "bootstrap", domain(), str(path)],
               capture_output=True, text=True, stdin=subprocess.DEVNULL,
               check=False)
    if done.returncode != 0:
        raise OSError(f"launchctl bootstrap {label} failed "
                      f"({done.returncode}): {(done.stderr or '').strip()}")
    deadline = time.monotonic() + wait
    while True:
        pid = running_pid(label, run=run)
        if pid:
            return pid
        if time.monotonic() >= deadline:
            raise OSError(f"launchd job {label} was bootstrapped but is not running")
        time.sleep(0.05)
