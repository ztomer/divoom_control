"""The app's long-lived helpers are apps of their own (D.HELPER, P1.18).

While a helper the app STARTED is alive, LaunchServices keeps the quit app's
record by pid, and the next AppKit process to draw that pid is bound to it
and exits 1 (D.CFXSBX). Measured (`divoom_client/helper_app.py`): a fork
keeps the record (coalition), a launchd job keeps it (``loadedJobs``), and
only an app bundle opened through LaunchServices does not. These tests hold:

* the build wraps each helper in a helper app, with the old
  ``Frameworks/bin`` path a symlink into it (`scripts/make_helper_apps.sh`);
* the GUI opens the menubar and a detached daemon through `open`, never as a
  fork, when they are helper apps -- and never looks for one by name;
* the GUI stops the menubar over the socket it owns.

Nothing here opens a real app: `run` is a recorder.
"""
from __future__ import annotations

import os
import plistlib
import socket
import subprocess
import threading
import types
from pathlib import Path

import pytest

from divoom_client import daemon_client, helper_app
from divoom_client.daemon_protocol import DEFAULT_SOCKET_PATH
from divoom_gui import menubar_agent

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "make_helper_apps.sh"


def _fake_app(tmp_path: Path) -> Path:
    app = tmp_path / "Divoom.app"
    bin_dir = app / "Contents" / "Frameworks" / "bin"
    bin_dir.mkdir(parents=True)
    for name in ("divoomd", "divoom-menubar"):
        exe = bin_dir / name
        exe.write_text("#!/bin/sh\necho %s 9.9.9\n" % name)
        exe.chmod(0o755)
    return app


def _wrap(app: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT), str(app)], capture_output=True,
                          text=True, stdin=subprocess.DEVNULL, check=False,
                          env={**os.environ, "DIVOOM_HELPER_VERSION": "9.9.9"})


def test_the_build_wraps_each_helper_in_a_helper_app(tmp_path):
    app = _fake_app(tmp_path)
    done = _wrap(app)
    assert done.returncode == 0, done.stderr
    for name, ident, display in (("divoom-menubar", "com.divoom.menubar", "Divoom Menubar"),
                                 ("divoomd", "com.divoom.divoomd", "divoomd")):
        old = app / "Contents" / "Frameworks" / "bin" / name
        assert old.is_symlink(), f"{name}: the old path must still run it"
        bundle = app / "Contents" / "Helpers" / f"{display}.app"
        assert helper_app.helper_bundle(old) == bundle.resolve()
        info = plistlib.loads((bundle / "Contents" / "Info.plist").read_bytes())
        assert info["CFBundleIdentifier"] == ident
        assert info["CFBundleExecutable"] == name
        out = subprocess.run([str(old)], capture_output=True, text=True,
                             stdin=subprocess.DEVNULL, check=True).stdout
        assert out.strip() == f"{name} 9.9.9"
    info = plistlib.loads((app / "Contents/Helpers/divoomd.app/Contents/Info.plist").read_bytes())
    assert info["NSBluetoothAlwaysUsageDescription"], "the daemon's Bluetooth grant needs it"
    # Idempotent: a second pass leaves the wrapped bundle alone.
    assert _wrap(app).returncode == 0


def test_a_binary_outside_a_helper_app_has_no_bundle(tmp_path):
    exe = tmp_path / "target" / "release" / "divoom-menubar"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert helper_app.helper_bundle(exe) is None
    assert helper_app.helper_bundle(tmp_path / "missing") is None


def test_open_starts_a_new_background_instance_with_the_helpers_env():
    cmd = helper_app.open_command(
        Path("/A.app/Contents/Helpers/divoomd.app"), ["--socket", "/tmp/s"],
        {"DIVOOM_X": "1", "XPC_SERVICE_NAME": "application.com.divoom.control.1",
         "__CFBundleIdentifier": "com.divoom.control", "RUST_LOG": "info", "HOME": "/h"},
        "/tmp/log")
    assert cmd[:5] == ["/usr/bin/open", "-n", "-g", "-a", "/A.app/Contents/Helpers/divoomd.app"]
    assert cmd[cmd.index("--args") + 1:] == ["--socket", "/tmp/s"]
    envs = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--env"]
    assert envs == ["DIVOOM_X=1", "RUST_LOG=info"], "the launcher's own identity is not handed on"
    assert cmd[cmd.index("--stdout") + 1] == "/tmp/log"


# ── the menubar agent ─────────────────────────────────────────────────────


class Recorder:
    def __init__(self, rc=0):
        self.calls: list[list[str]] = []
        self.rc = rc

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        return types.SimpleNamespace(returncode=self.rc, stdout="", stderr="")


def _forbid_fork(monkeypatch):
    """After the fake app is wrapped (which itself runs a subprocess)."""
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("a helper app must be opened, not forked into the app's coalition")))


def test_the_menubar_helper_app_is_opened_not_forked(tmp_path, monkeypatch):
    app = _fake_app(tmp_path)
    assert _wrap(app).returncode == 0
    _forbid_fork(monkeypatch)
    binary = str(app / "Contents/Frameworks/bin/divoom-menubar")
    monkeypatch.setattr(menubar_agent.sys, "platform", "darwin")
    monkeypatch.setattr(menubar_agent, "_resolve_menubar_binary", lambda resolve: binary)
    rec = Recorder()
    monkeypatch.setattr(subprocess, "run", rec)
    menubar_agent._spawn_menubar_agent(lambda name: None)
    assert len(rec.calls) == 1, rec.calls
    cmd = rec.calls[0]
    assert cmd[:5] == ["/usr/bin/open", "-n", "-g", "-a",
                       str((app / "Contents/Helpers/Divoom Menubar.app").resolve())]
    assert any(a.startswith("DIVOOM_GUI_PYTHON=") for a in cmd), cmd


def test_the_agent_is_never_looked_for_by_name(tmp_path, monkeypatch):
    """`pgrep` excludes its own ancestors: from the GUI the tray opened, it
    could not see that tray, and a second one was spawned (2026-11-02)."""
    app = _fake_app(tmp_path)
    assert _wrap(app).returncode == 0
    _forbid_fork(monkeypatch)
    monkeypatch.setattr(menubar_agent.sys, "platform", "darwin")
    monkeypatch.setattr(menubar_agent, "_resolve_menubar_binary",
                        lambda resolve: str(app / "Contents/Frameworks/bin/divoom-menubar"))
    rec = Recorder()
    monkeypatch.setattr(subprocess, "run", rec)
    menubar_agent._spawn_menubar_agent(lambda name: None)
    assert rec.calls and not any("pgrep" in c[0] for c in rec.calls), rec.calls


def test_the_gui_stops_the_agent_over_the_socket_it_owns(monkeypatch):
    run_dir = Path(f"/tmp/dvha-{os.getpid()}")
    run_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("DIVOOM_IDENTITY_DIR", str(run_dir))
    path = run_dir / "divoom-menubar.sock"
    path.unlink(missing_ok=True)
    seen = []
    with socket.socket(socket.AF_UNIX) as srv:
        srv.bind(str(path))
        srv.listen(1)

        def agent():
            conn, _ = srv.accept()
            with conn:
                seen.append(conn.recv(64))
                conn.sendall(b"ok\n")

        t = threading.Thread(target=agent)
        t.start()
        assert menubar_agent._ask_agent_to_step_down() is True
        t.join(timeout=5)
    path.unlink(missing_ok=True)
    run_dir.rmdir()
    assert seen == [b"replace\n"]


# ── the daemon ────────────────────────────────────────────────────────────


def test_a_detached_daemon_helper_app_is_opened_not_forked(tmp_path, monkeypatch):
    app = _fake_app(tmp_path)
    assert _wrap(app).returncode == 0
    binary = str(app / "Contents/Frameworks/bin/divoomd")
    monkeypatch.setattr(daemon_client.sys, "platform", "darwin")
    monkeypatch.setattr(daemon_client.binary_resolver, "resolve",
                        lambda name, override=None: binary)
    monkeypatch.setattr(daemon_client, "_spawn_disclaimed_macos",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            AssertionError("a detached daemon must not be forked")))
    monkeypatch.setattr(daemon_client, "_socket_holder", lambda path, wait=8.0: 5151)
    monkeypatch.setattr(daemon_client, "_record_identity", lambda pid, cmd: None)
    monkeypatch.setenv("DIVOOM_DAEMON_LOG", str(tmp_path / "d.log"))
    rec = Recorder()
    monkeypatch.setattr(subprocess, "run", rec)
    assert daemon_client.spawn_daemon(DEFAULT_SOCKET_PATH, detach=True) == 5151
    cmd = rec.calls[0]
    assert cmd[:5] == ["/usr/bin/open", "-n", "-g", "-a",
                       str((app / "Contents/Helpers/divoomd.app").resolve())]
    assert cmd[cmd.index("--args") + 1:] == ["--socket", DEFAULT_SOCKET_PATH]
    assert "DIVOOM_LINKS_RESTORE=1" in cmd


def test_an_attached_daemon_is_still_forked(tmp_path, monkeypatch):
    """Tests and the CLI spawn attached daemons they reap; those stay children."""
    app = _fake_app(tmp_path)
    assert _wrap(app).returncode == 0
    monkeypatch.setattr(daemon_client.sys, "platform", "darwin")
    monkeypatch.setattr(daemon_client.binary_resolver, "resolve",
                        lambda name, override=None: str(app / "Contents/Frameworks/bin/divoomd"))
    monkeypatch.setattr(daemon_client, "_spawn_disclaimed_macos", lambda *a, **kw: 9)
    monkeypatch.setattr(daemon_client, "_record_identity", lambda pid, cmd: None)
    monkeypatch.setenv("DIVOOM_DAEMON_LOG", str(tmp_path / "d.log"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("an attached daemon is not opened")))
    assert daemon_client.spawn_daemon("/tmp/x.sock") == 9
