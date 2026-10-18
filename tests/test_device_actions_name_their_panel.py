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

from pathlib import Path

import pytest

from tests.support.bridge_calls import (
    A, B, NOT_CALLED, WALL, args_for as _args_for, call as _call,
    names_its_panel as _names_its_panel, public_methods as _public_methods, recorded_api,
)

#: Methods that act on more than one panel by design, and say so in their API.
FLEET_WIDE = {
    # Runs Auto-Sync over every target the Routines tab toggled, each named
    # by its address (`hotchannel_config.get_targets()`); never the selection.
    "sync_now": "every Auto-Sync target, each by its address",
    # Builds the wall from the slots it is given.
    "update_wall_slots": "the wall, from the slots in its argument",
}


@pytest.fixture
def api(tmp_path):
    with recorded_api(tmp_path) as gui:
        yield gui


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
