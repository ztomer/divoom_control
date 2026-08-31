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
