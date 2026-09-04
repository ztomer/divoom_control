"""Unit tests for divoom_lib.system.device (R61 coverage push)."""

import logging

import pytest

from divoom_lib.models import COMMANDS, CHANNEL_ID_MIN, CHANNEL_ID_MAX
from divoom_lib.system.device import Device


class _FramingCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeComm:
    def __init__(self):
        self.logger = logging.getLogger("test.device")
        self.calls = []
        self.send_result = True
        self.wait_payload = b""
        self.name_response = None
        self.device_name = ""
        self.use_ios_le_protocol = False
        self._expected_response_command = None

    async def send_command(self, command, args=None, write_with_response=False):
        self.calls.append((command, args))
        return self.send_result

    async def send_command_and_wait_for_response(self, command, args=None, timeout=10):
        if command == COMMANDS["get device name"] and self.name_response is not None:
            return list(self.name_response)
        return [1]

    def drain_notifications(self):
        pass

    def _framing_context(self, use_ios, escape):
        return _FramingCtx()

    async def wait_for_response(self, command_id, timeout=3.0):
        return self.wait_payload


def last_args(comm):
    return comm.calls[-1][1]


@pytest.fixture
def comm():
    return FakeComm()


@pytest.fixture
def device(comm):
    return Device(comm)


async def test_set_brightness(device, comm):
    await device.set_brightness(50)
    cmd, args = comm.calls[-1]
    assert cmd == COMMANDS["set brightness"]
    assert args == [50]


async def test_get_work_mode(device, comm):
    # default FakeComm wc returns [1]
    assert await device.get_work_mode() == 1


async def test_get_work_mode_empty(device, comm):
    async def empty(*a, **k):
        return []
    comm.send_command_and_wait_for_response = empty
    assert await device.get_work_mode() is None


async def test_set_work_mode(device, comm):
    await device.set_work_mode(3)
    cmd, args = comm.calls[-1]
    assert cmd == COMMANDS["set work mode"]
    assert args == [3]


async def test_set_channel_valid(device, comm):
    ok = await device.set_channel(2)
    assert ok is True
    cmd, args = comm.calls[-1]
    assert cmd == COMMANDS["set channel light"]
    assert args == [2]


async def test_set_channel_invalid_low(device, comm):
    ok = await device.set_channel(CHANNEL_ID_MIN - 1)
    assert ok is False
    assert comm.calls == []


async def test_set_channel_invalid_high(device, comm):
    ok = await device.set_channel(CHANNEL_ID_MAX + 1)
    assert ok is False


async def test_send_sd_status(device, comm):
    await device.send_sd_status(1)
    cmd, args = comm.calls[-1]
    assert cmd == COMMANDS["send sd status"]
    assert args == [1]


async def test_get_device_temp(device, comm):
    async def resp(*a, **k):
        return [0, 21, 0, 0, 0, 0, 0]
    comm.send_command_and_wait_for_response = resp
    out = await device.get_device_temp()
    assert out == {"format": 0, "value": 21}


async def test_get_device_temp_short(device, comm):
    async def resp(*a, **k):
        return [0]
    comm.send_command_and_wait_for_response = resp
    assert await device.get_device_temp() is None


async def test_send_net_temp_packs(device, comm):
    await device.send_net_temp(2024, 6, 15, 13, 30, 2, [(25, 1), (-3, 2)])
    cmd, args = comm.calls[-1]
    assert cmd == COMMANDS["send net temp"]
    assert args[:7] == [0xE8, 0x07, 6, 15, 13, 30, 2]
    assert args[7:] == [25, 1, 0xFD, 2]


async def test_send_net_temp_disp(device, comm):
    await device.send_net_temp_disp([True, False, True], 90)
    cmd, args = comm.calls[-1]
    assert cmd == COMMANDS["send net temp disp"]
    assert args == [1, 0, 1, 90, 0]


async def test_get_net_temp_disp(device, comm):
    async def resp(*a, **k):
        return [1, 0, 1, 0, 1, 0x2D, 0x00]
    comm.send_command_and_wait_for_response = resp
    out = await device.get_net_temp_disp()
    assert out == {"display_modes": [1, 0, 1, 0, 1], "time_minutes": 45}


async def test_get_net_temp_disp_short(device, comm):
    async def resp(*a, **k):
        return [1]
    comm.send_command_and_wait_for_response = resp
    assert await device.get_net_temp_disp() is None


async def test_set_device_name_truncates(device, comm):
    long_name = "x" * 20
    await device.set_device_name(long_name)
    cmd, args = comm.calls[-1]
    assert cmd == COMMANDS["set device name"]
    assert args[0] == 16
    assert len(args[1:]) == 16


async def test_set_device_name_normal(device, comm):
    await device.set_device_name("Ditoo")
    cmd, args = comm.calls[-1]
    assert args[0] == 5
    assert bytes(args[1:]).decode() == "Ditoo"


async def test_get_device_name_known(device, comm):
    comm.device_name = "Ditoo-light-2"
    assert await device.get_device_name() == "Ditoo-light-2"


async def test_get_device_name_fallback(device, comm):
    comm.device_name = ""
    comm.name_response = b"\x05Ditoo"
    assert await device.get_device_name() == "Ditoo"


async def test_get_device_name_fallback_invalid_utf8(device, comm):
    comm.device_name = ""
    comm.name_response = b"\x02\xff\xfe"
    assert await device.get_device_name() is None


async def test_send_current_temp(device, comm):
    await device.send_current_temp(25, 3)
    cmd, args = comm.calls[-1]
    assert cmd == COMMANDS["send current temp"]
    assert args == [25, 3]


async def test_set_temp_type(device, comm):
    await device.set_temp_type(1)
    cmd, args = comm.calls[-1]
    assert cmd == COMMANDS["set temp type"]
    assert args == [1]


async def test_get_brightness_live_read(device, comm):
    comm.wait_payload = bytes([0, 0, 0, 0, 0, 0, 42])
    assert await device.get_brightness() == 42


async def test_get_brightness_empty_payload(device, comm):
    comm.wait_payload = b""
    assert await device.get_brightness() is None
