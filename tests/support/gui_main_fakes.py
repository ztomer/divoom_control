"""Boundary fakes for gui_main.main() (test_gui_main_main.py,
test_gui_main_startup_steps.py)."""

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
        self.before_show = _ClosingEvent()
        self.loaded = _ClosingEvent()


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
    monkeypatch.setattr(gui_main, "_spawn_menubar_agent", lambda resolve: None)
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
        window=window,
        api=fake_api,
        create_window_calls=create_window_calls,
        start_calls=start_calls,
        exits=exits,
        web_ui_dir=web_ui_dir,
    )
