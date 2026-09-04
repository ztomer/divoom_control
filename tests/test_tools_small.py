"""Unit tests for divoom_lib.tools.{countdown,noise,timer,scoreboard} (R61)."""

import logging

import pytest

from divoom_lib.models import COMMANDS
from divoom_lib.tools.countdown import Countdown
from divoom_lib.tools.noise import Noise
from divoom_lib.tools.timer import Timer
from divoom_lib.tools.scoreboard import Scoreboard


class _FramingCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeComm:
    def __init__(self):
        self.logger = logging.getLogger("test.tools")
        self.calls = []
        self.send_result = True
        self.wait_payload = None
        self.use_ios_le_protocol = False
        self._expected_response_command = None

    async def send_command(self, command, args=None, write_with_response=False):
        self.calls.append((command, args))
        return self.send_result

    def _framing_context(self, use_ios, escape):
        return _FramingCtx()

    async def wait_for_response(self, command_id, timeout=3.0):
        return self.wait_payload


@pytest.fixture
def comm():
    return FakeComm()


# ---- countdown ----
async def test_countdown_get(comm):
    comm.wait_payload = bytes([1, 5, 0])
    out = await Countdown(comm).get_countdown()
    assert out == {"status": 1, "minutes": 5, "seconds": 0}
    assert comm.calls[-1][0] == COMMANDS["get tool info"]


async def test_countdown_get_short(comm):
    comm.wait_payload = b"\x01"
    assert await Countdown(comm).get_countdown() is None
    comm.wait_payload = None
    assert await Countdown(comm).get_countdown() is None


async def test_countdown_set(comm):
    ok = await Countdown(comm).set_countdown(1, 5, 0)
    assert ok is True
    cmd, args = comm.calls[-1]
    assert cmd == COMMANDS["set tool"]
    assert args == [3, 1, 5, 0]


# ---- noise ----
async def test_noise_get(comm):
    comm.wait_payload = bytes([2])
    assert await Noise(comm).get_noise() == {"status": 2}


async def test_noise_get_short(comm):
    comm.wait_payload = b""
    assert await Noise(comm).get_noise() is None


async def test_noise_set(comm):
    await Noise(comm).set_noise(1)
    cmd, args = comm.calls[-1]
    assert cmd == COMMANDS["set tool"]
    assert args == [2, 1]


# ---- timer ----
async def test_timer_get(comm):
    comm.wait_payload = bytes([1])
    assert await Timer(comm).get_timer() == {"status": 1}


async def test_timer_get_short(comm):
    comm.wait_payload = None
    assert await Timer(comm).get_timer() is None


async def test_timer_set(comm):
    await Timer(comm).set_timer(2)
    cmd, args = comm.calls[-1]
    assert cmd == COMMANDS["set tool"]
    assert args == [0, 2]


# ---- scoreboard ----
async def test_scoreboard_get(comm):
    # on_off=1, red=10 (LE 0x0A00), blue=20 (LE 0x1400)
    comm.wait_payload = bytes([1, 0x0A, 0x00, 0x14, 0x00])
    out = await Scoreboard(comm).get_scoreboard()
    assert out == {"on_off": 1, "red_score": 10, "blue_score": 20}


async def test_scoreboard_get_short(comm):
    comm.wait_payload = b"\x01"
    assert await Scoreboard(comm).get_scoreboard() is None


async def test_scoreboard_set_clamps(comm):
    await Scoreboard(comm).set_scoreboard(1, 5000, -5)
    cmd, args = comm.calls[-1]
    assert cmd == COMMANDS["set tool"]
    # red clamped to 999 (LE 0xE703), blue clamped to 0
    assert args == [1, 1, 0xE7, 0x03, 0, 0]


async def test_scoreboard_set_on_off_mask(comm):
    await Scoreboard(comm).set_scoreboard(0x1FF, 0, 0)
    args = comm.calls[-1][1]
    assert args[1] == 0xFF  # & 0xFF
