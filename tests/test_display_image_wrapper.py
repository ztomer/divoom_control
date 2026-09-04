"""Unit tests for divoom_lib.display.Display.display_image.

The wrapper is a thin layer over show_image + optional get_work_mode
polling. These tests mock the underlying methods so they run without
hardware. Live-device verification is in
`tests/test_push_protocol_diagnostic.py` (--run-hardware).
"""

import asyncio
import logging
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from divoom_lib.display import Display

# Add repo root to sys.path so divoom_lib imports resolve in CI.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Constants (no magic numbers) ─────────────────────────────────────

# A 16x16 test image's expected byte signature for the
# `display_image` push: just verify a file is sent, the wrapper
# shouldn't decode it (show_image does that).
TEST_IMAGE_SIDE = 16
TEST_IMAGE_COLOR_RGB = (255, 0, 0)

# Work mode constants (Divoom LIGHT_MODE enum from APK).
WORK_MODE_DESIGN = 0x05  # SOUND_USER = design / custom art
WORK_MODE_CLOCK = 0x00

# Polling params.
POLL_TIMEOUT_S_DEFAULT = 2.0
POLL_INTERVAL_S_DEFAULT = 0.2


# ── Fixtures ─────────────────────────────────────────────────────────


def _make_test_image(path: str) -> None:
    """Write a known-good 16x16 solid-color PNG to disk."""
    img = Image.new("RGB", (TEST_IMAGE_SIDE, TEST_IMAGE_SIDE), TEST_IMAGE_COLOR_RGB)
    img.save(path)


@pytest.fixture
def mock_communicator() -> MagicMock:
    """A MagicMock that quacks like the divoom_lib Divoom class.

    Display.__init__ expects a CommandSender with .send_command,
    .send_command_and_wait_for_response, .lan, .logger, .chunksize.
    """
    comm = MagicMock()
    comm.chunksize = 200
    comm.lan = None
    comm.logger = logging.getLogger("test_display_image")
    return comm


@pytest.fixture
def display(mock_communicator: MagicMock) -> Display:
    return Display(mock_communicator)


@pytest.fixture
def test_image(tmp_path) -> str:
    path = str(tmp_path / "test_divoom.png")
    _make_test_image(path)
    return path


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_display_image_calls_show_image(display: Display, test_image: str) -> None:
    """display_image() is a thin alias for show_image; verify it's called once."""
    with patch.object(display, "show_image", new=AsyncMock(return_value=True)) as mock_show:
        result = await display.display_image(test_image)
    assert result is True
    mock_show.assert_awaited_once_with(test_image, time=None)


@pytest.mark.asyncio
async def test_display_image_returns_false_when_show_image_fails(
    display: Display, test_image: str
) -> None:
    """If the underlying push fails, display_image() returns False without polling."""
    with patch.object(display, "show_image", new=AsyncMock(return_value=False)) as mock_show, \
         patch.object(display, "_get_work_mode", new=AsyncMock(return_value=WORK_MODE_DESIGN)) as mock_mode:
        result = await display.display_image(test_image, wait_for_display=True)
    assert result is False
    mock_show.assert_awaited_once()
    # _get_work_mode should NOT have been called (early return on push failure).
    mock_mode.assert_not_awaited()


@pytest.mark.asyncio
async def test_display_image_wait_for_display_polls_until_mode_matches(
    display: Display, test_image: str
) -> None:
    """wait_for_display=True polls get_work_mode until device reports design channel."""
    mode_sequence = [WORK_MODE_CLOCK, WORK_MODE_CLOCK, WORK_MODE_DESIGN]

    async def fake_get_work_mode() -> int:
        if mode_sequence:
            return mode_sequence.pop(0)
        return WORK_MODE_DESIGN

    with patch.object(display, "show_image", new=AsyncMock(return_value=True)), \
         patch.object(display, "_get_work_mode", new=AsyncMock(side_effect=fake_get_work_mode)):
        result = await display.display_image(test_image, wait_for_display=True, poll_timeout_s=2.0)
    assert result is True


@pytest.mark.asyncio
async def test_display_image_wait_for_display_times_out(
    display: Display, test_image: str
) -> None:
    """If the device never reports the design channel, return False after timeout."""
    async def always_clock() -> int:
        return WORK_MODE_CLOCK

    with patch.object(display, "show_image", new=AsyncMock(return_value=True)), \
         patch.object(display, "_get_work_mode", new=AsyncMock(side_effect=always_clock)):
        # Short timeout so the test is fast.
        result = await display.display_image(test_image, wait_for_display=True, poll_timeout_s=0.5)
    assert result is False


@pytest.mark.asyncio
async def test_display_image_passes_time_kwarg_to_show_image(
    display: Display, test_image: str
) -> None:
    """The `time` argument is forwarded to show_image for animation frame timing."""
    with patch.object(display, "show_image", new=AsyncMock(return_value=True)) as mock_show:
        result = await display.display_image(test_image, time=500)
    assert result is True
    mock_show.assert_awaited_once_with(test_image, time=500)


@pytest.mark.asyncio
async def test_get_work_mode_returns_byte_from_response(display: Display) -> None:
    """_get_work_mode parses the first byte of the response payload."""
    display.communicator.send_command_and_wait_for_response = AsyncMock(
        return_value=bytes([WORK_MODE_DESIGN, 0x00, 0xFF])
    )
    mode = await display._get_work_mode()
    assert mode == WORK_MODE_DESIGN


@pytest.mark.asyncio
async def test_get_work_mode_returns_none_on_empty_response(display: Display) -> None:
    """_get_work_mode returns None if the device doesn't respond."""
    display.communicator.send_command_and_wait_for_response = AsyncMock(return_value=None)
    mode = await display._get_work_mode()
    assert mode is None


@pytest.mark.asyncio
async def test_get_work_mode_returns_none_on_exception(display: Display) -> None:
    """_get_work_mode swallows exceptions and returns None (used in polling loop)."""
    display.communicator.send_command_and_wait_for_response = AsyncMock(
        side_effect=Exception("BLE error")
    )
    mode = await display._get_work_mode()
    assert mode is None


@pytest.mark.asyncio
async def test_get_work_mode_uses_lan_when_present(display: Display) -> None:
    """_get_work_mode routes through communicator.lan.get_work_mode() for LAN devices."""
    display.communicator.lan = MagicMock()
    display.communicator.lan.get_work_mode = AsyncMock(return_value=WORK_MODE_DESIGN)
    mode = await display._get_work_mode()
    assert mode == WORK_MODE_DESIGN
    display.communicator.lan.get_work_mode.assert_awaited_once()


@pytest.mark.asyncio
async def test_display_image_polling_loop_survives_get_work_mode_exception(
    display: Display, test_image: str
) -> None:
    """R61: display_image's own polling loop wraps `self._get_work_mode()` in a
    try/except (distinct from `_get_work_mode`'s internal exception handling) —
    a transient failure mid-poll must not abort the wait, and the loop should
    recover and succeed once a later poll reports the design channel."""
    call_count = 0

    async def flaky_then_ok() -> int:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("transient BLE hiccup")
        return WORK_MODE_DESIGN

    with patch.object(display, "show_image", new=AsyncMock(return_value=True)), \
         patch.object(display, "_get_work_mode", new=AsyncMock(side_effect=flaky_then_ok)), \
         patch("divoom_lib.display.asyncio.sleep", new=AsyncMock()):
        result = await display.display_image(test_image, wait_for_display=True, poll_timeout_s=2.0)
    assert result is True
    assert call_count >= 2
