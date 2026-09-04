"""gui_main.main() lifecycle coverage (split from
test_gui_main_bootstrap.py)."""

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



# ────────────────────────────────────── main() ────────────────────────────────
# main() is the real bootstrap: argument parsing, the single-instance gate,
# optional control-server surfaces, the eager daemon spawn, permission
# priming, the pywebview #1820 patch decision, and the daemon-shutdown-once
# guard around `webview.start()`. All of that is decision LOGIC we can and
# should unit-test by mocking the boundary (`webview`, `DivoomGuiAPI`,
# daemon/menubar/permissions helpers, `os._exit`). The genuinely untestable
# part — `webview.create_window`/`webview.start` actually driving a real
# Cocoa/GTK window — is exactly what we mock away here; that real mainloop is
# left to user-POV / real-app verification, not a unit test.

class _ClosingEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, fn):
        self.handlers.append(fn)
        return self


class _FakeMainEvents:
    def __init__(self):
        self.closing = _ClosingEvent()


class _FakeMainWindow:
    def __init__(self):
        self.events = _FakeMainEvents()
        self.destroyed = False
        self.js_calls = []

    def evaluate_js(self, js):
        self.js_calls.append(js)

    def destroy(self):
        self.destroyed = True


def _patch_main_common(monkeypatch, tmp_path, *, fire_closing=True):
    """Wire up the standard set of main() boundary mocks; individual tests
    layer additional monkeypatches (lifecycle config, DaemonClient, env vars)
    on top. Returns a namespace of captured call sites for assertions."""
    monkeypatch.setattr(gui_main.sys, "platform", "darwin")
    monkeypatch.setattr(sys, "argv", ["gui_main.py"])
    monkeypatch.setattr(gui_main, "_ensure_single_instance", lambda: True)

    web_ui_dir = tmp_path / "web_ui"
    web_ui_dir.mkdir()
    (web_ui_dir / "index.html").write_text("<html></html>")
    monkeypatch.setattr(gui_main, "_resolve_web_ui", lambda: web_ui_dir)

    fake_api = types.SimpleNamespace(window=None, _daemon_client=None)
    monkeypatch.setattr(gui_main, "DivoomGuiAPI", lambda: fake_api)

    window = _FakeMainWindow()
    create_window_calls = []

    def fake_create_window(**kwargs):
        create_window_calls.append(kwargs)
        return window

    monkeypatch.setattr(gui_main.webview, "create_window", fake_create_window)

    start_calls = []

    def fake_start(**kwargs):
        start_calls.append(kwargs)
        if fire_closing:
            # Simulate pywebview invoking the registered `closing` handler(s)
            # as the (real, blocking) window actually closes, before
            # webview.start() "returns".
            for h in list(window.events.closing.handlers):
                h()

    monkeypatch.setattr(gui_main.webview, "start", fake_start)

    # Skip the real BrowserView.move monkeypatch branch (it mutates the real,
    # process-global pywebview class) — that decision itself is covered by the
    # dedicated _pywebview_1820_bug_present tests above.
    monkeypatch.setattr(gui_main, "_pywebview_1820_bug_present", lambda: False)
    monkeypatch.setattr(gui_main, "_spawn_menubar_agent", lambda: None)
    monkeypatch.setattr(gui_main, "_start_shutdown_follower", lambda w: None)

    import divoom_gui.daemon_bridge as daemon_bridge
    monkeypatch.setattr(daemon_bridge, "ensure_daemon", lambda detach=True: object())

    import divoom_gui.permissions as permissions
    monkeypatch.setattr(permissions, "prime_permissions", lambda: None)

    exits = []

    def fake_exit(code):
        exits.append(code)
        raise SystemExit(code)

    monkeypatch.setattr(gui_main.os, "_exit", fake_exit)

    return types.SimpleNamespace(
        window=window, api=fake_api,
        create_window_calls=create_window_calls, start_calls=start_calls,
        exits=exits, web_ui_dir=web_ui_dir,
    )


def test_main_darwin_already_running_returns_early(monkeypatch):
    monkeypatch.setattr(gui_main.sys, "platform", "darwin")
    monkeypatch.setattr(sys, "argv", ["gui_main.py"])
    monkeypatch.setattr(gui_main, "_ensure_single_instance", lambda: False)
    osascript_calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: osascript_calls.append(a) or types.SimpleNamespace())
    monkeypatch.setattr(gui_main.webview, "create_window",
                         lambda **kw: (_ for _ in ()).throw(AssertionError("must not create a window")))

    result = gui_main.main()

    assert result is None
    assert osascript_calls, "expected the 'focus existing instance' osascript call"


def test_main_darwin_already_running_swallows_osascript_failure(monkeypatch):
    monkeypatch.setattr(gui_main.sys, "platform", "darwin")
    monkeypatch.setattr(sys, "argv", ["gui_main.py"])
    monkeypatch.setattr(gui_main, "_ensure_single_instance", lambda: False)
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


def test_main_control_server_env_enabled(monkeypatch, tmp_path):
    ctx = _patch_main_common(monkeypatch, tmp_path)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_keep_daemon_alive", lambda: True)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_quit_menubar_on_exit", lambda: True)
    monkeypatch.setenv("DIVOOM_CONTROL_SERVER", "1")
    monkeypatch.setenv("DIVOOM_CONTROL_PORT", "9999")

    import control_server
    calls = []
    monkeypatch.setattr(control_server, "serve_in_background",
                         lambda api, port=8787: calls.append(port))

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
    monkeypatch.setattr(control_server, "serve_unix_in_background",
                         lambda api, path: calls.append(path))

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
    monkeypatch.setattr(gui_main, "_ensure_single_instance",
                         lambda: (_ for _ in ()).throw(AssertionError("must not be called on non-darwin")))

    with pytest.raises(SystemExit):
        gui_main.main()

    assert ctx.create_window_calls, "window must still be created on non-darwin"
    assert ctx.api._daemon_client is None, "eager daemon spawn is darwin-only"
