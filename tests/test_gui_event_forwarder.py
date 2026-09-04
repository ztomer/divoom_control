"""Unit-test the GUI → web-UI event forwarder (R58/UI-reliability).

The daemon now broadcasts honest `status` events (connected + mac/lan_ip). The
GUI must forward them to the dashboard via `window.evaluate_js` so the UI
updates *live*, and must still follow the daemon down on shutdown. This test
pins that behavior without launching pywebview.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from divoom_gui.gui_main import _make_daemon_event_handler  # noqa: E402


class FakeWindow:
    def __init__(self):
        self.calls = []
        self.destroyed = False

    def evaluate_js(self, js: str) -> None:
        self.calls.append(js)

    def destroy(self) -> None:
        self.destroyed = True


def _forwarded_payload(window):
    """Return the parsed event object from the last evaluate_js call, or None."""
    import json
    for js in reversed(window.calls):
        marker = "window.Divoom.onDaemonEvent("
        i = js.find(marker)
        if i != -1:
            rest = js[i + len(marker):]
            json_str = rest.split(");", 1)[0]
            return json.loads(json_str)
    return None


def test_status_connected_forwarded_with_mac():
    w = FakeWindow()
    on_event = _make_daemon_event_handler(w)
    on_event({"type": "status", "state": "active", "connected": True,
              "mac": "MOCK_MAC", "counters": {}})
    assert w.calls, "no evaluate_js call for status event"
    ev = _forwarded_payload(w)
    assert ev["connected"] is True
    assert ev["mac"] == "MOCK_MAC"
    assert w.destroyed is False


def test_status_disconnected_forwarded():
    w = FakeWindow()
    on_event = _make_daemon_event_handler(w)
    on_event({"type": "status", "state": "idle", "connected": False, "counters": {}})
    ev = _forwarded_payload(w)
    assert ev["connected"] is False
    assert "mac" not in ev and "lan_ip" not in ev


def test_notification_forwarded():
    w = FakeWindow()
    on_event = _make_daemon_event_handler(w)
    on_event({"type": "notification", "title": "X", "body": "Y", "routed": True})
    assert w.calls, "notification event not forwarded"


def test_owned_devices_forwarded():
    w = FakeWindow()
    on_event = _make_daemon_event_handler(w)
    ev = {"type": "owned_devices", "devices": [{"address": "MOCK_MAC", "name": "", "kind": "idle", "state": "active"}]}
    on_event(ev)
    js = next((c for c in w.calls if "onOwnedDevices(" in c), None)
    assert js, "owned_devices event not forwarded to onOwnedDevices"
    assert '"address":"MOCK_MAC"' in js


def test_notif_status_forwarded():
    w = FakeWindow()
    on_event = _make_daemon_event_handler(w)
    ev = {"type": "notif_status", "state": "active", "counters": {"seen": 1, "routed": 1, "dropped": 0}}
    on_event(ev)
    js = next((c for c in w.calls if "onNotifStatus(" in c), None)
    assert js, "notif_status event not forwarded to onNotifStatus"


def test_hot_progress_forwarded():
    w = FakeWindow()
    on_event = _make_daemon_event_handler(w)
    on_event({"type": "hot_progress", "progress": 50, "phase": "uploading"})
    js = next((c for c in w.calls if "onHotProgress(" in c), None)
    assert js, "hot_progress event not forwarded to onHotProgress"


def test_shutdown_follows_when_lifecycle_says_yes():
    w = FakeWindow()
    on_event = _make_daemon_event_handler(w)
    with patch("divoom_lib.lifecycle_config.should_follow_daemon_shutdown",
               return_value=True), \
         patch("divoom_lib.lifecycle_config.get_keep_daemon_alive",
               return_value=False):
        on_event({"type": "shutdown"})
    assert w.destroyed is True
    assert w.calls == [], "shutdown must not be forwarded as JS"


def test_shutdown_ignored_when_lifecycle_says_no():
    w = FakeWindow()
    on_event = _make_daemon_event_handler(w)
    with patch("divoom_lib.lifecycle_config.should_follow_daemon_shutdown",
               return_value=False), \
         patch("divoom_lib.lifecycle_config.get_keep_daemon_alive",
               return_value=True):
        on_event({"type": "shutdown"})
    assert w.destroyed is False
