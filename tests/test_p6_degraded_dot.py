"""BLE Hardening P6 (GUI) — the appbar dot reflects DEGRADED / a mid-session drop.

The daemon already exposes connection_state; here the GUI's Python API hands it
to the appbar and the JS heartbeat maps it to the dot. Python is unit-tested
with a fake daemon client; the JS wiring is asserted against the source.
"""
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

REPO = Path(__file__).parent.parent
# Connection-actions logic now lives in connection_events.js (extracted for the
# 500-LOC gate); tests that inspect the JS wiring must read both files.
_CONNECTION_JS = (REPO / "divoom_gui" / "web_ui" / "connection_events.js").read_text()
APP_GLOBALS = (REPO / "divoom_gui" / "web_ui" / "app_globals.js").read_text() + "\n" + _CONNECTION_JS
APP_INIT = (REPO / "divoom_gui" / "web_ui" / "app_init.js").read_text()
APPBAR_CSS = (REPO / "divoom_gui" / "web_ui" / "appbar.css").read_text()


# ── Python API: get_connection_state ───────────────────────────────────────

class _FakeClient:
    def __init__(self, status):
        self._status = status
    def device_status(self):
        return self._status


def _mixin(client):
    from divoom_gui.scanner_mixin import ScannerMixin
    m = ScannerMixin.__new__(ScannerMixin)
    m._client = lambda: client
    return m


def test_get_connection_state_passes_through_degraded():
    m = _mixin(_FakeClient({"connected": True, "connection_state": "degraded"}))
    out = json.loads(m.get_connection_state())
    assert out == {"connected": True, "state": "degraded"}


def test_get_connection_state_connected():
    m = _mixin(_FakeClient({"connected": True, "connection_state": "connected"}))
    out = json.loads(m.get_connection_state())
    assert out["connected"] is True and out["state"] == "connected"


def test_get_connection_state_no_daemon_is_disconnected():
    m = _mixin(None)
    out = json.loads(m.get_connection_state())
    assert out == {"connected": False, "state": "disconnected"}


def test_get_connection_state_swallows_errors():
    class _Boom:
        def device_status(self):
            raise RuntimeError("socket gone")
    out = json.loads(_mixin(_Boom()).get_connection_state())
    assert out == {"connected": False, "state": "disconnected"}


# ── JS wiring ───────────────────────────────────────────────────────────────

def test_js_connection_state_is_event_driven():
    # R59: the dot is driven by the daemon's pushed `status` events, not a poll.
    assert "window.Divoom.onDaemonEvent" in APP_GLOBALS
    assert "get_connection_state()" in APP_GLOBALS
    assert "window.refreshConnectionState" in APP_GLOBALS
    # The 4s polling heartbeat is gone — link health now arrives as events.
    assert "setInterval(window.refreshConnectionState" not in APP_GLOBALS


def test_js_degraded_sets_amber_dot_class():
    assert '"transport-dot active degraded"' in APP_GLOBALS


def test_js_disconnect_clears_appConnected():
    # a genuine drop must flip appConnected so the rest of the UI stops acting
    # connected.
    assert "window.DivoomState.appConnected = false" in APP_GLOBALS


def test_heartbeat_started_on_init():
    assert "startConnectionHeartbeat()" in APP_INIT


def test_css_has_degraded_rule():
    assert "#global-status-dot.degraded" in APPBAR_CSS
