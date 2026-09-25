"""G0 bridge-IDL freeze: the JS<->Python seam is versioned and drift fails.

`divoom_gui/bridge_idl.json` (version 1) pins the exact public bridge surface:
every invokable method on DivoomGuiAPI (minus the window-only denylist), the
7 daemon push events and their window.Divoom handlers, and the 2 lifecycle
edges. Any new bridge method or event must bump the IDL in the same commit —
a green suite with a stale IDL is the failure this gate exists to prevent.
"""

import json
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / "divoom_gui"))

REPO = Path(__file__).parent.parent
IDL_PATH = REPO / "divoom_gui" / "bridge_idl.json"

EXPECTED_PUSH = {
    "status": "onDaemonEvent",
    "notification": "onDaemonEvent",
    "owned_devices": "onOwnedDevices",
    "notif_status": "onNotifStatus",
    "hot_progress": "onHotProgress",
    "activity": "onActivity",
    "selection": "onSelection",
}


def _load_idl():
    return json.loads(IDL_PATH.read_text())


def _real_api():
    import gui_main
    with patch("pathlib.Path.exists", return_value=False):
        return gui_main.DivoomGuiAPI()


def test_idl_file_is_versioned():
    idl = _load_idl()
    assert idl["version"] == 1, "bump version with any seam change"
    assert len(idl["methods"]) > 0 and len(idl["push_events"]) == 7


def test_bridge_methods_match_idl_exactly():
    """New public method without an IDL entry fails; removed method fails."""
    from control_server import list_methods
    live = sorted(m["name"] for m in list_methods(_real_api()))
    assert live == _load_idl()["methods"]


def test_denylist_matches_control_server():
    import control_server as cs
    assert sorted(cs._DENYLIST) == _load_idl()["denylist"]


def test_js_called_methods_are_subset_of_idl():
    """Every window.pywebview.api.* call in web_ui/ must exist in the IDL."""
    idl_methods = set(_load_idl()["methods"])
    called = set()
    for p in (REPO / "divoom_gui" / "web_ui").glob("*.js"):
        called.update(re.findall(r"pywebview\.api\.(\w+)", p.read_text()))
    assert called, "JS seam scan found nothing — glob broken?"
    assert called <= idl_methods, f"JS calls missing from IDL: {sorted(called - idl_methods)}"


def test_push_events_match_gui_main_handler_map():
    """The 7 etype->window.Divoom.* routes in _make_daemon_event_handler."""
    import gui_main

    seen = {}

    class FakeWindow:
        def evaluate_js(self, js):
            m = re.search(r"window\.Divoom\.(\w+)\(", js)
            if m:
                seen.setdefault("_last", m.group(1))

    # Drive the handler once per etype and record which JS entry it calls.
    routes = {}
    for etype, want in EXPECTED_PUSH.items():
        w = FakeWindow()
        h = gui_main._make_daemon_event_handler(w)
        h({"type": etype})
        got = None
        # re-capture: evaluate_js stores last handler name via closure side effect
        calls = []
        orig = w.evaluate_js
        w2 = FakeWindow()
        h2 = gui_main._make_daemon_event_handler(w2)
        captured = []
        w2.evaluate_js = captured.append
        h2({"type": etype})
        assert captured, f"no JS push for etype {etype}"
        m = re.search(r"window\.Divoom\.(\w+)\(", captured[0])
        routes[etype] = m.group(1)
    assert routes == _load_idl()["push_events"] == EXPECTED_PUSH


def test_lifecycle_edges_present():
    idl = _load_idl()
    assert idl["lifecycle"]["daemon_down"] == "onDaemonDown"
    assert "shutdown" in idl["lifecycle"]
