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

    # R71 P3.1: send_danmaku_text goes through `_lan_action` now, which
    # resolves `_target()` and awaits via `_run_async` — so those are the two
    # seams to fake, not `_dispatch`.
    monkeypatch.setattr(obj, "_target", lambda: _FakeTarget(calls), raising=False)
    monkeypatch.setattr(obj, "_run_async", lambda coro, **kw: coro, raising=False)
    obj._calls = calls
    obj._state = state
    return obj


def test_the_daemon_is_called_with_keyword_arguments(api):
    """The handler reads Text/TextColor BY NAME (`get_arg_str(kw, "Text", "")`).

    Sent positionally they would land as neither, and the command would ACK
    having pushed an empty string — a success signal for a no-op, which is the
    exact failure mode this feature is already suspected of on hardware.
    """
    assert api.send_danmaku_text("hello", "#00ffcc")["ok"] is True

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
    reply = api.send_danmaku_text("   ")
    assert reply["ok"] is False and reply["cause"] == "input"
    assert api._calls == []


def test_wall_mode_is_refused(api):
    """An overlay targets one device's own display, not a composite across
    several — the same reason album and playlist playback reject wall mode."""
    api._state["current_target_mode"] = "wall"
    reply = api.send_danmaku_text("hello")
    assert reply["ok"] is False and reply["cause"] == "wall"
    assert "Virtual Wall" in reply["error"]
    assert api._calls == []


def test_a_device_error_is_reported_not_raised(api, monkeypatch):
    """A failing send must return False, not propagate into the pywebview
    bridge thread where it would surface as a dead button."""
    def boom(_coro, **_kw):
        raise RuntimeError("LAN unreachable")

    monkeypatch.setattr(api, "_run_async", boom, raising=False)
    reply = api.send_danmaku_text("hello")
    assert reply["ok"] is False
    assert "LAN unreachable" in reply["error"]


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


# ── R71 P3.1: the capability gate ─────────────────────────────────────────────
#
# A Bluetooth-only device used to answer a bare `False`, which the UI rendered
# as "Failed to send overlay" — indistinguishable from a broken feature. The
# daemon knew the real answer the whole time and the bool discarded it. Same
# defect R70 fixed for cloud browse, on the other transport.

def test_no_lan_capability_is_distinguishable_from_a_plain_failure(api, monkeypatch):
    """The whole point: 'this device has no LAN' is its own state."""
    from divoom_client.daemon_proxy import _DeviceCallError

    def refuse(_coro, **_kw):
        raise _DeviceCallError(
            "this device is connected over Bluetooth, which has no LAN API",
            "no_lan_capability")

    monkeypatch.setattr(api, "_run_async", refuse, raising=False)
    reply = api.send_danmaku_text("hello")

    assert reply["ok"] is False
    assert reply["cause"] == "no_lan_capability"
    assert "Bluetooth" in reply["error"]
    # ...and it must NOT read like the generic device-rejected case.
    assert reply["cause"] != "lan"


def test_a_generic_lan_failure_keeps_its_own_cause(api, monkeypatch):
    """Calibration: if every failure came back 'no_lan_capability' the flag
    would carry no information at all."""
    from divoom_client.daemon_proxy import _DeviceCallError

    def refuse(_coro, **_kw):
        raise _DeviceCallError("Danmaku/SendText failed (RC=1)", "")

    monkeypatch.setattr(api, "_run_async", refuse, raising=False)
    reply = api.send_danmaku_text("hello")
    assert reply["ok"] is False
    assert reply["cause"] == "lan", reply


def test_no_device_connected_is_its_own_cause(api, monkeypatch):
    monkeypatch.setattr(api, "_target", lambda: None, raising=False)
    reply = api.send_danmaku_text("hello")
    assert reply["ok"] is False and reply["cause"] == "unreachable"


def test_the_proxy_preserves_the_daemons_cause():
    """The seam that made this possible: _DeviceCallError used to flatten every
    failure to a message string, so the cause died in transit."""
    from divoom_client.daemon_proxy import _DeviceCallError

    exc = _DeviceCallError("no LAN", "no_lan_capability")
    assert exc.cause == "no_lan_capability"
    assert _DeviceCallError("plain").cause == ""
