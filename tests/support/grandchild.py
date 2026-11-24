"""A stub binary that starts a child of its own, and the check that it died.

A `#!/bin/sh` stub whose body is `sleep 30` is TWO processes: the shell and
the `sleep` it forks. Killing the pid `Popen` returned kills the shell and
orphans the `sleep` to launchd, where the push gate's orphan canary found five
of them (DV.SOCKETFLAKE). A leak check that only looks at the pids it spawned
cannot see that, so this stub writes its child's pid to a file and
`assert_gone` reads it from there.
"""

from __future__ import annotations

import contextlib
import os
import signal
import stat
import time
from pathlib import Path


def stub_with_grandchild(path: Path, pidfile: Path) -> Path:
    """A stub that starts `sleep 30` in the background, records its pid, and waits."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/bin/sh\nsleep 30 &\necho $! > "{pidfile}"\nwait\n')
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def assert_gone(pidfile: Path, what: str, within: float = 5.0) -> None:
    """Fail when the stub's own child outlived it; kill it first, so the
    report does not itself leak."""
    deadline = time.monotonic() + within
    while not pidfile.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert pidfile.exists(), f"{what}: the stub never started its child"
    pid = int(pidfile.read_text().strip())
    while time.monotonic() < deadline:
        if not _alive(pid):
            return
        time.sleep(0.05)
    with contextlib.suppress(OSError):
        os.kill(pid, signal.SIGKILL)
    raise AssertionError(f"{what}: its child {pid} outlived it")
