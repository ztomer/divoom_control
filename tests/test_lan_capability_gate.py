"""Every LAN-backed GUI surface reports WHY it failed (R71 P3.4).

**Why this is a class-level test and not three method-level ones.** R70 fixed
exactly this defect for cloud browse -- five panels each swallowing the reason
and rendering "nothing found" -- and the fix was one funnel plus one unwrapper.
The LAN side then repeated it in three places (danmaku, photo albums,
playlists), because nothing existed to notice a fourth.

So this does not assert "danmaku returns a dict". It walks the GUI's LAN call
sites and requires each one to be reachable only through `_lan_action`. A new
LAN feature that returns a bare bool fails here on the day it is written, which
is the only version of this fix that stays fixed.

**The permitted exception, and why it is not a hole.** A method may touch
`t.lan` outside the funnel if it BRANCHES on `t.lan` itself -- `set_brightness`
does `t.lan.set_brightness(v) if t.lan else t.device.set_brightness(v)`. That
shape already answers the capability question, by falling back to the transport
the device does have. It is the absence of any answer that this test is for.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from divoom_gui.api.lighting import LightingApi

REPO = Path(__file__).resolve().parent.parent
LIGHTING = REPO / "divoom_gui" / "api" / "lighting.py"


def _lan_methods(tree: ast.AST) -> dict[str, ast.FunctionDef]:
    """Methods whose body reaches for `t.lan` / `target.lan` in any way."""
    out: dict[str, ast.FunctionDef] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Attribute) and sub.attr == "lan"
                    and isinstance(sub.value, ast.Name)):
                out[node.name] = node
                break
    return out


def _uses_funnel(fn: ast.AST) -> bool:
    return any(isinstance(n, ast.Attribute) and n.attr == "_lan_action"
               for n in ast.walk(fn))


def _branches_on_lan(fn: ast.AST) -> bool:
    """`... if t.lan else ...` — the method answers the question itself."""
    for n in ast.walk(fn):
        if isinstance(n, (ast.IfExp, ast.If)):
            for t in ast.walk(n.test):
                if isinstance(t, ast.Attribute) and t.attr == "lan":
                    return True
    return False


def test_every_lan_surface_goes_through_the_funnel():
    tree = ast.parse(LIGHTING.read_text(encoding="utf-8"))
    offenders = [
        name for name, fn in _lan_methods(tree).items()
        if not _uses_funnel(fn) and not _branches_on_lan(fn)
    ]
    assert not offenders, (
        "these LAN-backed methods bypass `_lan_action`, so on a Bluetooth-only "
        "device they can only answer 'it failed' and the user cannot tell a "
        f"missing capability from a broken feature: {offenders}"
    )


def test_the_scan_actually_finds_the_lan_surfaces():
    """Calibration: an empty scan would make the test above pass vacuously."""
    found = set(_lan_methods(ast.parse(LIGHTING.read_text(encoding="utf-8"))))
    for expected in ("send_danmaku_text", "play_album", "push_playlist"):
        assert expected in found, f"{expected} not seen by the scan: {sorted(found)}"


def test_the_brightness_fallback_is_recognised_not_excused():
    """The exception must be earned by branching, not by being on a list."""
    tree = ast.parse(LIGHTING.read_text(encoding="utf-8"))
    fn = _lan_methods(tree).get("set_brightness")
    assert fn is not None
    assert _branches_on_lan(fn), (
        "set_brightness is exempt only because it branches on `t.lan` and falls "
        "back to BLE; if that branch goes, it needs the funnel like the rest"
    )


def test_a_bypassing_method_would_be_caught():
    """Prove the detector bites, without waiting for someone to write one."""
    bad = ast.parse(
        "class A:\n"
        "    def push_thing(self, v):\n"
        "        return self._dispatch(lambda t: t.lan.send_thing(v))\n"
    )
    offenders = [n for n, fn in _lan_methods(bad).items()
                 if not _uses_funnel(fn) and not _branches_on_lan(fn)]
    assert offenders == ["push_thing"]


# ── behaviour, not just structure ─────────────────────────────────────────────
#
# The AST test above proves each surface ROUTES through the funnel. These prove
# the three surfaces actually answer with a usable cause, because "calls
# _lan_action" and "reports something a user can act on" are different claims.

class _FakeLan:
    def __init__(self, rec):
        self._rec = rec

    def __getattr__(self, name):
        def call(*a, **kw):
            self._rec.append((name, a, kw))
            return True
        return call


class _FakeTarget:
    def __init__(self, rec):
        self.lan = _FakeLan(rec)


@pytest.fixture
def api(monkeypatch):
    calls: list = []
    state = {"current_target_mode": "single"}
    obj = LightingApi.__new__(LightingApi)
    obj._state_getter = lambda: state
    monkeypatch.setattr(obj, "_target", lambda: _FakeTarget(calls), raising=False)
    monkeypatch.setattr(obj, "_run_async", lambda coro, **kw: coro, raising=False)
    monkeypatch.setattr(obj, "_stop_live_widgets", lambda: None, raising=False)
    obj._calls = calls
    obj._state = state
    return obj


@pytest.mark.parametrize("method,arg,verb", [
    ("play_album", 7, "play the album"),
    ("push_playlist", 3, "push the playlist"),
])
def test_success_reports_ok(api, method, arg, verb):
    reply = getattr(api, method)(arg)
    assert reply["ok"] is True, reply
    assert api._calls, "the device was never called"


@pytest.mark.parametrize("method,arg", [("play_album", 7), ("push_playlist", 3)])
def test_no_lan_capability_reaches_the_caller(api, monkeypatch, method, arg):
    """The point of the round: a BLE-only device says so, on every surface."""
    from divoom_client.daemon_proxy import _DeviceCallError

    def refuse(_coro, **_kw):
        raise _DeviceCallError(
            "this device is connected over Bluetooth, which has no LAN API",
            "no_lan_capability")

    monkeypatch.setattr(api, "_run_async", refuse, raising=False)
    reply = getattr(api, method)(arg)
    assert reply["ok"] is False
    assert reply["cause"] == "no_lan_capability", reply
    assert "Bluetooth" in reply["error"]


@pytest.mark.parametrize("method,arg", [("play_album", 7), ("push_playlist", 3)])
def test_wall_mode_is_refused_with_its_own_cause(api, method, arg):
    api._state["current_target_mode"] = "wall"
    reply = getattr(api, method)(arg)
    assert reply["ok"] is False and reply["cause"] == "wall"
    assert api._calls == []


@pytest.mark.parametrize("method", ["play_album", "push_playlist"])
def test_a_non_numeric_id_is_input_not_a_device_failure(api, method):
    """Bad input must not masquerade as the device refusing."""
    reply = getattr(api, method)("not-a-number")
    assert reply["ok"] is False and reply["cause"] == "input"
    assert api._calls == []
