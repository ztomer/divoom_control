"""The helpers have a stable identity, and a stale one names nothing.

`divoomd` and `divoom-menubar` are bare binaries in their own sessions: a
`quit:` by bundle id cannot reach them, and the only way to stop them was a
name pattern (`pkill -f divoom-menubar`, and the homebrew cask's `pkill -f
Divoom.app/Contents/Frameworks/bin/divoom`). A pattern is not an address.

These tests are the three properties the identity has to have:

  1. it REACHES the helper -- the app can stop the process it spawned by its
     identity, with no name pattern anywhere;
  2. it is CLEANED UP on the app's quit path -- the identity is gone when the
     helper is stopped, so nothing is left claiming a pid;
  3. a STALE identity -- one left behind by a crashed run -- names NOTHING.
     The OS reuses pids, so an identity that carried only a pid would point
     at whatever process took that pid next. The identity carries the
     process's start time, and a pid that is alive but started at a different
     moment is NOT the helper.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from divoom_client import helper_identity


def _spawn_sleeper() -> subprocess.Popen:
    """A process to be identified: it does nothing, and it is ours."""
    return subprocess.Popen(
        ["/bin/sleep", "120"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )


def _wait_gone(proc: subprocess.Popen, timeout: float = 5.0) -> bool:
    """Wait for the process to exit.

    `proc.wait` and not `kill(pid, 0)`: a killed child stays a ZOMBIE until it
    is reaped, and a zombie still answers signal 0 -- so the poll would report
    a process that is gone as one that is alive.
    """
    try:
        proc.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        return False


def test_an_identity_reaches_the_process_it_names(monkeypatch, tmp_path):
    monkeypatch.setenv(helper_identity.ENV_DIR, str(tmp_path))
    proc = _spawn_sleeper()
    try:
        helper_identity.write(helper_identity.MENUBAR, proc.pid, "/bin/sleep")
        assert helper_identity.resolve(helper_identity.MENUBAR) == proc.pid
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_a_stale_identity_names_nothing(monkeypatch, tmp_path):
    """The pid is alive, but it is NOT the process the identity was written for.

    This is the recycled-pid case, made exactly: the identity records a start
    time, and the live process started at a different moment.
    """
    monkeypatch.setenv(helper_identity.ENV_DIR, str(tmp_path))
    proc = _spawn_sleeper()
    try:
        helper_identity.write(helper_identity.MENUBAR, proc.pid, "/bin/sleep")
        data = json.loads(helper_identity.identity_path(helper_identity.MENUBAR).read_text())
        assert data["pid"] == proc.pid
        # Same pid, a start time that is not this process's.
        data["started"] = "Mon Jan  1 00:00:00 1990"
        helper_identity.identity_path(helper_identity.MENUBAR).write_text(json.dumps(data))
        assert helper_identity.resolve(helper_identity.MENUBAR) is None
        # And the process it names is still very much alive.
        os.kill(proc.pid, 0)
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_the_identity_of_a_dead_process_names_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv(helper_identity.ENV_DIR, str(tmp_path))
    proc = _spawn_sleeper()
    helper_identity.write(helper_identity.MENUBAR, proc.pid, "/bin/sleep")
    proc.kill()
    proc.wait(timeout=5)
    assert helper_identity.resolve(helper_identity.MENUBAR) is None


def test_stopping_by_identity_kills_that_process_and_clears_the_identity(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(helper_identity.ENV_DIR, str(tmp_path))
    proc = _spawn_sleeper()
    try:
        helper_identity.write(helper_identity.MENUBAR, proc.pid, "/bin/sleep")
        assert helper_identity.stop(helper_identity.MENUBAR) is True
        assert _wait_gone(proc), "the identified process was not stopped"
        assert not helper_identity.identity_path(helper_identity.MENUBAR).exists()
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_stopping_a_stale_identity_leaves_the_live_process_alone(
    monkeypatch, tmp_path
):
    """A stale identity must not stop the innocent process that took the pid."""
    monkeypatch.setenv(helper_identity.ENV_DIR, str(tmp_path))
    proc = _spawn_sleeper()
    try:
        helper_identity.write(helper_identity.MENUBAR, proc.pid, "/bin/sleep")
        data = json.loads(helper_identity.identity_path(helper_identity.MENUBAR).read_text())
        data["started"] = "Mon Jan  1 00:00:00 1990"
        helper_identity.identity_path(helper_identity.MENUBAR).write_text(json.dumps(data))
        assert helper_identity.stop(helper_identity.MENUBAR) is False
        time.sleep(0.2)
        os.kill(proc.pid, 0)  # still alive: nothing was killed
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_the_quit_path_clears_the_daemon_identity(monkeypatch, tmp_path):
    """The app's quit path removes the daemon's identity.

    The identity is a claim that a pid is our daemon; once the daemon is
    stopping, the claim is stale, and a stale claim is worse than none.
    """
    monkeypatch.setenv(helper_identity.ENV_DIR, str(tmp_path))
    sys.path.append(str(Path(__file__).resolve().parents[1] / "divoom_gui"))
    from divoom_gui import gui_main

    proc = _spawn_sleeper()
    try:
        helper_identity.write(helper_identity.DAEMON, proc.pid, "/bin/sleep")
        gui_main._forget_daemon_identity()
        assert not helper_identity.identity_path(helper_identity.DAEMON).exists()
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_the_quit_path_stops_the_menubar_by_its_identity(monkeypatch, tmp_path):
    """The menu-bar agent is stopped by its identity, not by a name pattern."""
    monkeypatch.setenv(helper_identity.ENV_DIR, str(tmp_path))
    from divoom_gui import gui_main
    monkeypatch.setattr(gui_main.sys, "platform", "darwin")
    proc = _spawn_sleeper()
    try:
        helper_identity.write(helper_identity.MENUBAR, proc.pid, "/bin/sleep")
        gui_main._terminate_menubar_agent()
        assert _wait_gone(proc), "the identified agent was not stopped"
        assert not helper_identity.identity_path(helper_identity.MENUBAR).exists()
    finally:
        proc.kill()
        proc.wait(timeout=5)
