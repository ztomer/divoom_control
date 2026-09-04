"""Unit tests for divoom_lib.system.device_settings (R61 coverage push)."""

import logging

import pytest

from divoom_lib.models import COMMANDS, POVVC_GET, POVVC_SET, POCC_GET, POCC_SET
from divoom_lib.models import POCC_CHANNEL_MIN, POCC_CHANNEL_MAX
from divoom_lib.system.device_settings import DeviceSettings
from divoom_lib.utils.converters import bool_to_byte


class FakeSender:
    """Duck-typed CommandSender: records calls, returns canned responses."""

    def __init__(self):
        self.logger = logging.getLogger("test.device_settings")
        self.calls = []
        self.send_result = True
        self.responses = {}

    async def send_command(self, command, args=None, write_with_response=False):
        self.calls.append((command, args))
        return self.send_result

    async def send_command_and_wait_for_response(self, command, args=None, timeout=10):
        return self.responses.get(command, [1])


@pytest.fixture
def sender():
    return FakeSender()


@pytest.fixture
def settings(sender):
    return DeviceSettings(sender)


def last_args(sender):
    return sender.calls[-1][1]


async def test_set_boot_gif_packs_args(settings, sender):
    ok = await settings.set_boot_gif(1, 256, 3, [9, 8])
    assert ok is True
    cmd, args = sender.calls[-1]
    assert cmd == COMMANDS["set boot gif"]
    assert args == [bool_to_byte(1), 0, 1, 3, 9, 8]


async def test_set_low_power_switch(settings, sender):
    await settings.set_low_power_switch(1)
    cmd, args = sender.calls[-1]
    assert cmd == COMMANDS["set low power switch"]
    assert args == [1]


async def test_get_low_power_switch_returns_value(settings, sender):
    sender.responses[COMMANDS["get low power switch"]] = [1]
    assert await settings.get_low_power_switch() == 1

    sender.responses[COMMANDS["get low power switch"]] = [0]
    assert await settings.get_low_power_switch() == 0


async def test_get_low_power_switch_empty_or_none(settings, sender):
    sender.responses[COMMANDS["get low power switch"]] = []
    assert await settings.get_low_power_switch() is None

    sender.responses[COMMANDS["get low power switch"]] = None
    assert await settings.get_low_power_switch() is None


async def test_set_song_display_control(settings, sender):
    await settings.set_song_display_control(0)
    cmd, args = sender.calls[-1]
    assert cmd == COMMANDS["set song dis ctrl"]
    assert args == [0]


async def test_set_power_on_voice_volume_set_with_volume(settings, sender):
    ok = await settings.set_power_on_voice_volume(POVVC_SET, volume=50)
    assert ok is True
    cmd, args = sender.calls[-1]
    assert cmd == COMMANDS["set poweron voice vol"]
    assert args == [POVVC_SET, 50]


async def test_set_power_on_voice_volume_get(settings, sender):
    ok = await settings.set_power_on_voice_volume(POVVC_GET)
    assert ok is True
    cmd, args = sender.calls[-1]
    assert args == [POVVC_GET]


async def test_set_power_on_voice_volume_out_of_range(settings, sender):
    ok = await settings.set_power_on_voice_volume(POVVC_SET, volume=200)
    assert ok is False
    assert sender.calls == []


async def test_set_power_on_voice_volume_missing_volume(settings, sender):
    ok = await settings.set_power_on_voice_volume(POVVC_SET)
    assert ok is False


async def test_set_power_on_voice_volume_unknown_control(settings, sender):
    ok = await settings.set_power_on_voice_volume(99)
    assert ok is False


async def test_set_power_on_channel_set(settings, sender):
    ok = await settings.set_power_on_channel(POCC_SET, channel_id=2)
    assert ok is True
    cmd, args = sender.calls[-1]
    assert cmd == COMMANDS["set poweron channel"]
    assert args == [POCC_SET, 2]


async def test_set_power_on_channel_out_of_range(settings, sender):
    ok = await settings.set_power_on_channel(POCC_SET, channel_id=POCC_CHANNEL_MAX + 1)
    assert ok is False


async def test_set_power_on_channel_missing(settings, sender):
    ok = await settings.set_power_on_channel(POCC_SET)
    assert ok is False


async def test_set_power_on_channel_unknown(settings, sender):
    ok = await settings.set_power_on_channel(7)
    assert ok is False


async def test_set_auto_power_off_packs_le(settings, sender):
    await settings.set_auto_power_off(0x0102)
    cmd, args = sender.calls[-1]
    assert cmd == COMMANDS["set auto power off"]
    assert args == [0x02, 0x01]


async def test_get_auto_power_off(settings, sender):
    sender.responses[COMMANDS["get auto power off"]] = [0x34, 0x12]
    assert await settings.get_auto_power_off() == 0x1234


async def test_get_auto_power_off_short_response(settings, sender):
    sender.responses[COMMANDS["get auto power off"]] = [1]
    assert await settings.get_auto_power_off() is None


async def test_set_and_get_sound_control(settings, sender):
    await settings.set_sound_control(1)
    cmd, args = sender.calls[-1]
    assert cmd == COMMANDS["set sound ctrl"]
    assert args == [1]

    sender.responses[COMMANDS["get sound ctrl"]] = [1]
    assert await settings.get_sound_control() == 1
    assert await settings.get_sound_control() == 1
