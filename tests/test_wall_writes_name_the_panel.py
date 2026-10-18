"""Every bridge write to the wall hands the page the panel that failed (P6.4).

P6.3 made the daemon name each wall panel whose write failed (`failed`, mac to
reason) apart from each slot with no panel (`degraded`), and the wall image
push passed that to the page. The other wall writes -- light, clock, channel,
VJ, visualizer, text, rich clock, scoreboard, brightness, volume -- answered a
bare true/false, so the toast said "Failed to switch channel" and the reason,
naming the panel, reached only the log.

Enumerated, not listed: EVERY public bridge method that takes a mac is called
on the wall against a daemon whose wall names one failing panel, and every one
that sent the wall a `device_call` must hand back that panel and its reason.
On a panel, the same methods answer the same shape. A wall write added
tomorrow is held to this on the day it is added.
"""
from __future__ import annotations

import json

import pytest

from tests.support.bridge_calls import (
    A, B, NOT_CALLED, WALL, RecordingDaemon, args_for, call, names_its_panel,
    public_methods, recorded_api,
)

WHY = "the transfer failed"
REFUSAL = {"success": False, "code": "device_failed", "result": False,
           "error": f"wall: {B} did not take it ({WHY})",
           "failed": {B: WHY}, "degraded": []}


class _FailingWall(RecordingDaemon):
    """The wall's B did not take the write; a panel takes everything."""

    def device_call(self, method, args=None, kwargs=None, target="device",
                    blobs=None, token=None, mac=None):
        super().device_call(method, args, kwargs, target, blobs, token, mac)
        return dict(REFUSAL) if target == "wall" else {"success": True, "result": True}


@pytest.fixture
def api(tmp_path):
    with recorded_api(tmp_path) as gui:
        gui._daemon_client = _FailingWall()
        gui.wall_slots = {A: {"x": 0, "y": 0, "size": 16}, B: {"x": 1, "y": 0, "size": 16}}
        yield gui


def _reply(value):
    return json.loads(value) if isinstance(value, str) else value


#: Bridge methods that forward their caller's method and reply verbatim; on
#: the wall the method would be this test's choice (see the existence test).
PASSTHROUGH = {"device_call"}

WRITES = [m for m in public_methods()
          if m[0] not in NOT_CALLED and m[0] not in PASSTHROUGH and names_its_panel(m[1])]


def _wall_reply(api, name, fn):
    api.select_device(A)
    api._daemon_client.requests.clear()
    reply = _reply(getattr(api, name)(*args_for(fn, WALL)))
    sent = [kw for r, kw in api._daemon_client.requests
            if r == "device_call" and kw["target"] == "wall"]
    return reply, sent


def _wall_writes(api):
    """Each wall-writing bridge method and its reply on the failing wall."""
    out = {}
    for name, fn in WRITES:
        reply, sent = _wall_reply(api, name, fn)
        if sent:
            out[name] = reply
    return out


def test_every_wall_write_names_the_panel_that_did_not_take_it(api):
    writes = _wall_writes(api)
    # Calibration: the walk reaches the writes this item is about.
    expected = {"set_solid_light", "set_clock", "switch_channel", "set_vj_effect",
                "set_visualization", "push_text", "set_clock_rich", "set_scoreboard",
                "set_brightness", "set_volume", "display_wall_image"}
    assert expected <= set(writes), f"not reached: {sorted(expected - set(writes))}"
    wrong = {}
    for name, reply in writes.items():
        if not isinstance(reply, dict):
            wrong[name] = f"answered {reply!r}, not the write's outcome"
        elif (reply.get("success"), reply.get("failed"), reply.get("degraded")) != (False, {B: WHY}, []):
            wrong[name] = f"dropped the panel that failed: {reply}"
    assert wrong == {}, f"wall writes that do not hand the page the failing panel: {wrong}"


DISPLAY_WRITES = ["set_solid_light", "set_clock", "switch_channel", "set_vj_effect",
                  "set_visualization", "push_text", "set_clock_rich", "set_scoreboard",
                  "set_brightness", "set_volume"]


@pytest.mark.parametrize("name", DISPLAY_WRITES)
def test_a_display_write_answers_one_shape_on_a_panel_too(api, name):
    """The page reads one reply whichever display it named."""
    fn = dict(public_methods())[name]
    call(api, name, args_for(fn, A))
    reply = _reply(getattr(api, name)(*args_for(fn, A)))
    assert reply == {"success": True}, f"{name} on a panel answered {reply!r}"


@pytest.mark.parametrize("name", DISPLAY_WRITES)
def test_a_display_write_naming_no_panel_says_why(api, name):
    fn = dict(public_methods())[name]
    reply = _reply(getattr(api, name)(*args_for(fn, "")))
    assert isinstance(reply, dict) and reply.get("success") is False, f"{name}: {reply!r}"
    assert reply.get("error"), f"{name} refused with no reason: {reply}"
