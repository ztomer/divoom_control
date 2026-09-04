"""Mock-device unit tests for divoom_lib/tool.py (timer/score/noise/countdown).

The pre-existing `test_tool_timer_functions.py` needs a real device and skips,
leaving tool.py at 18% (REVIEW_2026-06 §0.5). These tests drive the builders
and response parser against a recording mock.
"""

import contextlib
import logging

import pytest

from divoom_lib.models import (
    COMMANDS,
    TOOL_TYPE_TIMER, TOOL_TYPE_SCORE, TOOL_TYPE_NOISE, TOOL_TYPE_COUNTDOWN,
    TOOL_TYPE_NOT_IN_GAME_MODE,
)
from divoom_lib.tool import Tool

pytestmark = pytest.mark.asyncio


class ToolMockSender:
    """Recording mock covering the slice of CommandSender that tool.py uses."""

    def __init__(self, response=None):
        self.logger = logging.getLogger("tool_mock")
        self.sent: list[tuple[int | str, list]] = []
        self.use_ios_le_protocol = False
        self._expected_response_command = None
        self._response = response
        self.framing_calls = 0

    async def send_command(self, command, args=None, write_with_response=False) -> bool:
        self.sent.append((command, list(args or [])))
        return True

    async def wait_for_response(self, command):
        return self._response

    @contextlib.asynccontextmanager
    async def _framing_context(self, use_ios=False, escape=False):
        self.framing_calls += 1
        yield

    @property
    def last(self):
        return self.sent[-1]


# ── get_tool_info parsing ───────────────────────────────────────────────────


async def test_get_tool_info_timer():
    s = ToolMockSender(response=[1])
    info = await Tool(s).get_tool_info(TOOL_TYPE_TIMER)
    assert info == {"status": 1}
    assert s.last[0] == COMMANDS["get tool info"]
    assert s.last[1] == [TOOL_TYPE_TIMER]
    assert s.framing_calls == 1


async def test_get_tool_info_score():
    # on_off=1, red=2 (LE bytes 1,2), blue=3 (LE bytes 3,4)
    s = ToolMockSender(response=[1, 0x02, 0x00, 0x03, 0x00])
    info = await Tool(s).get_tool_info(TOOL_TYPE_SCORE)
    assert info == {"on_off": 1, "red_score": 2, "blue_score": 3}


async def test_get_tool_info_noise():
    info = await Tool(ToolMockSender(response=[1])).get_tool_info(TOOL_TYPE_NOISE)
    assert info == {"status": 1}


async def test_get_tool_info_countdown():
    info = await Tool(ToolMockSender(response=[1, 5, 30])).get_tool_info(TOOL_TYPE_COUNTDOWN)
    assert info == {"status": 1, "minutes": 5, "seconds": 30}


async def test_get_tool_info_not_in_game_mode():
    info = await Tool(ToolMockSender(response=[0])).get_tool_info(TOOL_TYPE_NOT_IN_GAME_MODE)
    assert info == {"status": "not in game mode"}


async def test_get_tool_info_no_response_returns_none():
    assert await Tool(ToolMockSender(response=None)).get_tool_info(TOOL_TYPE_TIMER) is None


async def test_get_tool_info_short_response_returns_none():
    # score needs >=5 bytes; a 3-byte response yields None
    assert await Tool(ToolMockSender(response=[1, 0, 0])).get_tool_info(TOOL_TYPE_SCORE) is None


# ── set_tool_info builders ──────────────────────────────────────────────────


async def test_set_tool_timer():
    s = ToolMockSender()
    ok = await Tool(s).set_tool_info(TOOL_TYPE_TIMER, ctrl_flag=2)
    assert ok is True
    assert s.last == (COMMANDS["set tool"], [TOOL_TYPE_TIMER, 2])


async def test_set_tool_score_with_scores():
    s = ToolMockSender()
    await Tool(s).set_tool_info(TOOL_TYPE_SCORE, on_off=1, red_score=258, blue_score=3)
    cmd, args = s.last
    assert cmd == COMMANDS["set tool"]
    # mode, on_off, red(2 LE), blue(2 LE)  -> 258 = 0x0102
    assert args == [TOOL_TYPE_SCORE, 1, 0x02, 0x01, 0x03, 0x00]


async def test_set_tool_score_defaults_zero():
    s = ToolMockSender()
    await Tool(s).set_tool_info(TOOL_TYPE_SCORE, on_off=0)
    assert s.last[1] == [TOOL_TYPE_SCORE, 0, 0, 0, 0, 0]


async def test_set_tool_noise():
    s = ToolMockSender()
    await Tool(s).set_tool_info(TOOL_TYPE_NOISE, ctrl_flag=1)
    assert s.last == (COMMANDS["set tool"], [TOOL_TYPE_NOISE, 1])


async def test_set_tool_countdown():
    s = ToolMockSender()
    await Tool(s).set_tool_info(TOOL_TYPE_COUNTDOWN, ctrl_flag=1, minutes=10, seconds=0)
    assert s.last == (COMMANDS["set tool"], [TOOL_TYPE_COUNTDOWN, 1, 10, 0])


async def test_set_tool_unknown_mode_returns_false():
    s = ToolMockSender()
    ok = await Tool(s).set_tool_info(99, ctrl_flag=1)
    assert ok is False
    assert s.sent == []  # nothing sent


async def test_set_tool_missing_required_kwarg_returns_false():
    # missing ctrl_flag for timer -> ValueError caught -> False, nothing sent
    s = ToolMockSender()
    ok = await Tool(s).set_tool_info(TOOL_TYPE_TIMER)
    assert ok is False
    assert s.sent == []


async def test_set_tool_countdown_missing_fields_returns_false():
    s = ToolMockSender()
    ok = await Tool(s).set_tool_info(TOOL_TYPE_COUNTDOWN, ctrl_flag=1, minutes=5)
    assert ok is False
    assert s.sent == []


async def test_set_tool_score_missing_on_off_returns_false():
    s = ToolMockSender()
    assert await Tool(s).set_tool_info(TOOL_TYPE_SCORE, red_score=1) is False
    assert s.sent == []


async def test_set_tool_noise_missing_ctrl_flag_returns_false():
    s = ToolMockSender()
    assert await Tool(s).set_tool_info(TOOL_TYPE_NOISE) is False
    assert s.sent == []


async def test_get_tool_info_empty_timer_response_returns_none():
    # timer needs len>=1; empty list falls through to None
    assert await Tool(ToolMockSender(response=[])).get_tool_info(TOOL_TYPE_TIMER) is None
    assert await Tool(ToolMockSender(response=[])).get_tool_info(TOOL_TYPE_NOISE) is None
    assert await Tool(ToolMockSender(response=[1])).get_tool_info(TOOL_TYPE_COUNTDOWN) is None
