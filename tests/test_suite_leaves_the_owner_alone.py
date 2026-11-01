"""The suite never reads or writes the user's own state (2026-11-01).

The owner's `~/.config/divoom-control/links.json` was rewritten to `links: [],
wall: null` at 02:04 by a pytest run: `test_cli_device_verbs.py` spawned a real
divoomd with the developer's HOME, the daemon read the owner's links list on
the way up, dropped its wall slots, and saved the result over the owner's file.
Every daemon a test spawned also logged into `/tmp/divoom_client.log`, the
installed app's daemon log. Per-file overrides (`DIVOOM_LINKS_PATH`, ...) had
to be remembered by each test for each file; `tests/conftest.py` now replaces
the one root they derive from. These tests hold it, at the class level: the
home the suite sees, the log a spawned daemon writes, and what a real daemon
spawned by a test actually touches.
"""
from __future__ import annotations

import os
import pwd
import subprocess as sp
import tempfile
import time
from pathlib import Path

from tests.support.daemon_binary import require_divoomd

REAL_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
OWNER_STATE = REAL_HOME / ".config" / "divoom-control"


def test_the_suite_does_not_see_the_users_home():
    home = Path.home().resolve()
    assert home != REAL_HOME.resolve(), f"tests run with the user's own HOME: {home}"
    assert not str(home).startswith(str(REAL_HOME.resolve()) + os.sep), home
    state = (home / ".config" / "divoom-control").resolve()
    assert not str(state).startswith(str(OWNER_STATE.resolve())), state


def test_a_spawned_daemon_does_not_log_into_the_apps_log():
    log = os.environ.get("DIVOOM_DAEMON_LOG", "/tmp/divoom_client.log")
    assert Path(log).resolve() != Path("/tmp/divoom_client.log").resolve(), log
    assert str(Path(log).resolve()).startswith(str(Path.home().resolve())), log


def _mtimes(root: Path) -> dict[str, int]:
    if not root.is_dir():
        return {}
    return {p.name: p.stat().st_mtime_ns for p in root.iterdir() if p.is_file()}


def test_a_daemon_a_test_spawns_writes_only_the_tests_home():
    """A real divoomd, spawned the way every daemon-backed test spawns it, is
    asked to save a layout: the file appears under the suite's home, and the
    owner's state directory is not written."""
    from divoom_client.daemon_client import DaemonClient, daemon_alive, spawn_daemon

    require_divoomd()
    before = _mtimes(OWNER_STATE)
    sock = os.path.join(tempfile.mkdtemp(prefix="divoom-own-"), "d.sock")
    handle = spawn_daemon(sock)
    try:
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline and not daemon_alive(sock):
            time.sleep(0.1)
        assert daemon_alive(sock), f"the daemon never bound {sock}"
        reply = DaemonClient(sock).send_command(
            "set_topology", {"topology": {"rooms": ["Isolation-probe"]}})
        assert reply.get("success") is True, reply
        written = Path.home() / ".config" / "divoom-control" / "topology.json"
        assert written.is_file() and "Isolation-probe" in written.read_text(), written
    finally:
        if isinstance(handle, sp.Popen):
            handle.terminate()
            handle.wait(timeout=10)
        else:
            try:
                os.kill(handle, 15)
                os.waitpid(handle, 0)
            except (ProcessLookupError, ChildProcessError):
                pass
    after = _mtimes(OWNER_STATE)
    changed = sorted(k for k in after if before.get(k) != after[k])
    # The installed app's own daemon may write its files while this runs; the
    # layout file is the one this test asked a daemon to write.
    assert "topology.json" not in changed, f"the owner's layout was rewritten: {changed}"
