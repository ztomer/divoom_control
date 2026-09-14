"""Durable device_call parity check (hardware-free, static analysis).

The Python daemon routes every facade method string (``<submodule>.<method>``)
verbatim to ``divoomd`` via ``device_call``. For true parity, ``divoomd`` must
have a handler for every such key. This test enumerates the Python facade's
public callable methods (class-level; no device instantiation) and asserts the
Rust ``device_call`` dispatcher covers each one.

This is the anti-drift guard for ROADMAP item #4: adding a facade method
without a matching Rust handler turns this test red. The ``ALLOWLIST`` must
stay empty — any genuine gap is a real parity break, not a skim.
"""

import importlib
import inspect
import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
RUST_DEVICE_CALL_DIR = REPO_ROOT / "divoomd" / "src" / "device_call"

# attr (facade submodule) -> "module.Class" path inside divoom_lib.
FACADE = {
    "light": "divoom_legacy.display.light.Light",
    "animation": "divoom_legacy.display.animation.Animation",
    "drawing": "divoom_legacy.display.drawing.Drawing",
    "text": "divoom_legacy.display.text.Text",
    "device": "divoom_legacy.system.device.Device",
    "time": "divoom_legacy.system.time.Time",
    "bluetooth": "divoom_legacy.system.bluetooth.Bluetooth",
    "music": "divoom_legacy.media.music.Music",
    "radio": "divoom_legacy.media.radio.Radio",
    "alarm": "divoom_legacy.scheduling.alarm.Alarm",
    "sleep": "divoom_legacy.scheduling.sleep.Sleep",
    "timeplan": "divoom_legacy.scheduling.timeplan.Timeplan",
    "weather": "divoom_legacy.system.weather.Weather",
    "scoreboard": "divoom_legacy.tools.scoreboard.Scoreboard",
    "timer": "divoom_legacy.tools.timer.Timer",
    "countdown": "divoom_legacy.tools.countdown.Countdown",
    "noise": "divoom_legacy.tools.noise.Noise",
    "notification": "divoom_legacy.tools.notification.Notification",
    "hot_update": "divoom_legacy.tools.hot_update.HotUpdate",
    "display": "divoom_legacy.display.Display",
    "system": "divoom_legacy.system.System",
    "sound": "divoom_legacy.system.sound.SoundControl",
    "control": "divoom_legacy.system.control.Control",
    "tool": "divoom_legacy.tool.Tool",
    "game": "divoom_legacy.game.Game",
    "design": "divoom_legacy.display.design.Design",
}

# Internal helpers that are not device_call-routable actions.
INTERNAL = {"update_display", "_update_message", "set_logger", "run", "start", "stop"}

# Genuine parity gaps would go here ONLY as a documented, time-boxed exception.
# Must stay empty: a new facade method without a Rust handler is a real break.
ALLOWLIST = set()


def _python_facade_methods():
    methods = set()
    for attr, path in FACADE.items():
        mod, cls = path.rsplit(".", 1)
        Cls = getattr(importlib.import_module(mod), cls)
        for name in dir(Cls):
            if name.startswith("_") or name in INTERNAL:
                continue
            member = getattr(Cls, name)
            if isinstance(member, property):
                continue
            if not (inspect.isfunction(member) or inspect.ismethod(member)):
                continue
            methods.add(f"{attr}.{name}")
    return methods


def _rust_handler_keys():
    keys = set()
    if not RUST_DEVICE_CALL_DIR.is_dir():
        pytest.skip(f"Rust device_call source not found at {RUST_DEVICE_CALL_DIR}")
    for f in RUST_DEVICE_CALL_DIR.glob("*.rs"):
        # Keys may contain digits (e.g. animation.app_big64_user_define).
        for match in re.findall(r'"([a-zA-Z0-9_]+\.[a-zA-Z0-9_]+)"', f.read_text()):
            keys.add(match)
    return keys


def test_device_call_parity():
    python_methods = _python_facade_methods()
    rust_keys = _rust_handler_keys()
    assert python_methods, "facade enumeration produced no methods"

    gaps = sorted(python_methods - rust_keys - ALLOWLIST)
    assert not gaps, (
        f"{len(gaps)} Python facade method(s) have no Rust device_call handler: "
        + ", ".join(gaps)
    )
