"""A real `divoomd` + a real GUI-backend bridge, owned as one disposable unit.

Extracted from `tests/test_e2e_gui_daemon_connect_disconnect.py` (2026-08-30,
P1.1-P1.3) for two reasons: that file was at 448 of the house 500-line cap, and
the teardown invariant below could not be tested from inside a module that needs
a browser to be collected. It is now exercised by
`tests/test_e2e_stack_teardown.py`, which needs neither camoufox nor a GUI
session.

**The invariant: no exit from `__init__` leaves a process running.**

It used to. Three paths could fail during bring-up and only one cleaned up:
`_assert_daemon_is_current` correctly passed `on_mismatch=self.close`, but
`_wait_for_socket` called `pytest.fail` with the daemon still alive, and
`_wait_for_http` killed the bridge and left the daemon. Raising from a
constructor means the caller never receives the object — so the fixture's
`finally: stack.close()` never runs, and teardown is bypassed *precisely* when
something has already gone wrong. That is the bypassed-funnel class: cleanup
that depends on remembering to call it at each exit will be forgotten at one.

Ten orphaned processes were found on the development machine on 2026-08-30 (four
`divoomd`, six bridges, some days old) — the accumulated output of that hole.

Two details that are easy to get wrong and both load-bearing:

* **`except BaseException`, not `except Exception`.** `pytest.fail` raises
  `Failed`, which descends from `BaseException` via `OutcomeException` — an
  `except Exception` funnel would catch none of the three failures it exists for
  and would look correct while doing nothing.
* **Every attribute `close()` touches is set before anything can fail.** The
  cleanup path runs against a half-built object by definition, so a `close()`
  that assumes `__init__` finished is itself a second failure on top of the
  first.

The socket path is also per-STACK now. It used to be keyed on `os.getpid()` —
the pytest process PID, constant for a whole run — so every stack in a session
shared one path and a single leak made the next test collide with it.
"""
from __future__ import annotations

import itertools
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import pytest

from divoom_client.daemon_protocol import DaemonClient

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BRIDGE_SCRIPT = REPO_ROOT / "tests" / "e2e_gui_bridge.py"

_STACK_SEQ = itertools.count()


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class IsolatedStack:
    """Owns the daemon + bridge subprocesses; kills only its own PIDs.

    `socket_timeout` and `http_timeout` are injectable so the failure paths can
    be driven in about a second instead of thirty-five. A cleanup path that is
    too slow to test is a cleanup path nobody tests.
    """

    def __init__(self, bin_path: Path, *, socket_timeout: float = 5.0,
                 http_timeout: float = 30.0,
                 bridge_script: Path | None = None) -> None:
        # Set BEFORE anything can raise: close() runs against a half-built
        # object by definition.
        self.daemon_proc: subprocess.Popen | None = None
        self.bridge_proc: subprocess.Popen | None = None
        self.fake_home: str | None = None
        self.client: DaemonClient | None = None
        self._closed = False

        # Per-stack, not per-process. `os.getpid()` is the same for every stack
        # in a pytest run, so one leaked daemon poisoned every later test with
        # "another divoomd is starting up". Kept in /tmp and kept short: a unix
        # socket path has a hard ~104-byte limit, and the pytest tmp dirs under
        # /var/folders are long enough to blow it.
        self.socket_path = (
            f"/tmp/divoomd_e2e_{os.getpid()}_{next(_STACK_SEQ)}_"
            f"{uuid.uuid4().hex[:8]}.sock")
        self.bridge_port = free_port()
        self.bridge_url = f"http://127.0.0.1:{self.bridge_port}"

        try:
            self._bring_up(bin_path, socket_timeout, http_timeout,
                           bridge_script or BRIDGE_SCRIPT)
        except BaseException:
            # `pytest.fail` raises Failed <- OutcomeException <- BaseException,
            # so `except Exception` here would silently catch nothing.
            self.close()
            raise

    def _bring_up(self, bin_path: Path, socket_timeout: float,
                  http_timeout: float, bridge_script: Path) -> None:
        self.fake_home = tempfile.mkdtemp(prefix="divoom_e2e_home_")

        self.daemon_proc = subprocess.Popen(
            [str(bin_path), "--socket", self.socket_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self._wait_for_socket(self.socket_path, socket_timeout)

        self.bridge_proc = subprocess.Popen(
            [sys.executable, str(bridge_script),
             "--socket-path", self.socket_path,
             "--port", str(self.bridge_port),
             "--fake-home", self.fake_home],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self._wait_for_http(self.bridge_port, http_timeout)

        self.client = DaemonClient(self.socket_path)
        self._assert_daemon_is_current(bin_path)

    def _assert_daemon_is_current(self, bin_path: Path) -> None:
        """Fail loudly if the daemon is not this tree's version.

        No `on_mismatch` callback any more: `__init__` funnels every failure
        through `close()`, so cleanup is no longer this call site's business.
        Passing it here was the one path that got it right, which is exactly how
        the other two went unnoticed — a per-site fix looks like a solved
        problem.
        """
        from tests.support.daemon_binary import assert_daemon_is_current

        assert_daemon_is_current(self.client, bin_path)

    def _wait_for_socket(self, path: str, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if os.path.exists(path):
                return
            if self.daemon_proc.poll() is not None:
                out, err = self.daemon_proc.communicate(timeout=1.0)
                pytest.fail(f"divoomd exited early. stdout={out} stderr={err}")
            time.sleep(0.05)
        pytest.fail(f"divoomd never bound {path}")

    # Generous by default: the bridge is a fresh interpreter that cold-imports
    # the whole divoom_gui stack (bleak, pyobjc, PIL, aiohttp) before it binds.
    # That is sub-second warm locally but seconds on a cold CI runner under
    # load, so a tight timeout produced spurious "never opened port" errors.
    def _wait_for_http(self, port: int, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    return
            except OSError:
                if self.bridge_proc.poll() is not None:
                    out, err = self.bridge_proc.communicate(timeout=1.0)
                    pytest.fail(
                        f"e2e_gui_bridge exited early. stdout={out} stderr={err}")
                time.sleep(0.05)
        # Surface the bridge's output so a real hang is diagnosable rather than
        # an opaque timeout. Killing it is close()'s job now, not this one's.
        out, err = self._drain(self.bridge_proc)
        pytest.fail(
            f"e2e_gui_bridge never opened port {port} in {timeout}s. "
            f"stdout={out} stderr={err}")

    @staticmethod
    def _drain(proc: subprocess.Popen) -> tuple[str, str]:
        """Stop `proc` and return whatever it said, without raising."""
        try:
            proc.terminate()
            return proc.communicate(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                return proc.communicate(timeout=2.0)
            except Exception:
                return ("", "")
        except Exception:
            return ("", "")

    def close(self) -> None:
        """Idempotent, and safe on a half-built stack.

        Called from `__init__`'s failure funnel AND from the fixture's
        `finally`, so it must tolerate both a fully-built object and one where
        almost nothing exists yet.
        """
        if self._closed:
            return
        self._closed = True

        procs = [p for p in (self.bridge_proc, self.daemon_proc) if p is not None]
        for proc in procs:
            try:
                proc.terminate()
            except OSError:
                pass
        for proc in procs:
            try:
                proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=2.0)
                except Exception:
                    pass
            except Exception:
                pass

        # The daemon unlinks its own socket on a clean exit; this covers the
        # kill path, where Drop never ran.
        for path in (self.socket_path, f"{self.socket_path}.lock",
                     f"{self.socket_path}.failure"):
            try:
                os.remove(path)
            except OSError:
                pass

        # The throwaway HOME was never cleaned up either — a directory per
        # stack, left in the system temp dir forever.
        if self.fake_home:
            import shutil

            shutil.rmtree(self.fake_home, ignore_errors=True)
            self.fake_home = None

    def pids(self) -> list[int]:
        """PIDs this stack started, for leak assertions."""
        return [p.pid for p in (self.daemon_proc, self.bridge_proc) if p is not None]
