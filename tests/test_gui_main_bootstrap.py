"""Coverage for the testable logic in divoom_gui/gui_main.py.

Split from test_gui_event_forwarder.py (which already covers
`_make_daemon_event_handler`) and test_menubar.py (which already covers the
`_spawn_menubar_agent` dupe-guard happy path). This file covers:

  - the pure helper functions (`_pywebview_1820_bug_present`, `_resolve_web_ui`,
    `_resolve_bundled_binary`, `_resolve_menubar_binary`, `_ensure_single_instance`)
  - the remaining `_spawn_menubar_agent` / `_terminate_menubar_agent` branches
  - `main()`'s bootstrap/decision logic (single-instance gate, optional control
    servers, eager daemon spawn, permission priming, the daemon-shutdown-once
    guard, url/query construction) with `webview`/`DivoomGuiAPI`/daemon/menubar
    calls mocked out.

What's deliberately NOT covered here (left to real app / user-POV verification,
per docs/PLANNING_ROUND61.md item 1): the actual `webview.create_window(...)`
window it produces, `webview.start()`'s real GTK/Cocoa event loop, and the
`__main__` entrypoint — those are platform GUI mainloop plumbing, not logic.
"""
from __future__ import annotations

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


# ───────────────────────── module-level locale bootstrap ────────────────────
# gui_main.py's very first lines (before any other import) try
# `en_US.UTF-8` then `C.UTF-8` via `locale.setlocale`, swallowing failures —
# a py2app-bundled interpreter starts with no locale applied. That loop runs
# once, at import time, before any fixture can intervene, so the only way to
# exercise the "every candidate fails" branch is a fresh interpreter with
# `locale.setlocale` forced to fail *before* `divoom_gui.gui_main` is
# imported. A subprocess gives us that clean slate without mutating the
# current process's locale or reloading a module already used by other tests.

def test_locale_bootstrap_swallows_setlocale_failures_for_all_candidates():
    script = (
        "import locale, sys\n"
        "def _boom(*a, **kw):\n"
        "    raise locale.Error('no locale available')\n"
        "locale.setlocale = _boom\n"
        "sys.path.insert(0, %r)\n"
        "import divoom_gui.gui_main as gm\n"
        "print('IMPORTED_OK', gm.logger.name)\n"
    ) % str(_REPO)

    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(_REPO), capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "IMPORTED_OK divoom_gui" in proc.stdout


# ─────────────────────────── _pywebview_1820_bug_present ────────────────────

def test_bug_present_detects_token(monkeypatch):
    def fake_getsource(fn):
        return "AppKit.NSPoint(self.screen.origin.x + x, self.screen.origin.y + flipped_y)"

    # The function imports `inspect` locally; patch the real (shared) module.
    import inspect as real_inspect
    monkeypatch.setattr(real_inspect, "getsource", fake_getsource)
    assert gui_main._pywebview_1820_bug_present() is True


def test_bug_present_false_when_fixed(monkeypatch):
    import inspect as real_inspect
    monkeypatch.setattr(real_inspect, "getsource", lambda fn: "NSPoint(x, self.screen.origin.y + flipped_y)")
    assert gui_main._pywebview_1820_bug_present() is False


def test_bug_present_false_on_import_error(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "webview.platforms.cocoa":
            raise ImportError("no cocoa backend")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert gui_main._pywebview_1820_bug_present() is False


def test_bug_present_false_on_getsource_oserror(monkeypatch):
    import inspect as real_inspect

    def raiser(fn):
        raise OSError("no source available")

    monkeypatch.setattr(real_inspect, "getsource", raiser)
    assert gui_main._pywebview_1820_bug_present() is False


# ─────────────────────────────── _resolve_web_ui ─────────────────────────────

def test_resolve_web_ui_finds_dev_tree_index(tmp_path, monkeypatch):
    fake_module_file = tmp_path / "src" / "gui_main.py"
    (tmp_path / "src" / "web_ui").mkdir(parents=True)
    (tmp_path / "src" / "web_ui" / "index.html").write_text("<html></html>")
    monkeypatch.setattr(gui_main, "__file__", str(fake_module_file))
    monkeypatch.delattr(gui_main.sys, "_MEIPASS", raising=False)

    result = gui_main._resolve_web_ui()
    assert result == tmp_path / "src" / "web_ui"


def test_resolve_web_ui_falls_back_to_meipass_divoom_gui(tmp_path, monkeypatch):
    fake_module_file = tmp_path / "src" / "gui_main.py"
    (tmp_path / "src").mkdir(parents=True)  # no web_ui next to the module
    mei = tmp_path / "bundle" / "frameworks"
    (mei / "divoom_gui" / "web_ui").mkdir(parents=True)
    (mei / "divoom_gui" / "web_ui" / "index.html").write_text("<html></html>")
    monkeypatch.setattr(gui_main, "__file__", str(fake_module_file))
    monkeypatch.setattr(gui_main.sys, "_MEIPASS", str(mei), raising=False)

    result = gui_main._resolve_web_ui()
    assert result == mei / "divoom_gui" / "web_ui"


def test_resolve_web_ui_falls_back_to_resources_parent(tmp_path, monkeypatch):
    fake_module_file = tmp_path / "src" / "gui_main.py"
    (tmp_path / "src").mkdir(parents=True)
    mei = tmp_path / "bundle" / "Contents" / "Frameworks"
    resources = tmp_path / "bundle" / "Contents" / "Resources" / "divoom_gui" / "web_ui"
    resources.mkdir(parents=True)
    (resources / "index.html").write_text("<html></html>")
    monkeypatch.setattr(gui_main, "__file__", str(fake_module_file))
    monkeypatch.setattr(gui_main.sys, "_MEIPASS", str(mei), raising=False)

    result = gui_main._resolve_web_ui()
    assert result == resources


def test_resolve_web_ui_no_candidate_found_returns_first(tmp_path, monkeypatch):
    fake_module_file = tmp_path / "src" / "gui_main.py"
    (tmp_path / "src").mkdir(parents=True)
    monkeypatch.setattr(gui_main, "__file__", str(fake_module_file))
    monkeypatch.delattr(gui_main.sys, "_MEIPASS", raising=False)

    result = gui_main._resolve_web_ui()
    assert result == tmp_path / "src" / "web_ui"


# ───────────────────────────── _resolve_bundled_binary ───────────────────────

def test_resolve_bundled_binary_env_override(tmp_path, monkeypatch):
    binary = tmp_path / "divoomd"
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setenv("DIVOOM_RUST_BINARY", str(binary))
    assert gui_main._resolve_bundled_binary("divoomd") == str(binary)


def test_resolve_bundled_binary_env_override_menubar(tmp_path, monkeypatch):
    binary = tmp_path / "divoom-menubar"
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setenv("DIVOOM_MENUBAR_BINARY", str(binary))
    assert gui_main._resolve_bundled_binary("divoom-menubar") == str(binary)


def test_resolve_bundled_binary_meipass_bin_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("DIVOOM_RUST_BINARY", raising=False)
    mei = tmp_path / "mei"
    (mei / "bin").mkdir(parents=True)
    binary = mei / "bin" / "divoomd"
    binary.write_text("x")
    monkeypatch.setattr(gui_main.sys, "_MEIPASS", str(mei), raising=False)
    assert gui_main._resolve_bundled_binary("divoomd") == str(binary)


def test_resolve_bundled_binary_resourcepath(tmp_path, monkeypatch):
    monkeypatch.delenv("DIVOOM_RUST_BINARY", raising=False)
    monkeypatch.delattr(gui_main.sys, "_MEIPASS", raising=False)
    rp = tmp_path / "Resources"
    rp.mkdir()
    binary = rp / "divoomd"
    binary.write_text("x")
    monkeypatch.setenv("RESOURCEPATH", str(rp))
    assert gui_main._resolve_bundled_binary("divoomd") == str(binary)


def test_resolve_bundled_binary_meipass_second_candidate(tmp_path, monkeypatch):
    """First MEIPASS candidate (bin/<name>) is absent; the loop must continue
    to the second (<mei>/<name>) rather than stopping at the first miss."""
    monkeypatch.delenv("DIVOOM_RUST_BINARY", raising=False)
    mei = tmp_path / "mei"
    mei.mkdir(parents=True)
    binary = mei / "divoomd"
    binary.write_text("x")
    monkeypatch.setattr(gui_main.sys, "_MEIPASS", str(mei), raising=False)
    assert gui_main._resolve_bundled_binary("divoomd") == str(binary)


def test_resolve_bundled_binary_meipass_no_candidate_falls_through(tmp_path, monkeypatch):
    """None of the three MEIPASS-relative candidates exist -> the loop runs to
    completion and falls through to the RESOURCEPATH/None checks below it."""
    monkeypatch.delenv("DIVOOM_RUST_BINARY", raising=False)
    monkeypatch.delenv("RESOURCEPATH", raising=False)
    mei = tmp_path / "mei-empty"
    mei.mkdir(parents=True)
    monkeypatch.setattr(gui_main.sys, "_MEIPASS", str(mei), raising=False)
    assert gui_main._resolve_bundled_binary("divoomd") is None


def test_resolve_bundled_binary_none_found(tmp_path, monkeypatch):
    monkeypatch.delenv("DIVOOM_RUST_BINARY", raising=False)
    monkeypatch.delenv("RESOURCEPATH", raising=False)
    monkeypatch.delattr(gui_main.sys, "_MEIPASS", raising=False)
    assert gui_main._resolve_bundled_binary("divoomd") is None


# ───────────────────────────── _ensure_single_instance ───────────────────────

def test_ensure_single_instance_acquires_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(gui_main, "_GUI_LOCK_FH", None)
    # `_ensure_single_instance` imports `tempfile` locally; patch the shared module.
    import tempfile as real_tempfile
    monkeypatch.setattr(real_tempfile, "gettempdir", lambda: str(tmp_path))

    assert gui_main._ensure_single_instance() is True
    assert gui_main._GUI_LOCK_FH is not None


def test_ensure_single_instance_false_when_locked(tmp_path, monkeypatch):
    monkeypatch.setattr(gui_main, "_GUI_LOCK_FH", None)
    import fcntl as real_fcntl

    def raiser(fd, flags):
        raise BlockingIOError("already locked")

    monkeypatch.setattr(real_fcntl, "flock", raiser)
    assert gui_main._ensure_single_instance() is False


# ─────────────────────────────── _resolve_menubar_binary ─────────────────────

def test_resolve_menubar_binary_uses_bundled(monkeypatch):
    monkeypatch.setattr(gui_main, "_resolve_bundled_binary", lambda name: "/bundled/divoom-menubar")
    assert gui_main._resolve_menubar_binary() == "/bundled/divoom-menubar"


def test_resolve_menubar_binary_dev_tree_release(monkeypatch, tmp_path):
    monkeypatch.setattr(gui_main, "_resolve_bundled_binary", lambda name: None)
    # `_resolve_menubar_binary` computes `repo_root = Path(__file__).resolve().parents[1]`
    # — fake `__file__` two levels under a controlled repo_root instead of touching
    # the real Path.resolve (which is process-global and used everywhere).
    repo_root = tmp_path
    fake_module_file = repo_root / "divoom_gui" / "gui_main.py"
    monkeypatch.setattr(gui_main, "__file__", str(fake_module_file))
    target = repo_root / "target" / "release"
    target.mkdir(parents=True)
    (target / "divoom-menubar").write_text("x")

    assert gui_main._resolve_menubar_binary() == str(target / "divoom-menubar")


def test_resolve_menubar_binary_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr(gui_main, "_resolve_bundled_binary", lambda name: None)
    repo_root = tmp_path
    fake_module_file = repo_root / "divoom_gui" / "gui_main.py"
    monkeypatch.setattr(gui_main, "__file__", str(fake_module_file))

    assert gui_main._resolve_menubar_binary() is None


# ─────────────────────────────── _spawn_menubar_agent ────────────────────────

def test_spawn_menubar_agent_noop_on_non_darwin(monkeypatch):
    monkeypatch.setattr(gui_main.sys, "platform", "linux")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not run")))
    gui_main._spawn_menubar_agent()  # must return immediately, no assertion raised


def test_spawn_menubar_agent_already_running_skips_spawn(monkeypatch):
    monkeypatch.setattr(gui_main.sys, "platform", "darwin")

    class _Match:
        returncode = 0
        stdout = "1234\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _Match())
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not spawn")))
    gui_main._spawn_menubar_agent()  # no assertion raised => Popen never called


def test_spawn_menubar_agent_binary_not_found_warns(monkeypatch):
    monkeypatch.setattr(gui_main.sys, "platform", "darwin")

    class _NoMatch:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _NoMatch())
    monkeypatch.setattr(gui_main, "_resolve_menubar_binary", lambda: None)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not spawn")))
    gui_main._spawn_menubar_agent()  # no assertion raised => Popen never called


def test_spawn_menubar_agent_frozen_uses_executable(monkeypatch):
    monkeypatch.setattr(gui_main.sys, "platform", "darwin")
    monkeypatch.setattr(gui_main.sys, "frozen", True, raising=False)

    class _NoMatch:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _NoMatch())
    monkeypatch.setattr(gui_main, "_resolve_menubar_binary", lambda: "/bin/divoom-menubar")
    seen = {}

    def fake_popen(args, env=None, **kw):
        seen["args"] = args
        seen["env"] = env
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    gui_main._spawn_menubar_agent()

    assert seen["env"]["DIVOOM_GUI_PYTHON"] == sys.executable
    assert seen["env"]["DIVOOM_GUI_SCRIPT"] == ""


def test_spawn_menubar_agent_swallows_exceptions(monkeypatch):
    monkeypatch.setattr(gui_main.sys, "platform", "darwin")

    def raiser(*a, **kw):
        raise OSError("pgrep missing")

    monkeypatch.setattr(subprocess, "run", raiser)
    gui_main._spawn_menubar_agent()  # must not raise


# ────────────────────────────── _terminate_menubar_agent ─────────────────────

def test_terminate_menubar_agent_noop_on_non_darwin(monkeypatch):
    monkeypatch.setattr(gui_main.sys, "platform", "linux")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not run")))
    gui_main._terminate_menubar_agent()


def test_terminate_menubar_agent_calls_pkill(monkeypatch):
    monkeypatch.setattr(gui_main.sys, "platform", "darwin")
    seen = {}

    def fake_run(args, **kw):
        seen["args"] = args
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    gui_main._terminate_menubar_agent()
    assert seen["args"] == ["pkill", "-f", "divoom-menubar"]


def test_terminate_menubar_agent_swallows_exceptions(monkeypatch):
    monkeypatch.setattr(gui_main.sys, "platform", "darwin")

    def raiser(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="pkill", timeout=3)

    monkeypatch.setattr(subprocess, "run", raiser)
    gui_main._terminate_menubar_agent()  # must not raise


# ─────────────────────────── _make_daemon_event_handler ──────────────────────
# (the happy-path event types are already covered by test_gui_event_forwarder.py;
# these fill in the remaining defensive branches.)

class _FakeWindow:
    def __init__(self, destroy_raises=False, evaluate_js_raises=False):
        self.calls = []
        self.destroyed = False
        self._destroy_raises = destroy_raises
        self._evaluate_js_raises = evaluate_js_raises

    def evaluate_js(self, js):
        self.calls.append(js)
        if self._evaluate_js_raises:
            raise RuntimeError("evaluate_js boom")

    def destroy(self):
        self.destroyed = True
        if self._destroy_raises:
            raise RuntimeError("destroy boom")


def test_event_handler_ignores_non_dict_payload():
    w = _FakeWindow()
    on_event = gui_main._make_daemon_event_handler(w)
    on_event(None)
    on_event("garbage")
    assert w.calls == []
    assert w.destroyed is False


def test_event_handler_unknown_event_type_is_ignored():
    w = _FakeWindow()
    on_event = gui_main._make_daemon_event_handler(w)
    on_event({"type": "something_unhandled"})
    assert w.calls == []


def test_event_handler_shutdown_lifecycle_import_failure_returns(monkeypatch):
    import divoom_lib.lifecycle_config as lifecycle_config
    monkeypatch.delattr(lifecycle_config, "get_keep_daemon_alive")
    w = _FakeWindow()
    on_event = gui_main._make_daemon_event_handler(w)
    on_event({"type": "shutdown"})  # import inside the handler raises -> caught, return
    assert w.destroyed is False


def test_event_handler_shutdown_destroy_exception_is_swallowed(monkeypatch):
    monkeypatch.setattr("divoom_lib.lifecycle_config.should_follow_daemon_shutdown",
                         lambda keep_alive: True)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_keep_daemon_alive",
                         lambda: False)
    w = _FakeWindow(destroy_raises=True)
    on_event = gui_main._make_daemon_event_handler(w)
    on_event({"type": "shutdown"})  # destroy() raises -> caught
    assert w.destroyed is True


def test_event_handler_evaluate_js_exception_is_swallowed():
    w = _FakeWindow(evaluate_js_raises=True)
    on_event = gui_main._make_daemon_event_handler(w)
    on_event({"type": "status", "connected": True})  # evaluate_js raises -> caught
    assert w.calls  # it was still attempted


# ─────────────────────────────── _start_shutdown_follower ────────────────────

def test_start_shutdown_follower_notifies_ondaemondown_and_backs_off(monkeypatch):
    """The follower subscribes on a daemon thread; when subscribe() returns/raises
    (daemon down), it tells the UI via onDaemonDown then backs off with
    time.sleep() before retrying. We let it run exactly one iteration by having
    the injected sleep raise, which unwinds the (otherwise infinite) `while True`
    inside the background thread."""
    w = _FakeWindow()

    class _StopLoop(BaseException):
        pass

    class FakeDaemonClient:
        def __init__(self, *a, **kw):
            pass

        def subscribe(self, handler):
            raise RuntimeError("daemon socket closed")

    sleep_calls = []

    def fake_sleep(secs):
        sleep_calls.append(secs)
        raise _StopLoop()

    monkeypatch.setattr("divoom_daemon.daemon_protocol.DaemonClient", FakeDaemonClient)
    monkeypatch.setattr("time.sleep", fake_sleep)

    # Suppress the default thread-exception traceback dump: _StopLoop escaping
    # the background thread is expected (that's how the test bounds the loop),
    # not a real failure.
    old_hook = threading.excepthook
    threading.excepthook = lambda args: None
    try:
        gui_main._start_shutdown_follower(w)
        # the thread is created inside the function; find and join it
        for t in threading.enumerate():
            if t.name == "daemon-event-follower":
                t.join(timeout=2)
                break
    finally:
        threading.excepthook = old_hook

    assert sleep_calls == [2.0]
    assert any("onDaemonDown" in c for c in w.calls)


def test_start_shutdown_follower_swallows_evaluate_js_failure(monkeypatch):
    """window.evaluate_js(onDaemonDown) raising must not crash the follower
    thread (it's wrapped in its own try/except inside the `finally` block)."""
    w = _FakeWindow(evaluate_js_raises=True)

    class _StopLoop(BaseException):
        pass

    class FakeDaemonClient:
        def __init__(self, *a, **kw):
            pass

        def subscribe(self, handler):
            raise RuntimeError("daemon socket closed")

    def fake_sleep(secs):
        raise _StopLoop()

    monkeypatch.setattr("divoom_daemon.daemon_protocol.DaemonClient", FakeDaemonClient)
    monkeypatch.setattr("time.sleep", fake_sleep)

    old_hook = threading.excepthook
    threading.excepthook = lambda args: None
    try:
        gui_main._start_shutdown_follower(w)
        for t in threading.enumerate():
            if t.name == "daemon-event-follower":
                t.join(timeout=2)
                break
    finally:
        threading.excepthook = old_hook

    assert w.calls  # evaluate_js was attempted despite raising


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

    monkeypatch.setattr("divoom_daemon.daemon_protocol.DaemonClient", FakeDaemonClient)
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

    monkeypatch.setattr("divoom_daemon.daemon_protocol.DaemonClient", FakeDaemonClient)
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

    monkeypatch.setattr("divoom_daemon.daemon_protocol.DaemonClient", FakeDaemonClient)
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
