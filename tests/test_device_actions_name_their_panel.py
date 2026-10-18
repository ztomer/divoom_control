"""Every bridge method that acts on a panel names it -- enumerated, not listed (P5.7).

P5.6 made the channel writes name their panel, from a hand-written table. The
Tools tab, media sync and the gallery push were not in it, and went on acting
on `current_divoom` -- the panel the bench last selected, read when the call
RAN -- so a selection change between a click and its write sent the write to
the other panel. A table is the instance; this is the class.

It calls EVERY public method of the real `DivoomGuiAPI` against a daemon
client that records each request, with the bench having selected A and then B
(the user moved on). A request that acts on a panel -- a `device_call`, a live
job, a custom-art or hot-channel push, a wall build -- must then name the
panel the METHOD was given:

* a method whose first parameter is `mac` is called with A, and everything it
  sends names A (never B, never nobody); called with no panel, it sends
  nothing at all;
* any other method sends nothing that acts on a panel, unless it is declared
  in `FLEET_WIDE` with the reason it legitimately acts on several.

So a device-writing method added tomorrow without a `mac` fails here on the
day it is added, with no table to forget. `divoomd/src/mock_tools_tests.rs`
pins the daemon's half: a named `device_call` lands on that panel even when
another is selected.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import patch

import pytest

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

#: Methods that act on more than one panel by design, and say so in their API.
FLEET_WIDE = {
    # Runs Auto-Sync over every target the Routines tab toggled, each named
    # by its address (`hotchannel_config.get_targets()`); never the selection.
    "sync_now": "every Auto-Sync target, each by its address",
    # Builds the wall from the slots it is given.
    "update_wall_slots": "the wall, from the slots in its argument",
}

#: Not called here, and why. None of them may act on a panel.
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


class _Daemon:
    """Answers every request with success and records what it was asked."""

    def __init__(self):
        self.requests: list[tuple[str, dict]] = []

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
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *a, **kw: {"success": True}

    def panel_requests(self):
        return [(name, PANEL_REQUESTS[name](kw), kw) for name, kw in self.requests
                if name in PANEL_REQUESTS]


def _public_methods():
    from divoom_gui.gui_api import DivoomGuiAPI
    return sorted((name, fn) for name, fn in inspect.getmembers(DivoomGuiAPI, inspect.isfunction)
                  if not name.startswith("_"))


def _names_its_panel(fn) -> bool:
    return list(inspect.signature(fn).parameters)[1:2] == ["mac"]


def _args_for(fn, panel):
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


@pytest.fixture
def api(tmp_path):
    from divoom_gui import daemon_bridge
    daemon = _Daemon()
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
        yield gui
    gui.loop_thread.stop()


def _call(api, name, args):
    api.select_device(A)
    api.select_device(B)   # the user moved on before this call ran
    api._daemon_client.requests.clear()
    try:
        getattr(api, name)(*args)
    except Exception:
        pass   # what matters is what it SENT before failing


METHODS = [m for m in _public_methods() if m[0] not in NOT_CALLED]


@pytest.mark.parametrize("name,fn", METHODS, ids=[m[0] for m in METHODS])
def test_a_panel_action_names_the_panel_it_was_given(api, name, fn):
    _call(api, name, _args_for(fn, A))
    sent = api._daemon_client.panel_requests()
    if _names_its_panel(fn):
        wrong = [(r, panel) for r, panel, _ in sent if panel != A]
        assert wrong == [], f"{name}(A, ...) acted on {wrong}, not A, the panel it named"
    elif name not in FLEET_WIDE:
        assert sent == [], (
            f"{name} acts on a panel but names none: {[(r, p) for r, p, _ in sent]}. "
            "Its first parameter must be the mac its gesture resolved (P5.7)")


NAMED = [m for m in METHODS if _names_its_panel(m[1])]


@pytest.mark.parametrize("name,fn", NAMED, ids=[m[0] for m in NAMED])
def test_a_panel_action_naming_no_panel_sends_nothing(api, name, fn):
    _call(api, name, _args_for(fn, ""))
    sent = api._daemon_client.panel_requests()
    assert sent == [], f"{name} with no panel acted on {[(r, p) for r, p, _ in sent]}"


def test_the_tools_tab_is_one_panel_never_the_wall(api):
    """A Tools action names ONE panel: the wall is refused, not resolved to
    whichever panel the bench last held (which it was, before P5.7)."""
    api.wall_slots = {A: {"x": 0, "y": 0, "size": 16}}
    for name in ("set_timer", "sync_time", "set_device_name", "set_alarm", "factory_reset"):
        fn = dict(_public_methods())[name]
        _call(api, name, _args_for(fn, WALL))
        sent = api._daemon_client.panel_requests()
        assert sent == [], f"{name} on the wall acted on {[(r, p) for r, p, _ in sent]}"


def test_the_wall_is_named_never_defaulted(api):
    """The gallery push takes the wall by NAME: with slots configured and one
    panel named, it goes to that panel (it went to the wall whenever slots
    existed). Named, the wall gets it, and the only panels touched are its
    slots, whose live widgets are stopped first."""
    api.wall_slots = {A: {"x": 0, "y": 0, "size": 16}, B: {"x": 1, "y": 0, "size": 16}}
    _call(api, "play_gallery_art", [B, "f1"])
    assert {p for _, p, _ in api._daemon_client.panel_requests()} == {B}
    _call(api, "play_gallery_art", [WALL, "f1"])
    sent = api._daemon_client.panel_requests()
    assert {p for r, p, _ in sent if r != "live_jobs_stop_for"} == {WALL}, sent
    assert {p for r, p, _ in sent if r == "live_jobs_stop_for"} == {A, B}, sent


def test_a_live_widget_on_the_wall_is_refused_not_misrouted(api):
    """The daemon's live jobs push to one panel's link: a job named
    `MatrixWall` made a phantom fleet entry with no link and painted nothing.
    With slots configured, a single panel named gets its widget."""
    api.wall_slots = {A: {"x": 0, "y": 0, "size": 16}}
    for name in ("toggle_sysmon_sync", "toggle_music_sync", "toggle_weather_sync",
                 "toggle_stocks_sync"):
        _call(api, name, [WALL, True])
        assert api._daemon_client.panel_requests() == [], name
        _call(api, name, [B, True])
        assert {p for _, p, _ in api._daemon_client.panel_requests()} == {B}, name


def test_the_implicit_route_is_gone():
    """Nothing reads "the panel the bench last selected" any more: no code
    names `current_divoom` (the docs that say what it was quote it)."""
    import re
    root = Path(__file__).parent.parent / "divoom_gui"
    code = re.compile(r"(?<!`)\b_?current_divoom\b(?!`)")
    offenders = [str(p.relative_to(root)) for p in root.rglob("*.py")
                 if code.search(p.read_text(encoding="utf-8"))]
    assert offenders == [], f"current_divoom is still in the code of {offenders}"
