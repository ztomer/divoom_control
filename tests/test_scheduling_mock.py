"""Mock-device unit tests for the scheduling module (alarm / sleep / timeplan).

The existing `test_{alarm,sleep,timeplan}_functions.py` suites require a real
BLE device and skip on CI, which left `divoom_lib/scheduling/` at 17-23%
coverage (REVIEW_2026-06 §0.3). These tests drive the command builders against
a recording mock sender so the on-wire bytes are verified without hardware.

Each command builder takes a `CommandSender`; we record every
`send_command(command, args)` call and assert the command id + argument bytes.
"""

import logging

import pytest

from divoom_lib.models import COMMANDS
from divoom_lib.scheduling.alarm import Alarm
from divoom_lib.scheduling.sleep import Sleep
from divoom_lib.scheduling.timeplan import Timeplan
from divoom_lib.utils.converters import color_to_rgb_list

pytestmark = pytest.mark.asyncio


class MockSender:
    """Records send_command calls and replays canned responses.

    Mirrors the slice of the `CommandSender` protocol the scheduling builders
    touch: `send_command`, `send_command_and_wait_for_response`, `convert_color`
    and a `logger`.
    """

    def __init__(self, response: bytes | None = None):
        self.logger = logging.getLogger("mock_sender")
        self.sent: list[tuple[int | str, list]] = []
        self._response = response

    async def send_command(self, command, args=None, write_with_response=False) -> bool:
        self.sent.append((command, list(args or [])))
        return True

    async def send_command_and_wait_for_response(self, command, args=None, timeout=10):
        self.sent.append((command, list(args or [])))
        return self._response

    def convert_color(self, color_input):
        return color_to_rgb_list(color_input)

    # Convenience accessors -------------------------------------------------
    @property
    def last(self) -> tuple[int | str, list]:
        return self.sent[-1]


# ── Alarm ────────────────────────────────────────────────────────────────


async def test_set_alarm_builds_args():
    s = MockSender()
    ok = await Alarm(s).set_alarm(
        alarm_index=2, status=1, hour=8, minute=30, week=0b0111110,
        mode=0, trigger_mode=1, fm_freq=0x036c, volume=50,
    )
    assert ok is True
    cmd, args = s.last
    assert cmd == COMMANDS["set alarm"]
    # index, status, hour, minute, week, mode, trigger_mode, fm[2 LE], volume
    assert args == [2, 1, 8, 30, 0b0111110, 0, 1, 0x6c, 0x03, 50]


async def test_get_alarm_time_parses_response():
    # APK-verified (u1/b.a()): 10 alarms × 10 bytes, each record STARTS with
    # the alarm index byte. Alarm 0: idx=0,status=1,hour=7,min=15,week=2,
    # mode=0,trigger=1, fm=0x036c (LE at bytes 7,8), volume@9=40.
    block = bytes([0, 1, 7, 15, 2, 0, 1, 0x6c, 0x03, 40])
    rest = b"".join(bytes([i, 0, 0, 0, 0, 0, 0, 0, 0, 0]) for i in range(1, 10))
    s = MockSender(response=block + rest)
    alarms = await Alarm(s).get_alarm_time()
    assert alarms is not None and len(alarms) == 10
    assert alarms[0] == {
        "status": 1, "hour": 7, "minute": 15, "week": 2, "mode": 0,
        "trigger_mode": 1, "fm_freq": 0x036c, "volume": 40,
    }
    # Index bytes must NOT bleed into the next record's fields.
    assert alarms[1]["status"] == 0 and alarms[1]["week"] == 0
    assert s.last[0] == COMMANDS["get alarm time"]


async def test_get_alarm_time_short_response_returns_none():
    assert await Alarm(MockSender(response=b"\x00\x01")).get_alarm_time() is None
    assert await Alarm(MockSender(response=None)).get_alarm_time() is None


async def test_set_alarm_gif_header():
    s = MockSender()
    await Alarm(s).set_alarm_gif(alarm_index=1, total_length=300, gif_id=5, data=[9, 9])
    cmd, args = s.last
    assert cmd == COMMANDS["set alarm gif"]
    # index(1 big), total_length(2 LE), gif_id(1 big), data...
    assert args == [1, 300 & 0xFF, 300 >> 8, 5, 9, 9]


async def test_set_memorial_gif_header():
    s = MockSender()
    await Alarm(s).set_memorial_gif(memorial_index=2, total_length=12, gif_id=7, data=[1])
    cmd, args = s.last
    assert cmd == COMMANDS["set memorial gif"]
    assert args == [2, 12, 0, 7, 1]  # index, total_length(2 LE), gif_id, data


async def test_set_memorial_time_pads_title_to_32():
    s = MockSender()
    await Alarm(s).set_memorial_time(
        dialy_id=0, on_off=1, month=1, day=1, hour=0, minute=0,
        have_flag=1, title_name="NYE",
    )
    cmd, args = s.last
    assert cmd == COMMANDS["set memorial"]
    assert args[:7] == [0, 1, 1, 1, 0, 0, 1]
    title = args[7:]
    assert len(title) == 32
    assert bytes(title).rstrip(b"\x00").decode() == "NYE"


async def test_set_memorial_time_truncates_long_title():
    s = MockSender()
    await Alarm(s).set_memorial_time(0, 1, 1, 1, 0, 0, 1, "x" * 50)
    title = s.last[1][7:]
    assert len(title) == 32
    assert all(b == ord("x") for b in title)  # fully filled, truncated to 32


async def test_get_memorial_time_parses_response():
    # one memorial: id=3,on=1,month=12,day=25,hour=6,min=30,flag=1,title="Xmas"
    title = b"Xmas" + b"\x00" * 28  # 32 bytes
    block = bytes([3, 1, 12, 25, 6, 30, 1]) + title  # 7 + 32 = 39
    response = block + bytes([0] * 39 * 9)
    mems = await Alarm(MockSender(response=response)).get_memorial_time()
    assert mems is not None and len(mems) == 10
    assert mems[0]["dialy_id"] == 3
    assert mems[0]["month"] == 12 and mems[0]["day"] == 25
    assert mems[0]["title_name"] == "Xmas"


async def test_get_memorial_time_short_response_returns_none():
    assert await Alarm(MockSender(response=b"\x00")).get_memorial_time() is None


async def test_set_alarm_listen_and_volume():
    s = MockSender()
    await Alarm(s).set_alarm_listen(on_off=1, mode=0, volume=10)
    assert s.last == (COMMANDS["set alarm listen"], [1, 0, 10])
    await Alarm(s).set_alarm_volume(volume=42)
    assert s.last == (COMMANDS["set alarm vol"], [42])
    await Alarm(s).set_alarm_volume_control(control=1, index=2)
    assert s.last == (COMMANDS["set alarm vol ctrl"], [1, 2])


async def test_set_alarm_listen_bool_to_byte_quirk():
    # bool_to_byte maps only exactly 1 → 1; any other truthy int → 0.
    s = MockSender()
    await Alarm(s).set_alarm_listen(on_off=5, mode=0, volume=0)
    assert s.last[1][0] == 0  # 5 is NOT treated as "on"


# ── Sleep ──────────────────────────────────────────────────────────────────


async def test_show_sleep_defaults():
    s = MockSender()
    await Sleep(s).show_sleep(on=1, sleeptime=10)
    cmd, args = s.last
    assert cmd == COMMANDS["set sleeptime"]
    # sleeptime, sleepmode(default), on, fm[2], volume(default), rgb[3], brightness
    assert args[0] == 10
    assert args[2] == 1  # on
    # time, mode, on, fm[2], volume, rgb[3], brightness = 10 bytes
    assert len(args) == 10


async def test_show_sleep_with_color():
    s = MockSender()
    await Sleep(s).show_sleep(on=1, sleeptime=5, color=[255, 0, 0], brightness=7)
    args = s.last[1]
    assert args[-4:-1] == [255, 0, 0]  # rgb just before brightness
    assert args[-1] == 7


async def test_show_sleep_string_args_coerced():
    s = MockSender()
    # to_int_if_str should coerce "12"/"3" etc.
    await Sleep(s).show_sleep(on=1, sleeptime="12", volume="3", brightness="4")
    args = s.last[1]
    assert args[0] == 12


async def test_set_sleep_scene_listen_and_volume_and_light():
    s = MockSender()
    await Sleep(s).set_sleep_scene_listen(on_off=1, mode=2, volume=30)
    assert s.last == (COMMANDS["set sleep scene listen"], [1, 2, 30])
    await Sleep(s).set_scene_volume(20)
    assert s.last == (COMMANDS["set scene vol"], [20])
    await Sleep(s).set_sleep_light(55)
    assert s.last == (COMMANDS["set sleep light"], [55])


async def test_set_sleep_color_valid_and_invalid():
    s = MockSender()
    ok = await Sleep(s).set_sleep_color([0, 0, 255])
    assert ok is True
    assert s.last == (COMMANDS["set sleep color"], [0, 0, 255])
    # too-short colour is rejected without sending
    before = len(s.sent)
    bad = await Sleep(s).set_sleep_color([1, 2])
    assert bad is False
    assert len(s.sent) == before  # nothing sent


async def test_set_sleep_scene_full():
    s = MockSender()
    await Sleep(s).set_sleep_scene(
        mode=0, on=1, fm_freq=[0x03, 0x6c], volume=50, color=[255, 0, 0], light=8,
    )
    cmd, args = s.last
    assert cmd == COMMANDS["set sleep scene"]
    # mode, on, fm[2], volume, rgb[3], light
    assert args == [0, 1, 0x03, 0x6c, 50, 255, 0, 0, 8]


async def test_get_sleep_scene_parses_response():
    # 10 bytes: time, mode, on, fm[2 LE], volume, r, g, b, light
    response = bytes([20, 1, 1, 0x6c, 0x03, 40, 10, 20, 30, 5])
    scene = await Sleep(MockSender(response=response)).get_sleep_scene()
    assert scene == {
        "time": 20, "mode": 1, "on": 1, "fm_freq": 0x036c, "volume": 40,
        "color_r": 10, "color_g": 20, "color_b": 30, "light": 5,
    }


async def test_get_sleep_scene_short_response_returns_none():
    assert await Sleep(MockSender(response=b"\x00\x01")).get_sleep_scene() is None


# ── Timeplan ─────────────────────────────────────────────────────────────────


async def test_set_time_manage_info_type1_no_animation():
    s = MockSender()
    ok = await Timeplan(s).set_time_manage_info(
        status=1, hour=9, minute=0, week=0b0111110, mode=0,
        trigger_mode=1, fm_freq=0x036c, volume=50, type=1,
    )
    assert ok is True
    cmd, args = s.last
    assert cmd == COMMANDS["set time manage info"]
    # status,hour,minute,week,mode,trigger,fm[2 LE],volume,type
    assert args == [1, 9, 0, 0b0111110, 0, 1, 0x6c, 0x03, 50, 1]


async def test_set_time_manage_info_type0_animation_defaults():
    s = MockSender()
    await Timeplan(s).set_time_manage_info(
        status=1, hour=9, minute=0, week=0, mode=0, trigger_mode=1,
        fm_freq=0, volume=50, type=0,
    )
    args = s.last[1]
    # type 0 appends 5 animation default bytes (all 0) after the type byte
    assert args[-6:] == [0, 0, 0, 0, 0, 0]  # type + 5 defaults


async def test_set_time_manage_info_type0_animation_data():
    s = MockSender()
    await Timeplan(s).set_time_manage_info(
        status=1, hour=9, minute=0, week=0, mode=0, trigger_mode=1,
        fm_freq=0, volume=50, type=0, animation_id=3, animation_speed=4,
        animation_direction=1, animation_frame_count=2, animation_frame_delay=10,
        animation_frame_data=[0xAA, 0xBB],
    )
    args = s.last[1]
    assert args[-7:] == [3, 4, 1, 2, 10, 0xAA, 0xBB]


async def test_set_time_manage_info_unknown_type_returns_false():
    s = MockSender()
    before = len(s.sent)
    ok = await Timeplan(s).set_time_manage_info(
        status=1, hour=0, minute=0, week=0, mode=0, trigger_mode=0,
        fm_freq=0, volume=0, type=9,
    )
    assert ok is False
    assert len(s.sent) == before  # nothing sent for unknown type


async def test_set_time_manage_ctrl():
    s = MockSender()
    await Timeplan(s).set_time_manage_ctrl(status=1, index=3)
    assert s.last == (COMMANDS["set time manage ctrl"], [1, 3])
