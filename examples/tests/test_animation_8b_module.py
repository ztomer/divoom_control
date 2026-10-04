"""Unit tests for the module-level helpers and Animation8B class in
divoom_legacy.display.animation_8b (R61 coverage push).

test_apk_encoding_parity.py already covers the wire-format byte layout of
_phase_start/_phase_data/_phase_terminate and build_8b_phases' happy path.
These tests cover what that file doesn't: build_8b_phases' empty-input guard
and the Animation8B high-level `send()` wrapper (empty frames / all-phases-ok
/ mid-stream failure), which was entirely unexercised (0% on Animation8B).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from divoom_legacy.display.animation_8b import Animation8B, build_8b_phases, CONTROL_START_SENDING, CONTROL_SENDING_DATA, CONTROL_TERMINATE_SENDING
from divoom_lib.models import COMMANDS


def _one_frame():
    # One 16x16 RGB frame of zeroes: 16 * 16 * 3 = 768 bytes. This was
    # `np.zeros((16, 16, 3), dtype=np.uint8)` then `bytes(...)` -- numpy was
    # here ONLY to spell "768 zero bytes", it was the sole importer in the whole
    # tree, and numpy is a FORBIDDEN import in divoom_gui/
    # (tools/check_gui_is_a_client.py), so it was a declared dependency whose
    # only use is a construction the language spells for free.
    return [(bytes(16 * 16 * 3), 16, 16, 100)]


# ── build_8b_phases: empty input guard ───────────────────────────────────────


def test_build_8b_phases_empty_frames_returns_empty_list():
    assert build_8b_phases([]) == []


# ── Animation8B.send ──────────────────────────────────────────────────────────


def _make_animation8b():
    comm = MagicMock()
    comm.logger = MagicMock()
    comm.send_command = AsyncMock(return_value=True)
    return Animation8B(comm), comm


@pytest.mark.asyncio
async def test_animation8b_send_empty_frames_returns_false():
    anim8b, comm = _make_animation8b()
    result = await anim8b.send([])
    assert result is False
    comm.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_animation8b_send_all_phases_succeed():
    anim8b, comm = _make_animation8b()
    result = await anim8b.send(_one_frame())
    assert result is True
    # Every phase went through send_command with the 0x8B command id.
    for call in comm.send_command.await_args_list:
        assert call.args[0] == COMMANDS["app new send gif cmd"]
    control_words = [call.args[1][0] for call in comm.send_command.await_args_list]
    assert control_words[0] == CONTROL_START_SENDING
    assert control_words[-1] == CONTROL_TERMINATE_SENDING
    assert all(cw == CONTROL_SENDING_DATA for cw in control_words[1:-1])


@pytest.mark.asyncio
async def test_animation8b_send_returns_false_on_mid_stream_failure():
    anim8b, comm = _make_animation8b()
    # Start phase ok, first data phase fails.
    comm.send_command = AsyncMock(side_effect=[True, False])
    result = await anim8b.send(_one_frame())
    assert result is False


@pytest.mark.asyncio
async def test_animation8b_send_returns_false_when_start_phase_fails():
    anim8b, comm = _make_animation8b()
    comm.send_command = AsyncMock(return_value=False)
    result = await anim8b.send(_one_frame())
    assert result is False
    comm.send_command.assert_awaited_once()
