"""Unit tests for divoom_lib.mcp_tools (R61 coverage push)."""

import asyncio
import base64
import dataclasses
import logging

import pytest

from divoom_lib.mcp_tools import (
    _make_handlers,
    _validate_level,
    build_tool_catalog,
    LIGHT_MODE_NAMES,
)


class FakeMusic:
    async def set_volume(self, level): return True
    async def get_volume(self): return 10


class FakeDevice:
    async def set_brightness(self, level): return True
    async def set_low_power_switch(self, v): return True
    async def get_brightness(self): return 50


class FakeControl:
    async def set_light_mode(self, ch): return True
    async def get_light_mode(self): return 0
    async def set_hot(self, v): return True


class FakeWeather:
    async def set(self, t, wt): return True


class FakeAlarm:
    async def set_alarm(self, *a, **k): return True


class FakeRadio:
    async def set_radio_frequency(self, f): return True


class FakeDesign:
    async def set_screen_dir(self, d): return True
    async def set_screen_mirror(self, m): return True
    async def get_screen_dir(self): return 0
    async def get_screen_mirror(self): return False


class FakeDisplay:
    async def show_image(self, f): return True


class FakeDivoom:
    def __init__(self):
        self.music = FakeMusic()
        self.device = FakeDevice()
        self.control = FakeControl()
        self.weather = FakeWeather()
        self.alarm = FakeAlarm()
        self.radio = FakeRadio()
        self.design = FakeDesign()
        self.display = FakeDisplay()
        self.capabilities = None


@pytest.fixture
def divoom():
    return FakeDivoom()


@pytest.fixture
def handlers(divoom):
    return _make_handlers(divoom)


def test_validate_level_ok():
    assert _validate_level("x", 5, 0, 10) == 5


def test_validate_level_bad_type():
    with pytest.raises(ValueError):
        _validate_level("x", "5", 0, 10)
    with pytest.raises(ValueError):
        _validate_level("x", True, 0, 10)


def test_validate_level_out_of_range():
    with pytest.raises(ValueError):
        _validate_level("x", 99, 0, 10)


async def test_set_volume(handlers):
    assert await handlers["set_volume"](5) == {"ok": True, "level": 5}


async def test_set_volume_invalid(handlers):
    with pytest.raises(ValueError):
        await handlers["set_volume"](99)


async def test_set_brightness(handlers):
    assert await handlers["set_brightness"](50) == {"ok": True, "level": 50}


async def test_set_light_mode(handlers):
    out = await handlers["set_light_mode"]("clock")
    assert out == {"ok": True, "mode": "clock", "channel": 0}


async def test_set_light_mode_invalid(handlers):
    with pytest.raises(ValueError):
        await handlers["set_light_mode"]("nope")


async def test_set_weather(handlers):
    out = await handlers["set_weather"](20, "rain")
    assert out["ok"] is True and out["temperature_c"] == 20 and out["weather"] == "rain"


async def test_set_weather_invalid(handlers):
    with pytest.raises(ValueError):
        await handlers["set_weather"](20, "hail")
    with pytest.raises(ValueError):
        await handlers["set_weather"](200, "rain")


async def test_set_alarm(handlers):
    out = await handlers["set_alarm"](0, 7, 30, weekday_mask=1)
    assert out["ok"] is True and out["index"] == 0 and out["enabled"] is True


async def test_set_alarm_invalid(handlers):
    with pytest.raises(ValueError):
        await handlers["set_alarm"](99, 7, 30)


async def test_set_radio(handlers):
    assert await handlers["set_radio"](975) == {"ok": True, "freq_x10": 975}


async def test_set_radio_invalid(handlers):
    with pytest.raises(ValueError):
        await handlers["set_radio"](10)


async def test_set_low_power(handlers):
    assert await handlers["set_low_power"](True) == {"ok": True, "enabled": True}
    assert (await handlers["set_low_power"](False))["ok"] is True


async def test_set_low_power_invalid(handlers):
    with pytest.raises(ValueError):
        await handlers["set_low_power"]("yes")


async def test_set_screen_orientation(handlers):
    out = await handlers["set_screen_orientation"](90, mirror=True)
    assert out["ok"] is True and out["degrees"] == 90 and out["mirror"] is True


async def test_set_screen_orientation_invalid(handlers):
    with pytest.raises(ValueError):
        await handlers["set_screen_orientation"](45)
    with pytest.raises(ValueError):
        await handlers["set_screen_orientation"](90, mirror="yes")


async def test_show_image(handlers):
    assert await handlers["show_image"]("/tmp/x.png") == {"ok": True, "file": "/tmp/x.png"}


async def test_show_image_empty(handlers):
    with pytest.raises(ValueError):
        await handlers["show_image"]("")


async def test_push_animation_file(handlers):
    assert await handlers["push_animation"](file="/tmp/a.gif") == {"ok": True}


async def test_push_animation_data(handlers, divoom):
    b64 = base64.b64encode(b"GIFDATA").decode()
    assert await handlers["push_animation"](data=b64) == {"ok": True}


async def test_push_animation_neither_nor_both(handlers):
    with pytest.raises(ValueError):
        await handlers["push_animation"]()
    with pytest.raises(ValueError):
        await handlers["push_animation"](file="a", data="b")


async def test_play_sound(handlers):
    assert await handlers["play_sound"](500) == {"ok": True, "duration_ms": 500}


async def test_play_sound_invalid(handlers):
    with pytest.raises(ValueError):
        await handlers["play_sound"](10)


async def test_play_sound_set_hot_missing(divoom):
    handlers = _make_handlers(divoom)

    class NoHot:
        async def set_hot(self, v):
            raise AttributeError("nope")

    divoom.control = NoHot()
    out = await handlers["play_sound"](500)
    assert out["ok"] is False


async def test_get_capabilities_dataclass(divoom):
    @dataclasses.dataclass
    class Caps:
        width: int = 16
        height: int = 16
    divoom.capabilities = Caps()
    out = await handlers_get(divoom)["get_capabilities"]()
    assert out == {"width": 16, "height": 16}


async def test_get_capabilities_raw(divoom):
    divoom.capabilities = "rawcaps"
    out = await handlers_get(divoom)["get_capabilities"]()
    assert out == {"raw": "rawcaps"}


async def test_get_capabilities_proxy_awaitable(divoom):
    class Proxy:
        def to_dict(self):
            async def _():
                return {"panel": "16x16"}
            return _()
    divoom.capabilities = Proxy()
    out = await handlers_get(divoom)["get_capabilities"]()
    assert out == {"panel": "16x16"}


async def test_get_device_state(divoom):
    out = await handlers_get(divoom)["get_device_state"]()
    assert out == {
        "volume": 10, "brightness": 50, "light_mode": 0,
        "screen_orientation": 0, "mirror": False,
    }


async def test_get_device_state_safe_default(divoom):
    class Boom:
        async def get_volume(self):
            raise RuntimeError("x")
    divoom.music = Boom()
    out = await handlers_get(divoom)["get_device_state"]()
    assert out["volume"] is None


def handlers_get(divoom):
    return _make_handlers(divoom)


def test_build_tool_catalog(divoom):
    catalog = build_tool_catalog(divoom)
    names = {t.name for t in catalog}
    assert len(names) == 13
    assert len(catalog) == 13
    for tool in catalog:
        assert tool.description
        assert tool.input_schema
        assert callable(tool.handler)
