"""The app's helpers run as launchd jobs of their own (D.HELPER, P1.18).

A forked child stays in the app's coalition however it is detached, and a
helper alive in that coalition keeps the quit app's LaunchServices record
alive by pid -- the next AppKit process to draw that pid is bound to the dead
record and exits 1 (D.CFXSBX). These tests hold the two rules that close it:

* every helper the app starts to OUTLIVE it is started by launchd
  (`divoom_client/launchd_job.py`), never forked; and
* a label runs one process: starting it again boots the old one out first,
  so a relaunch replaces a helper instead of adding one.

No test here touches the real launchd: `run` is a recorder.
"""
from __future__ import annotations

import plistlib
import subprocess
import types

import pytest

from divoom_client import daemon_client, launchd_job
from divoom_client.daemon_protocol import DEFAULT_SOCKET_PATH
from divoom_gui import menubar_agent


class FakeLaunchctl:
    """Records launchctl calls; `print` reports `pid` once bootstrapped."""

    def __init__(self, pid=4242, bootstrap_rc=0, running=None):
        self.calls: list[list[str]] = []
        self.pid = pid
        self.bootstrap_rc = bootstrap_rc
        self.loaded = running is not None
        self.running = running

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        if argv[0] != "/bin/launchctl":   # e.g. the identity's `ps`
            return types.SimpleNamespace(returncode=1, stdout="", stderr="")
        verb = argv[1]
        if verb == "bootstrap":
            if self.bootstrap_rc == 0:
                self.loaded, self.running = True, self.pid
            return types.SimpleNamespace(returncode=self.bootstrap_rc, stdout="",
                                         stderr="Bootstrap failed: 5")
        if verb == "bootout":
            was = self.loaded
            self.loaded, self.running = False, None
            return types.SimpleNamespace(returncode=0 if was else 3, stdout="", stderr="")
        if verb == "print":
            if not self.loaded:
                return types.SimpleNamespace(returncode=113, stdout="", stderr="")
            body = "state = running\n\tpid = %d\n" % self.running if self.running else "state = not running\n"
            return types.SimpleNamespace(returncode=0, stdout=body, stderr="")
        raise AssertionError(f"unexpected launchctl {argv}")

    def verbs(self):
        return [c[1] for c in self.calls]


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DIVOOM_IDENTITY_DIR", str(tmp_path))
    return tmp_path


def test_a_start_boots_the_old_process_out_before_bootstrapping(run_dir):
    fake = FakeLaunchctl(running=111)
    pid = launchd_job.start("com.divoom.t", ["/bin/x", "-v"], {"A": "1"},
                            "/dev/null", run=fake)
    assert pid == 4242
    assert fake.verbs()[:2] == ["bootout", "bootstrap"], fake.calls
    plist = plistlib.loads((run_dir / "com.divoom.t.plist").read_bytes())
    assert plist["ProgramArguments"] == ["/bin/x", "-v"]
    assert plist["KeepAlive"] is False and plist["RunAtLoad"] is True
    assert plist["AbandonProcessGroup"] is True


def test_the_launchers_own_job_identity_is_not_handed_on():
    plist = launchd_job.job_plist(
        "l", ["/bin/x"],
        {"XPC_SERVICE_NAME": "application.com.divoom.control.1.2",
         "__CFBundleIdentifier": "com.divoom.control", "XPC_FLAGS": "0", "KEEP": "y"},
        "/dev/null")
    assert plist["EnvironmentVariables"] == {"KEEP": "y"}


def test_a_refused_bootstrap_raises(run_dir):
    with pytest.raises(OSError, match="bootstrap"):
        launchd_job.start("com.divoom.t", ["/bin/x"], {}, "/dev/null",
                          run=FakeLaunchctl(bootstrap_rc=5))


def test_a_private_socket_gets_its_own_daemon_label():
    assert launchd_job.daemon_label(DEFAULT_SOCKET_PATH, DEFAULT_SOCKET_PATH) == \
        launchd_job.DAEMON_LABEL
    other = launchd_job.daemon_label("/tmp/test.sock", DEFAULT_SOCKET_PATH)
    assert other.startswith(launchd_job.DAEMON_LABEL + ".") and other != launchd_job.DAEMON_LABEL


# ── the menubar agent ─────────────────────────────────────────────────────


@pytest.fixture
def darwin_agent(monkeypatch, run_dir):
    monkeypatch.setattr(menubar_agent.sys, "platform", "darwin")
    monkeypatch.setattr(menubar_agent, "_resolve_menubar_binary",
                        lambda resolve: "/Applications/Divoom.app/bin/divoom-menubar")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("the agent must not be forked into the app's coalition")))
    fake = FakeLaunchctl()
    monkeypatch.setattr(launchd_job.subprocess, "run", fake)
    return fake


def test_the_menubar_agent_is_started_as_its_own_launchd_job(darwin_agent, run_dir):
    menubar_agent._spawn_menubar_agent(lambda name: None)
    assert "bootstrap" in darwin_agent.verbs(), darwin_agent.calls
    plist = plistlib.loads((run_dir / f"{launchd_job.MENUBAR_LABEL}.plist").read_bytes())
    assert plist["ProgramArguments"] == ["/Applications/Divoom.app/bin/divoom-menubar"]
    assert "DIVOOM_GUI_PYTHON" in plist["EnvironmentVariables"]


def test_a_running_menubar_job_is_left_alone(monkeypatch, darwin_agent):
    """The GUI the tray opened must not replace the tray that opened it."""
    darwin_agent.loaded, darwin_agent.running = True, 777
    menubar_agent._spawn_menubar_agent(lambda name: None)
    assert darwin_agent.verbs() == ["print"], darwin_agent.calls


def test_the_agent_is_never_found_by_name(darwin_agent):
    """`pgrep` excludes its own ancestors: from the GUI the tray launched it
    could not see that tray, and a second one was spawned (2026-11-02)."""
    menubar_agent._spawn_menubar_agent(lambda name: None)
    assert darwin_agent.calls, "the job was never asked"
    assert not any("pgrep" in c[0] for c in darwin_agent.calls), darwin_agent.calls


# ── the daemon ────────────────────────────────────────────────────────────


def test_a_detached_daemon_is_started_as_its_own_launchd_job(monkeypatch, run_dir):
    monkeypatch.setattr(daemon_client.sys, "platform", "darwin")
    monkeypatch.setattr(daemon_client.binary_resolver, "resolve",
                        lambda name, override=None: "/Applications/Divoom.app/bin/divoomd")
    monkeypatch.setattr(daemon_client, "_spawn_disclaimed_macos",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            AssertionError("a detached daemon must not be forked")))
    monkeypatch.setenv("DIVOOM_DAEMON_LOG", str(run_dir / "d.log"))
    fake = FakeLaunchctl(pid=5151)
    monkeypatch.setattr(launchd_job.subprocess, "run", fake)
    pid = daemon_client.spawn_daemon(DEFAULT_SOCKET_PATH, detach=True)
    assert pid == 5151
    plist = plistlib.loads((run_dir / f"{launchd_job.DAEMON_LABEL}.plist").read_bytes())
    assert plist["ProgramArguments"] == [
        "/Applications/Divoom.app/bin/divoomd", "--socket", DEFAULT_SOCKET_PATH]
    assert plist["EnvironmentVariables"]["DIVOOM_LINKS_RESTORE"] == "1"


def test_an_attached_daemon_is_still_forked(monkeypatch, run_dir):
    """Tests and the CLI spawn attached daemons they reap; those stay children."""
    monkeypatch.setattr(daemon_client.sys, "platform", "darwin")
    monkeypatch.setattr(daemon_client.binary_resolver, "resolve",
                        lambda name, override=None: "/x/divoomd")
    monkeypatch.setattr(daemon_client, "_spawn_disclaimed_macos", lambda *a, **kw: 9)
    monkeypatch.setenv("DIVOOM_DAEMON_LOG", str(run_dir / "d.log"))
    monkeypatch.setattr(launchd_job.subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("an attached daemon is not a launchd job")))
    assert daemon_client.spawn_daemon("/tmp/x.sock") == 9
