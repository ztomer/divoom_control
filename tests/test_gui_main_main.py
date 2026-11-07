"""gui_main.main() lifecycle coverage: the single-instance gate and the
daemon-shutdown-once guard (split from test_gui_main_bootstrap.py; the optional
startup steps are in test_gui_main_startup_steps.py)."""

import re
import subprocess
import sys
import threading
import types
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from divoom_gui import gui_main  # noqa: E402
from tests.support.gui_main_fakes import _patch_main_common


def test_main_darwin_already_running_focuses_the_incumbent_by_pid(monkeypatch):
    """The focus path must address the incumbent by the pid in the lock file.

    It used to run `tell application "Python" to activate`, which asked
    LaunchServices to resolve the NAME "Python" and LAUNCH whatever answered:
    on 2026-09-07 that was TeX Live Utility's embedded Python 3.9.10 bundle,
    app-translocated into $TMPDIR and SIGABRTing in dyld. Four crash reports,
    and the window it meant to focus never moved. Pinned at the script level
    because the app-name form is the whole defect.
    """
    monkeypatch.setattr(gui_main.sys, "platform", "darwin")
    monkeypatch.setattr(sys, "argv", ["gui_main.py"])
    monkeypatch.setattr(gui_main, "_ensure_single_instance", lambda: False)
    monkeypatch.setattr(gui_main, "_running_gui_pid", lambda: 4242)
    osascript_calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: osascript_calls.append(a) or types.SimpleNamespace())
    monkeypatch.setattr(
        gui_main.webview,
        "create_window",
        lambda **kw: (_ for _ in ()).throw(AssertionError("must not create a window")),
    )

    result = gui_main.main()

    assert result is None
    assert osascript_calls, "expected the 'focus existing instance' osascript call"
    script = osascript_calls[0][0][2]
    assert "unix id is 4242" in script
    assert "System Events" in script
    # Pinned as the CLASS, not as the one name that bit us: no application may
    # be addressed by name except the faceless System Events bridge, because a
    # name is resolved by LaunchServices and can start an arbitrary bundle.
    assert not re.search(r'application\s+(?:id\s+)?"(?!System Events")', script), script


def test_main_darwin_already_running_without_a_pid_launches_nothing(monkeypatch):
    """No pid recorded -> do nothing. There is no safe name-based fallback."""
    monkeypatch.setattr(gui_main.sys, "platform", "darwin")
    monkeypatch.setattr(sys, "argv", ["gui_main.py"])
    monkeypatch.setattr(gui_main, "_ensure_single_instance", lambda: False)
    monkeypatch.setattr(gui_main, "_running_gui_pid", lambda: None)
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("must not shell out without a pid"))

    assert gui_main.main() is None


def test_main_darwin_already_running_swallows_osascript_failure(monkeypatch):
    monkeypatch.setattr(gui_main.sys, "platform", "darwin")
    monkeypatch.setattr(sys, "argv", ["gui_main.py"])
    monkeypatch.setattr(gui_main, "_ensure_single_instance", lambda: False)
    monkeypatch.setattr(gui_main, "_running_gui_pid", lambda: 4242)
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(OSError("no osascript")))

    assert gui_main.main() is None  # must not raise


def test_main_happy_path_darwin_shared_lifecycle(monkeypatch, tmp_path):
    """Shared lifecycle (keep_alive=False): closing the window stops the daemon
    and terminates the menubar agent exactly once, even though `main()` fires
    the closing handler AND then unconditionally calls `_stop_daemon_once`
    again after `webview.start()` returns (the R52 idempotency guard)."""
    ctx = _patch_main_common(monkeypatch, tmp_path)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_keep_daemon_alive", lambda: False)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_quit_menubar_on_exit", lambda: True)

    shutdown_calls = []

    class FakeDaemonClient:
        def __init__(self, *a, **kw):
            pass

        def shutdown(self):
            shutdown_calls.append(True)

    monkeypatch.setattr("divoom_client.daemon_protocol.DaemonClient", FakeDaemonClient)
    terminate_calls = []
    monkeypatch.setattr(gui_main, "_terminate_menubar_agent", lambda: terminate_calls.append(True))

    with pytest.raises(SystemExit) as ei:
        gui_main.main()

    assert ei.value.code == 0
    assert ctx.exits == [0]
    assert ctx.create_window_calls[0]["title"] == "Divoom Control Center"
    assert ctx.api.window is ctx.window
    assert len(ctx.window.events.closing.handlers) == 1
    assert shutdown_calls == [True], "daemon shutdown must fire exactly once"
    assert terminate_calls == [True], "menubar terminate must fire exactly once"


def test_main_keep_alive_skips_daemon_stop_and_menubar_terminate(monkeypatch, tmp_path):
    ctx = _patch_main_common(monkeypatch, tmp_path)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_keep_daemon_alive", lambda: True)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_quit_menubar_on_exit", lambda: True)

    shutdown_calls = []

    class FakeDaemonClient:
        def __init__(self, *a, **kw):
            pass

        def shutdown(self):
            shutdown_calls.append(True)

    monkeypatch.setattr("divoom_client.daemon_protocol.DaemonClient", FakeDaemonClient)
    terminate_calls = []
    monkeypatch.setattr(gui_main, "_terminate_menubar_agent", lambda: terminate_calls.append(True))

    with pytest.raises(SystemExit):
        gui_main.main()

    assert shutdown_calls == [], "keep-alive: daemon must not be stopped"
    assert terminate_calls == [], "keep-alive: menubar must not be terminated"


def test_main_stop_daemon_once_swallows_lifecycle_errors(monkeypatch, tmp_path):
    _patch_main_common(monkeypatch, tmp_path)

    def raiser():
        raise RuntimeError("config read boom")

    monkeypatch.setattr("divoom_lib.lifecycle_config.get_keep_daemon_alive", raiser)

    with pytest.raises(SystemExit):
        gui_main.main()  # the lifecycle-config error must not propagate


def test_main_no_closing_event_still_stops_daemon_once_after_start(monkeypatch, tmp_path):
    """If pywebview never fires `closing` (e.g. killed some other way),
    `_stop_daemon_once("Dashboard closed")` after webview.start() still runs."""
    ctx = _patch_main_common(monkeypatch, tmp_path, fire_closing=False)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_keep_daemon_alive", lambda: False)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_quit_menubar_on_exit", lambda: True)

    shutdown_calls = []

    class FakeDaemonClient:
        def __init__(self, *a, **kw):
            pass

        def shutdown(self):
            shutdown_calls.append(True)

    monkeypatch.setattr("divoom_client.daemon_protocol.DaemonClient", FakeDaemonClient)
    monkeypatch.setattr(gui_main, "_terminate_menubar_agent", lambda: None)

    with pytest.raises(SystemExit):
        gui_main.main()

    assert shutdown_calls == [True]
