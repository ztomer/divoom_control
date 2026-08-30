"""Danmaku overlay send (P2.4).

Danmaku/SendText is the device's OWN overlay layer, drawn over whatever channel
is showing — a different mechanism from `push_text`, which renders a bitmap and
uploads it. The P2.1 audit kept it (unlike Voice/SendText, which duplicates
push_text) on the grounds that it is genuinely distinct and testable on hardware
the user owns.

The render is UNCONFIRMED. That is stated in the UI, not hidden; these tests pin
the parts that are knowable without a matrix:

* the daemon is called with KEYWORD args, because its handler reads
  `get_arg_str(kw, "Text", ...)` by name and positional args would land as
  neither — an ACK for an empty string;
* wall mode is refused, since an overlay targets one device's own display;
* empty text never reaches the device.
"""
from __future__ import annotations

import pytest

from divoom_gui.api.lighting import LightingApi


class _FakeLan:
    def __init__(self, recorder):
        self._rec = recorder

    def send_danmaku_text(self, *args, **kwargs):
        self._rec.append(("send_danmaku_text", args, kwargs))
        return True


class _FakeTarget:
    def __init__(self, recorder):
        self.lan = _FakeLan(recorder)


@pytest.fixture
def api(monkeypatch):
    """A LightingApi whose dispatch runs the lambda against a fake device.

    `_current_target_mode` is a read-only property over `_state_getter()`, so
    the mode is set through that dict rather than assigned — the non-wall value
    is "single".
    """
    calls: list = []
    state = {"current_target_mode": "single"}
    obj = LightingApi.__new__(LightingApi)
    obj._state_getter = lambda: state

    def fake_dispatch(build_coro):
        return build_coro(_FakeTarget(calls))

    monkeypatch.setattr(obj, "_dispatch", fake_dispatch, raising=False)
    obj._calls = calls
    obj._state = state
    return obj


def test_the_daemon_is_called_with_keyword_arguments(api):
    """The handler reads Text/TextColor BY NAME (`get_arg_str(kw, "Text", "")`).

    Sent positionally they would land as neither, and the command would ACK
    having pushed an empty string — a success signal for a no-op, which is the
    exact failure mode this feature is already suspected of on hardware.
    """
    assert api.send_danmaku_text("hello", "#00ffcc") is True

    name, args, kwargs = api._calls[0]
    assert name == "send_danmaku_text"
    assert args == (), f"must be keyword args, got positional {args}"
    assert kwargs == {"Text": "hello", "TextColor": "#00ffcc"}


def test_the_default_colour_is_white(api):
    api.send_danmaku_text("hi")
    assert api._calls[0][2]["TextColor"] == "#FFFFFF"


def test_text_is_trimmed(api):
    api.send_danmaku_text("  spaced  ")
    assert api._calls[0][2]["Text"] == "spaced"


def test_empty_text_never_reaches_the_device(api):
    assert api.send_danmaku_text("   ") is False
    assert api._calls == []


def test_wall_mode_is_refused(api):
    """An overlay targets one device's own display, not a composite across
    several — the same reason album and playlist playback reject wall mode."""
    api._state["current_target_mode"] = "wall"
    assert api.send_danmaku_text("hello") is False
    assert api._calls == []


def test_a_device_error_is_reported_not_raised(api, monkeypatch):
    """A failing send must return False, not propagate into the pywebview
    bridge thread where it would surface as a dead button."""
    def boom(_build):
        raise RuntimeError("LAN unreachable")

    monkeypatch.setattr(api, "_dispatch", boom, raising=False)
    assert api.send_danmaku_text("hello") is False


def test_the_method_is_reachable_on_the_real_gui_api():
    """pywebview exposes DivoomGuiAPI's methods by name, so a missing forward is
    a missing feature with no other symptom."""
    from divoom_gui.gui_api import DivoomGuiAPI

    assert callable(getattr(DivoomGuiAPI, "send_danmaku_text", None))


def test_the_ui_states_that_the_render_is_unconfirmed():
    """The honest-placeholder rule, pinned.

    This command ACKs cleanly and nobody has watched it draw on a matrix. R32
    §D is the case where exactly that combination rendered nothing. If someone
    later deletes the caveat because the button "looks finished", this fails.
    """
    from pathlib import Path

    html = (Path(__file__).parent.parent / "divoom_gui" / "web_ui"
            / "index.html").read_text()
    assert 'id="send-danmaku-btn"' in html
    assert "Not yet verified on real hardware" in html
