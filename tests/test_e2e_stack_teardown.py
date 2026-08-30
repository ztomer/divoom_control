"""No exit from `IsolatedStack.__init__` may leave a process running.

The harness that spawns a real daemon and a real GUI bridge had three failure
paths during bring-up and cleaned up on one of them. Raising from a constructor
means the caller never receives the object, so the fixture's
`finally: stack.close()` never runs — teardown was bypassed exactly when
something had already gone wrong. Ten orphaned processes were found on the
development machine on 2026-08-30 as a result.

These tests drive each failure path with a stub and assert nothing survives.
They need no browser and no GUI session, which is the point of extracting
`tests/support/gui_daemon_stack.py`: the invariant is about process lifetime,
not about the UI, and it should not be collected behind a camoufox skip.

Every stub here is a shell script standing in for a real binary, so the paths
exercised are the real `subprocess` ones — a mocked `Popen` would prove the
funnel calls `close()` without proving `close()` reaps anything.
"""
from __future__ import annotations

import os
import signal
import stat
import time
from pathlib import Path

import pytest

from tests.support.gui_daemon_stack import IsolatedStack


def _script(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _alive(pid: int) -> bool:
    """True while `pid` exists and has not been reaped.

    `os.kill(pid, 0)` alone is not enough: a terminated child stays a zombie
    until waited on, and a zombie answers signal 0 happily. `close()` waits on
    every process it started, so a surviving zombie would mean it did not.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _assert_all_dead(pids: list[int], what: str) -> None:
    # terminate() -> wait() is not instantaneous; give the OS a moment before
    # calling a process a leak.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not any(_alive(p) for p in pids):
            return
        time.sleep(0.05)
    survivors = [p for p in pids if _alive(p)]
    for p in survivors:  # do not leak out of the test that is reporting the leak
        try:
            os.kill(p, signal.SIGKILL)
        except OSError:
            pass
    pytest.fail(f"{what}: {survivors} still running after __init__ failed")


def _capture_pids(monkeypatch) -> list[int]:
    """Record the PID of every process the stack starts.

    Taken at spawn rather than from the stack afterwards, because a failed
    `__init__` returns no object to ask — which is the whole defect.
    """
    import subprocess as sp

    pids: list[int] = []
    real_popen = sp.Popen

    class _Recording(real_popen):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            pids.append(self.pid)

    monkeypatch.setattr(
        "tests.support.gui_daemon_stack.subprocess.Popen", _Recording)
    return pids


def test_daemon_that_never_binds_is_reaped(tmp_path, monkeypatch):
    """`_wait_for_socket` timing out used to `pytest.fail` with the daemon alive.

    The stub sleeps without ever creating the socket — the "started fine, never
    became ready" case, which is the one that leaves a live process behind.
    """
    daemon = _script(tmp_path / "divoomd", "sleep 30\n")
    pids = _capture_pids(monkeypatch)

    with pytest.raises(BaseException):
        IsolatedStack(daemon, socket_timeout=0.5)

    assert pids, "no process was spawned; the test proved nothing"
    _assert_all_dead(pids, "daemon that never bound")


def test_bridge_that_never_binds_leaves_no_daemon_behind(tmp_path, monkeypatch):
    """`_wait_for_http` killed the BRIDGE and left the DAEMON running.

    Both must go. The daemon is the one that holds the socket and the advisory
    startup lock, so leaking it is what poisoned every following test.
    """
    stack_mod = pytest.importorskip("tests.support.gui_daemon_stack")
    sock = tmp_path / "d.sock"
    # Binds the socket so bring-up gets past _wait_for_socket, then idles.
    daemon = _script(
        tmp_path / "divoomd",
        f"python3 -c \"import socket,time; "
        f"s=socket.socket(socket.AF_UNIX); s.bind('{sock}'); s.listen(1); "
        f"time.sleep(30)\"\n")
    bridge = _script(tmp_path / "bridge.py", "sleep 30\n")

    monkeypatch.setattr(stack_mod.IsolatedStack, "_wait_for_socket",
                        lambda self, path, timeout: None)
    pids = _capture_pids(monkeypatch)

    with pytest.raises(BaseException):
        IsolatedStack(daemon, http_timeout=0.5, bridge_script=bridge)

    assert len(pids) == 2, f"expected daemon + bridge, got {pids}"
    _assert_all_dead(pids, "bridge that never bound")


def test_daemon_that_exits_immediately_is_reaped(tmp_path, monkeypatch):
    """The early-exit branch: `divoomd exited early`.

    Already dead, so nothing to kill — but `close()` must still wait on it so it
    does not sit as a zombie, and must not itself raise on a dead process.
    """
    daemon = _script(tmp_path / "divoomd", "exit 3\n")
    pids = _capture_pids(monkeypatch)

    with pytest.raises(BaseException):
        IsolatedStack(daemon, socket_timeout=5.0)

    assert pids
    _assert_all_dead(pids, "daemon that exited early")


def test_close_is_idempotent_and_safe_on_a_half_built_stack(tmp_path, monkeypatch):
    """`close()` runs from the failure funnel AND the fixture's `finally`.

    So it is routinely called twice, and at least once against an object whose
    `__init__` never finished. Neither may raise.
    """
    daemon = _script(tmp_path / "divoomd", "sleep 30\n")
    _capture_pids(monkeypatch)

    stack = None
    try:
        IsolatedStack(daemon, socket_timeout=0.5)
    except BaseException:
        pass

    # And directly: a stack built far enough to have attributes but no procs.
    stack = IsolatedStack.__new__(IsolatedStack)
    stack.daemon_proc = None
    stack.bridge_proc = None
    stack.fake_home = None
    stack.client = None
    stack._closed = False
    stack.socket_path = str(tmp_path / "never-created.sock")
    stack.close()
    stack.close()  # second call must be a no-op, not an error


def test_the_throwaway_home_is_removed(tmp_path, monkeypatch):
    """Each stack made a `divoom_e2e_home_*` temp dir and never removed it.

    A directory per stack, left in the system temp dir forever — the quiet
    sibling of the process leak, and invisible because nothing ever failed.
    """
    daemon = _script(tmp_path / "divoomd", "sleep 30\n")
    _capture_pids(monkeypatch)

    homes: list[str] = []
    real_mkdtemp = __import__("tempfile").mkdtemp

    def recording(*a, **kw):
        d = real_mkdtemp(*a, **kw)
        homes.append(d)
        return d

    monkeypatch.setattr("tests.support.gui_daemon_stack.tempfile.mkdtemp", recording)

    with pytest.raises(BaseException):
        IsolatedStack(daemon, socket_timeout=0.5)

    assert homes, "no throwaway HOME was created; the test proved nothing"
    assert not os.path.exists(homes[0]), f"{homes[0]} survived teardown"


def test_two_stacks_do_not_share_a_socket_path(tmp_path, monkeypatch):
    """The path used to be keyed on `os.getpid()` — constant for a whole pytest
    run — so every stack in a session collided on one path and a single leaked
    daemon made the next test fail with "another divoomd is starting up"."""
    daemon = _script(tmp_path / "divoomd", "sleep 30\n")
    _capture_pids(monkeypatch)

    seen = []
    for _ in range(2):
        try:
            IsolatedStack(daemon, socket_timeout=0.2)
        except BaseException as e:
            seen.append(str(e))

    paths = [s.split()[-1] for s in seen if "never bound" in s]
    assert len(paths) == 2, seen
    assert paths[0] != paths[1], f"both stacks used {paths[0]}"
