"""gui_main._make_daemon_event_handler + _start_shutdown_follower coverage
(split from test_gui_main_bootstrap.py)."""

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

    monkeypatch.setattr("divoom_client.daemon_protocol.DaemonClient", FakeDaemonClient)
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

    monkeypatch.setattr("divoom_client.daemon_protocol.DaemonClient", FakeDaemonClient)
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
