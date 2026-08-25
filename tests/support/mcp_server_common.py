"""Shared helpers for the split mcp_server test modules."""
from types import SimpleNamespace  # noqa: F401
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from divoom_lib.mcp_server import MCPServer

# ── Helpers ───────────────────────────────────────────────────────────


def _fake_divoom() -> MagicMock:
    """Build a MagicMock with the surface area the tool catalog uses."""
    d = MagicMock()
    # We need AsyncMock for any method that gets awaited. Easiest way
    # is to build a sub-MagicMock per service and assign AsyncMocks
    # for the coroutine methods.
    music = MagicMock()
    music.set_volume = AsyncMock(return_value=True)
    music.get_volume = AsyncMock(return_value=8)
    d.music = music
    device = MagicMock()
    device.set_brightness = AsyncMock(return_value=True)
    device.get_brightness = AsyncMock(return_value=80)
    device.set_low_power_switch = AsyncMock(return_value=True)
    d.device = device
    control = MagicMock()
    control.set_light_mode = AsyncMock(return_value=True)
    control.get_light_mode = AsyncMock(return_value=0)
    control.set_hot = AsyncMock(return_value=True)
    d.control = control
    weather = MagicMock()
    weather.set = AsyncMock(return_value=True)
    d.weather = weather
    alarm = MagicMock()
    alarm.set_alarm = AsyncMock(return_value=True)
    d.alarm = alarm
    radio = MagicMock()
    radio.set_radio_frequency = AsyncMock(return_value=True)
    d.radio = radio
    design = MagicMock()
    design.set_screen_dir = AsyncMock(return_value=True)
    design.get_screen_dir = AsyncMock(return_value=0)
    design.set_screen_mirror = AsyncMock(return_value=True)
    design.get_screen_mirror = AsyncMock(return_value=False)
    d.design = design
    display = MagicMock()
    display.show_image = AsyncMock(return_value=True)
    d.display = display
    # `capabilities` is read directly (not awaited) — make it a
    # MagicMock with a ``to_dict()`` shim.
    caps = MagicMock()
    caps.to_dict.return_value = {
        "panel_resolution": 16,
        "has_speaker": True,
        "has_clock": True,
    }
    d.capabilities = caps
    return d


def _async_return(value: Any):
    async def _coro(*args, **kwargs):
        return value

    return _coro


def _build_server(divoom=None) -> MCPServer:
    from divoom_lib.mcp_tools import build_tool_catalog
    s = MCPServer(server_info={"name": "divoom-control", "version": "0.15.0"})
    s.tools = build_tool_catalog(divoom or _fake_divoom())
    return s
