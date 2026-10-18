"""Every channel bridge call names its panel, and the daemon is told THAT mac (P5.6).

P5.2 resolved the selected display at the click in the web UI, but the bridge
calls it then made carried no mac: `ApiBase._target()` sent them to
`current_divoom`, which `select_device` rebinds on every bench highlight. A
selection that moved between the click and the backend's write therefore
sent the setting to the other panel.

These drive the REAL bridge methods (`DivoomGuiAPI` -> LightingApi/ToolsApi ->
`DaemonDeviceProxy`) against a recording daemon client, so what is asserted is
the `mac` each `device_call` carries -- the field the daemon routes by
(`divoomd/src/mock_channel_tests.rs` pins that half). One table lists every
channel write; a method added to the bridge without a row fails
`test_every_channel_write_is_in_the_table`.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import patch

import pytest

A, B = "AA:00:00:00:00:01", "BB:00:00:00:00:02"

#: (bridge method, its arguments after the mac, the device_call method it makes)
CHANNEL_WRITES = [
    ("set_solid_light", ("#00ffcc", 80, 0), "display.show_light"),
    ("set_clock", (3, "#ff0000"), "display.show_clock"),
    ("set_clock_rich", (2, True, False, True, False, "#ffffff"), "display.set_clock_rich"),
    ("switch_channel", ("vj",), "display.switch_channel"),
    ("set_vj_effect", (4,), "display.show_effects"),
    ("set_visualization", (5,), "display.show_visualization"),
    ("push_text", ("HI", "#ffffff", 1, 50, 1), "display.show_image"),
    ("set_scoreboard", (1, 3, 5), "scoreboard.set_scoreboard"),
    ("play_album", (7,), "lan.play_album"),
    ("push_playlist", (9,), "lan.send_playlist"),
    ("send_danmaku_text", ("hi", "#ffffff"), "lan.send_danmaku_text"),
    ("play_aid_sleep", (11, 0), "aid_sleep.play"),
]


class _Daemon:
    """Answers every call with success and records what it was asked."""

    def __init__(self):
        self.calls: list[tuple[str, str | None]] = []
        self.stops: list[str | None] = []
        self.selected: str | None = None

    def device_call(self, method, args=None, kwargs=None, target="device",
                    blobs=None, token=None, mac=None):
        self.calls.append((method, mac))
        return {"success": True, "result": True}

    def live_jobs_stop_for(self, mac=None):
        self.stops.append(mac)
        return {"success": True}

    def select_device(self, mac):
        self.selected = mac
        return {"success": True}

    def device_status(self, mac=None):
        return {"success": True, "connected": True, "mac": mac, "width": 16}

    def __getattr__(self, name):
        return lambda *a, **kw: {"success": True}


@pytest.fixture
def api(tmp_path):
    with patch("pathlib.Path.home", return_value=tmp_path):
        from divoom_gui.gui_api import DivoomGuiAPI
        gui = DivoomGuiAPI()
    gui._daemon_client = _Daemon()
    frame = tmp_path / "text.png"
    frame.write_bytes(b"png")
    gui.lighting._widget_frame = lambda kind, size, params=None: ({}, frame)
    yield gui
    gui.loop_thread.stop()


def test_every_channel_write_is_in_the_table():
    """A bridge method whose first parameter is `mac` and that the web UI's
    channel controls call must be listed above, or nobody checks its route."""
    from divoom_gui.gui_api import DivoomGuiAPI

    js = "".join(p.read_text() for p in
                 (Path(__file__).parent.parent / "divoom_gui" / "web_ui").glob("*.js"))
    named = {name for name, fn in inspect.getmembers(DivoomGuiAPI, inspect.isfunction)
             if list(inspect.signature(fn).parameters)[1:2] == ["mac"]
             and (f"{name}(w.mac" in js or f"{name}(t.mac" in js)}
    assert named == {row[0] for row in CHANNEL_WRITES}, (
        f"in the UI but not the table: {named - {r[0] for r in CHANNEL_WRITES}}; "
        f"in the table but not the UI: {({r[0] for r in CHANNEL_WRITES}) - named}")


@pytest.mark.parametrize("method,args,call", CHANNEL_WRITES, ids=[r[0] for r in CHANNEL_WRITES])
def test_a_write_reaches_the_panel_it_names_after_the_selection_moved(api, method, args, call):
    api.select_device(A)
    api.select_device(B)   # the user moved on before this write ran
    reply = getattr(api, method)(A, *args)
    assert reply is True or (isinstance(reply, dict) and (reply.get("success") or reply.get("ok"))), reply
    daemon = api._daemon_client
    sent = [(m, mac) for m, mac in daemon.calls if m == call]
    assert sent == [(call, A)], f"{method} must reach A, the panel it named: {daemon.calls}"
    assert B not in daemon.stops, f"{method} stopped live jobs on B: {daemon.stops}"


@pytest.mark.parametrize("method,args,call", CHANNEL_WRITES, ids=[r[0] for r in CHANNEL_WRITES])
def test_a_write_naming_no_panel_is_refused(api, method, args, call):
    api.select_device(B)   # the old implicit route, which must not be taken
    reply = getattr(api, method)("", *args)
    assert reply is False or (isinstance(reply, dict) and not (reply.get("success") or reply.get("ok"))), reply
    assert reply is False or reply.get("error"), f"{method} refused with no reason: {reply}"
    daemon = api._daemon_client
    assert daemon.calls == [], f"{method} with no panel reached the daemon: {daemon.calls}"
    assert daemon.stops == [], f"{method} with no panel stopped live jobs: {daemon.stops}"


def test_the_implicit_route_is_gone():
    """`_target()` read the selection when the write RAN; nothing may again."""
    from divoom_gui.api import ApiBase

    assert not hasattr(ApiBase, "_target")
    assert not hasattr(ApiBase, "_current_target_mode")
    src = (Path(__file__).parent.parent / "divoom_gui" / "api" / "lighting.py").read_text()
    assert "_current_target_mode" not in src
