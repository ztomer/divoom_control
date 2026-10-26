"""A stable identity for the helpers the app spawns.

`divoomd` and `divoom-menubar` are bare binaries, not NSApplications. A
`quit:` by bundle id cannot reach either of them: the daemon's embedded
`__TEXT,__info_plist` exists for the Bluetooth grant, not for LaunchServices,
and the menubar has no plist at all. Both are spawned DETACHED, in their own
session, so they do not die with the app and are reparented to launchd.

So the only way to say "stop THAT process" was "stop every process whose
command line looks like this" — the homebrew cask's `pkill -f
Divoom.app/Contents/Frameworks/bin/divoom`, and this repo's own `pkill -f
divoom-menubar`. A name pattern is not an address: it can match a process
this app does not own, and it cannot tell one instance from another.

An identity file is the address. The app writes one per helper it spawns and
removes it when it stops that helper:

    ~/.config/divoom-control/run/divoomd.pid
    ~/.config/divoom-control/run/divoom-menubar.pid

A PID alone is NOT an identity — the OS reuses PIDs — so the file carries the
process's START TIME as well. An identity left behind by a crashed run
therefore resolves to NOTHING: the reader sees that the PID is alive but
started at a different moment, and leaves that innocent process alone. That
is the property that makes it safe for an uninstall to act on.

The start time is read with `ps -o lstart=` under `LC_ALL=C`, so the value
is the same string on every machine and in every locale, and a reader (this
app, or a shell script) can compare it without parsing a date.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path

from divoom_lib.utils.atomic_io import atomic_write_text

# The two helpers, by the name their identity file carries.
DAEMON = "divoomd"
MENUBAR = "divoom-menubar"

# Where the identities live. The config directory is the app's own home, and
# the homebrew cask already trashes it (`zap trash: "~/.config/divoom-control"`).
CONFIG_DIR = Path.home() / ".config" / "divoom-control"
RUN_DIR = CONFIG_DIR / "run"

# The environment override, so a test (or a second install) can keep its
# identities to itself.
ENV_DIR = "DIVOOM_IDENTITY_DIR"


def run_dir() -> Path:
    """The directory the identity files live in."""
    override = os.environ.get(ENV_DIR)
    if override:
        return Path(override)
    return RUN_DIR


def identity_path(name: str) -> Path:
    """The identity file of one helper."""
    return run_dir() / f"{name}.pid"


def process_started(pid: int) -> str | None:
    """The process's start time, as the OS reports it, or None if it is gone.

    `ps -o lstart=` prints e.g. ``Mon Oct 20 08:30:00 2026``. `LC_ALL=C`
    pins the format, so the string is comparable across machines and across
    the reader's locale.
    """
    try:
        done = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "lstart="],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=5,
            env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    value = done.stdout.strip()
    return value or None


def write(name: str, pid: int, command: str = "") -> None:
    """Record the identity of a helper this app just spawned.

    The start time is read AFTER the spawn, so it is the spawned process's own
    start time; the command is what we asked for, which is the app's own
    binary path.
    """
    payload = {
        "pid": int(pid),
        "started": process_started(int(pid)) or "",
        "command": command,
        "written_at": int(time.time()),
    }
    atomic_write_text(identity_path(name), json.dumps(payload, indent=2) + "\n")


def read(name: str) -> dict | None:
    """The identity file's contents, or None when there is none to read."""
    path = identity_path(name)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def resolve(name: str) -> int | None:
    """The PID this identity names — but only if it is STILL that process.

    None means: no identity, an unreadable one, or one whose PID is alive but
    is a DIFFERENT process (the OS reused the PID). The last case is the one
    that matters: acting on it would stop a process this app never spawned.
    """
    data = read(name)
    if not data:
        return None
    pid = data.get("pid")
    started = data.get("started")
    if not isinstance(pid, int) or pid <= 0:
        return None
    if not isinstance(started, str) or not started:
        return None
    live = process_started(pid)
    if live is None or live != started:
        return None
    return pid


def forget(name: str) -> None:
    """Remove an identity: the helper is gone (or was never ours)."""
    try:
        identity_path(name).unlink()
    except OSError:
        pass


def stop(name: str, sig: int = signal.SIGTERM) -> bool:
    """Stop the helper this identity names, if it is still that process.

    Returns whether a live helper was signalled. A stale identity is removed
    on the way out: it names nothing, and leaving it would keep asking the
    reader to check a process that is long gone.
    """
    pid = resolve(name)
    if pid is None:
        forget(name)
        return False
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        return False
    forget(name)
    return True
