"""Call every public bridge method against a recording daemon client.

Shared by `tests/test_device_actions_name_their_panel.py` (P5.7: every
panel action names its panel) and `tests/test_bridge_commands_exist_in_daemon.py`
(P6.5: every call the GUI makes is one the daemon answers). Both enumerate
`DivoomGuiAPI`'s public methods rather than list them, so a method added
tomorrow is covered on the day it is added.

The recorder answers only what the real `DaemonClient` has: a GUI that calls a
client method that does not exist fails here, rather than being answered by a
fake that accepts any name.
"""
from __future__ import annotations

import contextlib
import inspect
from unittest.mock import patch

A, B = "AA:00:00:00:00:01", "BB:00:00:00:00:02"
WALL = "MatrixWall"

#: Requests that act on a panel, and the panel each one names. A
#: `device_call` to the wall names the wall.
PANEL_REQUESTS = {
    "device_call": lambda kw: WALL if kw.get("target") == "wall" else kw.get("mac"),
    "custom_art_push": lambda kw: kw.get("mac"),
    "hot_update": lambda kw: kw.get("address") or None,
    "live_job_start": lambda kw: kw.get("mac"),
    "live_job_stop": lambda kw: kw.get("mac"),
    "live_jobs_stop_for": lambda kw: kw.get("mac"),
    "wall_configure": lambda kw: WALL,
}

#: Not called, and why. None of them may act on a panel.
NOT_CALLED = {
    "sync_now": "starts a worker thread over the Auto-Sync targets (FLEET_WIDE)",
    "start_mcp_server": "spawns the MCP subprocess",
    "stop_mcp_server": "stops the MCP subprocess",
    "close_window": "shuts the daemon down and closes the window",
}

#: An argument for a parameter with no default, by name.
ARGS = {
    "mac": A, "address": A, "enable": True, "enabled": True, "on": True,
    "is_24h": True, "fahrenheit": False, "action": "start", "file_id": "f1",
    "symbol": "AAPL", "text": "hi", "name": "Desk", "title": "hi",
    "color": "#ffffff", "index": 0, "minutes": 5, "hour": 7, "minute": 30,
    "month": 1, "day": 2, "direction": 1, "freq_x10": 1015, "app_type": 7,
    "confirm": "RESET", "payload_json": '{"0": "f1"}', "page": 0,
    "brightness": 50, "volume": 5, "channel": "vj", "number": 3, "style": 2,
    "on_off": 1, "album_id": 1, "play_id": 1, "sleep_id": 1, "kind": "clock",
    "method": "design.use_user_define_index", "classify": 18, "keyword": "x",
    "lat": 1.0, "lon": 2.0, "message": "m", "value": True, "ip": "10.0.0.9",
    "token": 1, "email": "a@b.c", "password": "p", "json_text": "[]",
    "slots_json": "{}", "topology_data": {}, "config": "{}", "dial_type": "x",
    "sleep_type": 0, "timeout": 1, "limit": 1, "sort": 1, "file_size": 1,
}


class RecordingDaemon:
    """Answers every request with success and records what it was asked.

    A name the real `DaemonClient` lacks raises AttributeError, as it would
    against the real client, and is kept in `missing`: the GUI catches most
    exceptions, so the raise alone would go unseen."""

    def __init__(self):
        self.requests: list[tuple[str, dict]] = []
        self.missing: set[str] = set()

    def _record(self, name, **kw):
        self.requests.append((name, kw))
        return {"success": True, "result": True, "started": True}

    def device_call(self, method, args=None, kwargs=None, target="device",
                    blobs=None, token=None, mac=None):
        self._record("device_call", method=method, target=target, mac=mac)
        return {"success": True, "result": True}

    def custom_art_push(self, file_ids, page, slot=None, slots=None, mac=None):
        return self._record("custom_art_push", mac=mac)

    def hot_update(self, *, device_size=16, show=True, address=""):
        return self._record("hot_update", address=address)

    def live_job_start(self, mac, kind, params):
        return self._record("live_job_start", mac=mac)

    def live_job_stop(self, mac, kind):
        return self._record("live_job_stop", mac=mac)

    def live_jobs_stop_for(self, mac=None):
        return self._record("live_jobs_stop_for", mac=mac)

    def wall_configure(self, slots, cell_size=16):
        self._record("wall_configure")
        return {"success": True, "wall": True}

    def device_status(self, mac=None):
        return {"success": True, "connected": True, "mac": mac, "width": 16, "devices": []}

    def __getattr__(self, name):
        from divoom_client.daemon_protocol import DaemonClient
        if name.startswith("_"):
            raise AttributeError(name)
        if not hasattr(DaemonClient, name):
            self.missing.add(name)
            raise AttributeError(f"DaemonClient has no {name!r}")
        return lambda *a, **kw: {"success": True}

    def panel_requests(self):
        return [(name, PANEL_REQUESTS[name](kw), kw) for name, kw in self.requests
                if name in PANEL_REQUESTS]


def public_methods():
    from divoom_gui.gui_api import DivoomGuiAPI
    return sorted((name, fn) for name, fn in inspect.getmembers(DivoomGuiAPI, inspect.isfunction)
                  if not name.startswith("_"))


def names_its_panel(fn) -> bool:
    return list(inspect.signature(fn).parameters)[1:2] == ["mac"]


def args_for(fn, panel):
    out = []
    for i, (pname, p) in enumerate(list(inspect.signature(fn).parameters.items())[1:]):
        if i == 0 and pname == "mac":
            out.append(panel)
        elif p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        elif p.default is not p.empty:
            break
        else:
            assert pname in ARGS, f"{fn.__name__}: give parameter {pname!r} an argument in ARGS"
            out.append(ARGS[pname])
    return out


@contextlib.contextmanager
def recorded_api(tmp_path):
    """A real `DivoomGuiAPI` whose daemon client is a `RecordingDaemon`."""
    from divoom_gui import daemon_bridge
    daemon = RecordingDaemon()
    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(daemon_bridge, "ensure_daemon", lambda *a, **k: daemon), \
         patch.object(daemon_bridge, "daemon_alive", lambda *a, **k: True), \
         patch("subprocess.run"):
        from divoom_gui.gui_api import DivoomGuiAPI
        gui = DivoomGuiAPI()
        gui._daemon_client = daemon
        frame = tmp_path / "frame.png"
        frame.write_bytes(b"png")
        gui._widget_frame = lambda kind, size, params=None: ({}, frame)
        gui.lighting._widget_frame = gui._widget_frame
        cache = tmp_path / ".config" / "divoom-control" / "cache_gallery"
        cache.mkdir(parents=True)
        (cache / "f1.gif").write_bytes(b"GIF89a")
        ARGS["file_path"] = str(frame)
        try:
            yield gui
        finally:
            gui.loop_thread.stop()


def call(api, name, args):
    """Call `name` as the bench would: A selected, then B (the user moved on
    before the call ran). What it SENT before any failure is what counts."""
    api.select_device(A)
    api.select_device(B)
    api._daemon_client.requests.clear()
    try:
        getattr(api, name)(*args)
    except Exception:
        pass
