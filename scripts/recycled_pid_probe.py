#!/usr/bin/env python3
"""Launch a browser AT a quit app's recycled pid, and report what happens.

    python3 scripts/recycled_pid_probe.py <target_pid>

D.CFXSBX / D.HELPER repro. LaunchServices keeps a record per running app,
keyed by the app's pid, and a helper the app starts can keep that record
alive after the app quits. The next AppKit process the OS gives that pid to
is then bound to the dead record and exits at once -- camoufox did, with
status 1, exactly this way. Nothing but a launch AT the recycled pid shows it,
so this tool makes one:

  1. refuses a target that is still alive (nothing to recycle);
  2. spends pids on `/usr/bin/true` until the pid after the last one is the
     target (every pid in between must be taken, or the kernel hands the
     browser a lower one);
  3. posix_spawns `camoufox --headless` there and watches it for 4 seconds;
  4. asks the unified log for the `launchedByLS` line of that pid.

Exit status: 0 when the browser kept running (the record is gone), 1 when it
exited inside the window (the D.CFXSBX signature), 2 when the probe itself
could not run (live target, no camoufox, deadline). It consumes pids at the
kernel's pace, so it can take minutes; `--deadline` bounds it.

Run it from a terminal, never while driving the screen: it starts a real
browser process. The pid-advance loop, the verdict and the lookups are
functions of injected collaborators and are tested without any of that
(tests/test_recycled_pid_probe.py).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

CAMOUFOX_CACHE = Path.home() / "Library" / "Caches" / "camoufox" / "browsers" / "official"
# The pid window in which a "next pid" check is meaningful: further away than
# this and the kernel could hand out any number of lower pids first.
WINDOW = 50
# How long the browser is watched for an early exit.
WATCH_S = 4.0


class ProbeError(Exception):
    """The probe could not run; this is not a verdict about the app."""


def find_camoufox(cache: Path = CAMOUFOX_CACHE) -> Path | None:
    """The newest installed camoufox executable, or None."""
    found = sorted(cache.glob("*/Camoufox.app/Contents/MacOS/camoufox"))
    return found[-1] if found else None


def pid_taken(pid: int, kill: Callable[[int, int], None] = os.kill) -> bool:
    """True when a process holds `pid`, including one we may not signal."""
    try:
        kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def require_free(pid: int, kill: Callable[[int, int], None] = os.kill) -> None:
    """Refuse a target that is alive: there is nothing to recycle."""
    if pid_taken(pid, kill):
        raise ProbeError(f"pid {pid} is alive; nothing to recycle")


def spawn_true_and_reap() -> int:
    """Spend one pid: run /usr/bin/true to completion and return its pid."""
    pid = os.posix_spawn("/usr/bin/true", ["true"], os.environ)
    os.waitpid(pid, 0)
    return pid


def advance_to(
    target: int,
    *,
    spawn_and_reap: Callable[[], int] = spawn_true_and_reap,
    taken: Callable[[int], bool] = pid_taken,
    clock: Callable[[], float] = time.time,
    deadline_s: float = 540,
    say: Callable[[str], None] = print,
) -> int:
    """Spend pids until the next one the kernel hands out is `target`.

    Returns the last pid spent. The stop condition is: that pid is within
    WINDOW below the target and EVERY pid between it and the target is taken,
    so no lower free pid can be given out first. A spawn that lands ON the
    target means another process took target-1 meanwhile; the counter laps.
    """
    deadline = clock() + deadline_s
    last = 0
    while clock() < deadline:
        pid = spawn_and_reap()
        last = pid
        if target - WINDOW < pid < target and all(taken(q) for q in range(pid + 1, target)):
            return pid
        if pid == target:
            say("overshot once (another process took target-1); another lap")
    raise ProbeError(f"deadline; last pid {last}")


def verdict(exit_status: int | None) -> tuple[int, str]:
    """(process exit code, report line) for the browser's fate.

    `exit_status` is None when the browser was still running at the end of the
    watch window.
    """
    if exit_status is None:
        return 0, f"camoufox still running after {WATCH_S:.0f} s -> launched cleanly"
    return 1, (
        f"camoufox exited {exit_status} inside {WATCH_S:.0f} s -> bound to a dead app's record (the D.CFXSBX signature)"
    )


def launched_by_ls_lines(log_text: str) -> list[str]:
    """The `launchedByLS` lines of a unified-log excerpt."""
    return [line for line in log_text.splitlines() if "launchedByLS" in line]


def launch_and_watch(camoufox: Path) -> tuple[int, int | None]:
    """posix_spawn camoufox headless NOW; return (its pid, exit status|None)."""
    profile = tempfile.mkdtemp(prefix="cfx_profile_")
    null = os.open(os.devnull, os.O_WRONLY)
    try:
        cpid = os.posix_spawn(
            str(camoufox),
            [str(camoufox), "--headless", "--profile", profile, "about:blank"],
            os.environ,
            file_actions=[(os.POSIX_SPAWN_DUP2, null, 1), (os.POSIX_SPAWN_DUP2, null, 2)],
        )
        started = time.time()
        print(f"camoufox pid {cpid}")
        status: int | None = None
        while time.time() - started < WATCH_S:
            reaped, raw = os.waitpid(cpid, os.WNOHANG)
            if reaped:
                status = os.waitstatus_to_exitcode(raw)
                break
            time.sleep(0.05)
        if status is None:
            os.kill(cpid, 15)
            os.waitpid(cpid, 0)
        return cpid, status
    finally:
        os.close(null)
        shutil.rmtree(profile, ignore_errors=True)


def log_lines_for(pid: int) -> list[str]:
    """What the unified log says about how `pid` was launched."""
    time.sleep(2)  # the log lags the launch
    out = subprocess.run(
        [
            "log",
            "show",
            "--last",
            "1m",
            "--style",
            "compact",
            "--predicate",
            f'eventMessage CONTAINS "launchedByLS" AND processID == {pid}',
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return launched_by_ls_lines(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("target_pid", type=int, help="the quit app's pid to recycle")
    parser.add_argument("--camoufox", type=Path, help="camoufox executable (default: newest cached)")
    parser.add_argument("--deadline", type=float, default=540, help="seconds to spend advancing pids")
    args = parser.parse_args(argv)
    try:
        camoufox = args.camoufox or find_camoufox()
        if camoufox is None or not camoufox.is_file():
            raise ProbeError(f"no camoufox executable found (looked in {CAMOUFOX_CACHE})")
        require_free(args.target_pid)
        advance_to(args.target_pid, deadline_s=args.deadline)
    except ProbeError as exc:
        print(f"recycled_pid_probe: {exc}", file=sys.stderr)
        return 2
    cpid, status = launch_and_watch(camoufox)
    if cpid != args.target_pid:
        print(f"note: camoufox got pid {cpid}, not the target {args.target_pid}")
    code, line = verdict(status)
    print(line)
    hits = log_lines_for(cpid)
    print("\n".join(hits[-3:]) or "no launchedByLS line for that pid")
    return code


if __name__ == "__main__":
    sys.exit(main())
