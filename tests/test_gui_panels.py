"""The GUI asks the DAEMON, by mac, what a panel is and how bright/loud it is (P5.1).

`divoom_gui/panels.py` replaced four mac-less calls (`get_brightness`,
`get_volume`, `set_brightness`, `set_volume`, which went to whichever panel
`current_divoom` happened to be) and a name-based size guess in
`MediaSyncMixin._get_device_size` ("64" in the name meant 64, anything else
16). These drive the real mixin against a fake daemon client that records
every request with the mac it named.
"""
from __future__ import annotations

import asyncio
import json

from divoom_gui.media_sync import MediaSyncMixin
from divoom_gui.panels import PanelsMixin

A, B = "AA:01", "BB:02"


class _FakeClient:
    """Two panels: a Ditoo with a speaker, a Pixoo 64 without one."""

    def __init__(self):
        self.calls: list[tuple[str, str | None, list]] = []
        self.status = {
            A: {"mac": A, "connected": True, "model": "DitooPlus", "width": 16, "height": 16,
                "model_source": "name", "features": {"speaker": True}},
            B: {"mac": B, "connected": True, "model": "Pixoo64Wifi", "width": 64, "height": 64,
                "model_source": "name", "features": {"speaker": False}},
        }
        self.levels = {A: {"device.get_brightness": 30, "music.get_volume": 5},
                       B: {"device.get_brightness": 90, "music.get_volume": 2}}

    def device_status(self, mac=None):
        if mac is None:
            return {"success": True, "devices": list(self.status.values()), "selected": A}
        return dict(self.status.get(mac, {}), success=True)

    def device_call(self, method, args=None, kwargs=None, *, target="device", blobs=None, token=None, mac=None):
        self.calls.append((method, mac, list(args or [])))
        if method in ("device.get_brightness", "music.get_volume"):
            return {"success": True, "result": self.levels[mac][method]}
        return {"success": True, "result": True}


class _Api(PanelsMixin, MediaSyncMixin):
    def __init__(self, client):
        self._fake = client
        self.wall_slots = {}
        self.discovered_list = [{"address": A, "name": "Ditoo 64 Desk"}]

    def _client(self):
        return self._fake

    def _run_async(self, coro, *, timeout=120.0):
        return asyncio.run(coro)


def test_get_panels_is_the_daemons_description_of_each_panel():
    out = json.loads(_Api(_FakeClient()).get_panels())
    assert out["ok"] is True
    by_mac = {p["mac"]: p for p in out["panels"]}
    assert by_mac[A]["width"] == 16 and by_mac[A]["model"] == "DitooPlus"
    assert by_mac[B]["width"] == 64 and by_mac[B]["features"] == {"speaker": False}


def test_levels_are_read_from_the_panel_named():
    client = _FakeClient()
    api = _Api(client)
    a = json.loads(api.get_panel_levels(A))
    assert (a["brightness"], a["volume"]) == (30, 5)
    assert {mac for _, mac, _ in client.calls} == {A}, client.calls


def test_volume_is_not_asked_of_a_panel_without_a_speaker():
    client = _FakeClient()
    b = json.loads(_Api(client).get_panel_levels(B))
    assert b["brightness"] == 90 and b["volume"] is None, b
    assert [m for m, _, _ in client.calls] == ["device.get_brightness"], client.calls


def test_writes_name_their_panel():
    client = _FakeClient()
    api = _Api(client)
    assert api.set_brightness(B, 55) is True
    assert api.set_volume(A, 9) is True
    assert ("device.set_brightness", B, [55]) in client.calls
    assert ("music.set_volume", A, [9]) in client.calls


def test_a_write_that_names_no_panel_is_refused_not_sent_somewhere():
    client = _FakeClient()
    api = _Api(client)
    assert api.set_brightness("", 55) is False
    assert api.set_volume(None, 3) is False
    assert json.loads(api.get_panel_levels(""))["ok"] is False
    assert client.calls == []


def test_writes_are_clamped_to_the_protocol_range():
    client = _FakeClient()
    api = _Api(client)
    api.set_brightness(A, 400)
    api.set_volume(A, -2)
    assert ("device.set_brightness", A, [100]) in client.calls
    assert ("music.set_volume", A, [0]) in client.calls


def test_a_panels_size_is_the_daemons_not_the_names():
    """The Ditoo's NAME says 64; the daemon says 16. The old guess said 64.
    P5.7: asked of the panel a call NAMES -- there is no "active" one here."""
    api = _Api(_FakeClient())
    assert api._size_of(A) == 16
    assert api._size_of(B) == 64


def test_an_unknown_size_falls_back_to_the_default_not_a_guess():
    client = _FakeClient()
    client.status[A]["width"] = None
    api = _Api(client)
    assert api._size_of(A) == 16
    assert api._panel_pixels(A) is None


def test_a_lan_panel_takes_brightness_over_lan():
    """The LAN fallback the old LightingApi.set_brightness had, kept per panel."""
    client = _FakeClient()
    client.status[B]["lan_ip"] = "10.0.0.9"
    api = _Api(client)
    assert api.set_brightness(B, 40) is True
    assert ("lan.set_brightness", B, [40]) in client.calls
    assert api.set_brightness(A, 41) is True
    assert ("device.set_brightness", A, [41]) in client.calls
