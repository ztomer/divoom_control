"""gui_main.main() optional startup steps: control server, unix control socket,
eager daemon spawn, permission priming, debug/tab args, the pywebview #1820
patch decision, and the non-darwin path (split from test_gui_main_main.py)."""

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


def test_main_control_server_env_enabled(monkeypatch, tmp_path):
    ctx = _patch_main_common(monkeypatch, tmp_path)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_keep_daemon_alive", lambda: True)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_quit_menubar_on_exit", lambda: True)
    monkeypatch.setenv("DIVOOM_CONTROL_SERVER", "1")
    monkeypatch.setenv("DIVOOM_CONTROL_PORT", "9999")

    import control_server

    calls = []
    monkeypatch.setattr(control_server, "serve_in_background", lambda api, port=8787: calls.append(port))

    with pytest.raises(SystemExit):
        gui_main.main()

    assert calls == [9999]


def test_main_control_server_failure_is_logged_not_fatal(monkeypatch, tmp_path):
    _patch_main_common(monkeypatch, tmp_path)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_keep_daemon_alive", lambda: True)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_quit_menubar_on_exit", lambda: True)
    monkeypatch.setenv("DIVOOM_CONTROL_SERVER", "yes")

    import control_server

    def raiser(api, port=8787):
        raise RuntimeError("port in use")

    monkeypatch.setattr(control_server, "serve_in_background", raiser)

    with pytest.raises(SystemExit):
        gui_main.main()  # must not propagate


def test_main_unix_control_socket_enabled(monkeypatch, tmp_path):
    _patch_main_common(monkeypatch, tmp_path)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_keep_daemon_alive", lambda: True)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_quit_menubar_on_exit", lambda: True)
    monkeypatch.setenv("DIVOOM_CONTROL_SOCKET", "/tmp/fake-divoom-test.sock")

    import control_server

    calls = []
    monkeypatch.setattr(control_server, "serve_unix_in_background", lambda api, path: calls.append(path))

    with pytest.raises(SystemExit):
        gui_main.main()

    assert calls == ["/tmp/fake-divoom-test.sock"]


def test_main_unix_control_socket_failure_is_logged_not_fatal(monkeypatch, tmp_path):
    _patch_main_common(monkeypatch, tmp_path)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_keep_daemon_alive", lambda: True)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_quit_menubar_on_exit", lambda: True)
    monkeypatch.setenv("DIVOOM_CONTROL_SOCKET", "/tmp/fake-divoom-test.sock")

    import control_server

    def raiser(api, path):
        raise OSError("bind failed")

    monkeypatch.setattr(control_server, "serve_unix_in_background", raiser)

    with pytest.raises(SystemExit):
        gui_main.main()  # must not propagate


def test_main_eager_daemon_spawn_returns_none_logs_warning(monkeypatch, tmp_path):
    ctx = _patch_main_common(monkeypatch, tmp_path)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_keep_daemon_alive", lambda: True)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_quit_menubar_on_exit", lambda: True)

    import divoom_gui.daemon_bridge as daemon_bridge

    monkeypatch.setattr(daemon_bridge, "ensure_daemon", lambda detach=True: None)

    with pytest.raises(SystemExit):
        gui_main.main()

    assert ctx.api._daemon_client is None


def test_main_eager_daemon_spawn_exception_is_caught(monkeypatch, tmp_path):
    _patch_main_common(monkeypatch, tmp_path)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_keep_daemon_alive", lambda: True)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_quit_menubar_on_exit", lambda: True)

    import divoom_gui.daemon_bridge as daemon_bridge

    def raiser(detach=True):
        raise RuntimeError("spawn failed")

    monkeypatch.setattr(daemon_bridge, "ensure_daemon", raiser)

    with pytest.raises(SystemExit):
        gui_main.main()  # must not propagate


def test_main_prime_permissions_exception_is_caught(monkeypatch, tmp_path):
    _patch_main_common(monkeypatch, tmp_path)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_keep_daemon_alive", lambda: True)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_quit_menubar_on_exit", lambda: True)

    import divoom_gui.permissions as permissions

    def raiser():
        raise RuntimeError("automation prompt failed")

    monkeypatch.setattr(permissions, "prime_permissions", raiser)

    with pytest.raises(SystemExit):
        gui_main.main()  # must not propagate


def test_main_debug_env_passed_to_webview_start(monkeypatch, tmp_path):
    ctx = _patch_main_common(monkeypatch, tmp_path)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_keep_daemon_alive", lambda: True)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_quit_menubar_on_exit", lambda: True)
    monkeypatch.setenv("DIVOOM_GUI_DEBUG", "true")

    with pytest.raises(SystemExit):
        gui_main.main()

    assert ctx.start_calls[0]["debug"] is True


def test_main_tab_and_card_args_build_query_string(monkeypatch, tmp_path):
    ctx = _patch_main_common(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["gui_main.py", "--tab", "data-sources", "--card", "notifications"])
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_keep_daemon_alive", lambda: True)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_quit_menubar_on_exit", lambda: True)

    with pytest.raises(SystemExit):
        gui_main.main()

    url = ctx.create_window_calls[0]["url"]
    assert "tab=data-sources" in url
    assert "card=notifications" in url


def test_main_applies_1820_patch_when_bug_present(monkeypatch, tmp_path):
    """When `_pywebview_1820_bug_present()` says the bug is present, main()
    monkeypatches the real cocoa `BrowserView.move` — that's a genuine mutation
    of process-global third-party state, so we save/restore it around the
    assertion rather than mocking `_pywebview_1820_bug_present` to False like
    the other main() tests do."""
    from webview.platforms.cocoa import BrowserView

    original_move = BrowserView.move

    ctx = _patch_main_common(monkeypatch, tmp_path)
    monkeypatch.setattr(gui_main, "_pywebview_1820_bug_present", lambda: True)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_keep_daemon_alive", lambda: True)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_quit_menubar_on_exit", lambda: True)

    try:
        with pytest.raises(SystemExit):
            gui_main.main()

        assert BrowserView.move is not original_move

        class FakeScreen:
            size = types.SimpleNamespace(height=1000)
            origin = types.SimpleNamespace(x=50, y=20)

        class FakeNSWindow:
            def __init__(self):
                self.point = None

            def setFrameTopLeftPoint_(self, point):
                self.point = point

        class FakeSelf:
            screen = FakeScreen()
            window = FakeNSWindow()

        fs = FakeSelf()
        BrowserView.move(fs, 100, 300)
        # flipped_y = 1000 - 300 = 700; the patch drops screen.origin.x, so
        # NSPoint is (x, origin.y + flipped_y) = (100, 20 + 700).
        assert fs.window.point.x == 100
        assert fs.window.point.y == 720
    finally:
        BrowserView.move = original_move


def test_main_1820_patch_check_import_error_is_caught(monkeypatch, tmp_path):
    _patch_main_common(monkeypatch, tmp_path)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_keep_daemon_alive", lambda: True)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_quit_menubar_on_exit", lambda: True)

    import builtins

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in ("webview.platforms.cocoa", "AppKit"):
            raise ImportError("no AppKit on this platform")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(SystemExit):
        gui_main.main()  # the ImportError must not propagate


def test_main_non_darwin_skips_single_instance_and_menubar_patch(monkeypatch, tmp_path):
    """On non-macOS platforms the single-instance gate, the eager daemon spawn,
    and the #1820 cocoa patch are all skipped by their `sys.platform ==
    "darwin"` guards — main() still builds and shows the window."""
    ctx = _patch_main_common(monkeypatch, tmp_path)
    monkeypatch.setattr(gui_main.sys, "platform", "linux")
    monkeypatch.setattr(
        gui_main,
        "_ensure_single_instance",
        lambda: (_ for _ in ()).throw(AssertionError("must not be called on non-darwin")),
    )

    with pytest.raises(SystemExit):
        gui_main.main()

    assert ctx.create_window_calls, "window must still be created on non-darwin"
    assert ctx.api._daemon_client is None, "eager daemon spawn is darwin-only"
