"""Tests for divoom_lib.tools.custom_art_push — wire-format builders + push flows.

These use a mock divoom (``send_command = AsyncMock``) so no BLE is needed.
The pure helper functions (``_le16``, ``_le32``, ``build_*``) are tested
without any mock at all.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from divoom_lib.tools.custom_art_push import (
    _le16,
    _le32,
    SLOTS_PER_PAGE,
    CHUNK_SIZE,
    build_n2_header,
    build_data_packets,
    build_k0,
    push_page,
    push_slot,
    query_page,
)

# ── helpers ──────────────────────────────────────────────────────────────────

class TestHelpers:
    def test_le16_zero(self):
        assert _le16(0) == [0x00, 0x00]

    def test_le16_byte(self):
        assert _le16(0xFF) == [0xFF, 0x00]

    def test_le16_word(self):
        assert _le16(0x1234) == [0x34, 0x12]

    def test_le32_zero(self):
        assert _le32(0) == [0x00, 0x00, 0x00, 0x00]

    def test_le32_dword(self):
        assert _le32(0x12345678) == [0x78, 0x56, 0x34, 0x12]


# ── N2 header ────────────────────────────────────────────────────────────────

class TestBuildN2Header:
    def test_old_mode(self):
        cmd, args = build_n2_header(0, total_encoded_len=None)
        assert cmd == 0xB1
        assert args == [0x00, 0x00, 0x00]

    def test_old_mode_page_2(self):
        cmd, args = build_n2_header(2)
        assert cmd == 0xB1
        assert args == [0x00, 0x00, 0x02]

    def test_new_mode(self):
        cmd, args = build_n2_header(1, total_encoded_len=4096)
        assert cmd == 0x8C
        # [0x00] + le32(4096) + [page]
        assert args == [0x00, 0x00, 0x10, 0x00, 0x00, 0x01]

    def test_new_mode_zero_len(self):
        cmd, args = build_n2_header(0, total_encoded_len=0)
        assert cmd == 0x8C
        assert args == [0x00, 0x00, 0x00, 0x00, 0x00, 0x00]


# ── Data packets ─────────────────────────────────────────────────────────────

class TestBuildDataPackets:
    def test_old_single_chunk(self):
        blob = bytes([i % 256 for i in range(100)])
        packets = build_data_packets(blob, total_len=100, use_new_mode=False)
        assert len(packets) == 1
        cmd, args = packets[0]
        assert cmd == 0xB1
        # header: [0x01] + le16(100) + 100 bytes
        assert args[:3] == [0x01, 100, 0x00]
        assert args[3:] == list(range(100))

    def test_old_multi_chunk(self):
        blob = bytes([i % 256 for i in range(300)])
        packets = build_data_packets(blob, total_len=300, use_new_mode=False)
        assert len(packets) == 2
        # chunk 0: 256 bytes, header = [0x01] + le16(256)
        cmd0, args0 = packets[0]
        assert cmd0 == 0xB1
        assert args0[:3] == [0x01, 0x00, 0x01]  # le16(256) = [0, 1]
        assert len(args0[3:]) == 256
        # chunk 1: 44 bytes, header = [0x01] + le16(44)
        cmd1, args1 = packets[1]
        assert args1[:3] == [0x01, 44, 0x00]
        assert len(args1[3:]) == 44

    def test_old_exact_chunk(self):
        blob = bytes([i % 256 for i in range(CHUNK_SIZE)])
        packets = build_data_packets(blob, total_len=CHUNK_SIZE, use_new_mode=False)
        assert len(packets) == 1
        assert len(packets[0][1][3:]) == CHUNK_SIZE

    def test_new_single_chunk(self):
        blob = bytes([i % 256 for i in range(100)])
        packets = build_data_packets(blob, total_len=200, use_new_mode=True)
        assert len(packets) == 1
        cmd, args = packets[0]
        assert cmd == 0x8C
        # [0x01] + le32(200) + le16(0) + blob
        assert args[:7] == [0x01, 200 & 0xFF, (200 >> 8) & 0xFF, 0, 0, 0, 0]
        assert args[7:] == [i % 256 for i in range(100)]

    def test_new_multi_chunk(self):
        blob = bytes([i % 256 for i in range(300)])
        packets = build_data_packets(blob, total_len=300, use_new_mode=True)
        assert len(packets) == 2
        cmd0, args0 = packets[0]
        assert cmd0 == 0x8C
        assert args0[:7] == [0x01, 44, 1, 0, 0, 0, 0]  # idx=0 LE
        assert len(args0[7:]) == 256
        cmd1, args1 = packets[1]
        assert args1[:7] == [0x01, 44, 1, 0, 0, 1, 0]  # idx=1 LE
        assert len(args1[7:]) == 44


# ── K0 end signal ────────────────────────────────────────────────────────────

class TestBuildK0:
    def test_old_mode(self):
        cmd, args = build_k0(use_new_mode=False)
        assert cmd == 0xB1
        assert args == [0x02]

    def test_new_mode(self):
        cmd, args = build_k0(use_new_mode=True)
        assert cmd == 0x8C
        assert args == [0x02]


# ── push_page (integration-style with mock divoom) ───────────────────────────

@pytest.fixture
def mock_divoom():
    d = AsyncMock()
    d.send_command = AsyncMock(return_value=True)
    return d


class TestPushPage:
    async def _assert_flow(self, divoom, expected_calls):
        """Assert send_command was called with the expected (cmd, args) sequence."""
        assert divoom.send_command.call_count == len(expected_calls), (
            f"expected {len(expected_calls)} calls, got {divoom.send_command.call_count}"
        )
        for i, (exp_cmd, exp_args) in enumerate(expected_calls):
            call = divoom.send_command.call_args_list[i]
            assert call.args[0] == exp_cmd, f"call {i}: expected cmd 0x{exp_cmd:02x}"
            # compare args as lists
            actual = list(call.args[1]) if call.args[1] else []
            assert actual == exp_args, f"call {i}: args mismatch"

    @pytest.mark.asyncio
    async def test_push_page_old_mode(self, mock_divoom):
        frames = [bytes(range(i * 10, (i + 1) * 10)) for i in range(12)]
        result = await push_page(mock_divoom, page=0, encoded_frames=frames, use_new_mode=False)
        assert result is True
        # expected: N2 header + 1 data chunk + K0
        assert mock_divoom.send_command.call_count == 3
        n2_call = mock_divoom.send_command.call_args_list[0]
        assert n2_call.args[0] == 0xB1  # old mode
        k0_call = mock_divoom.send_command.call_args_list[-1]
        assert k0_call.args[1] == [0x02]

    @pytest.mark.asyncio
    async def test_push_page_new_mode(self, mock_divoom):
        frames = [bytes(range(i * 10, (i + 1) * 10)) for i in range(12)]
        result = await push_page(mock_divoom, page=1, encoded_frames=frames, use_new_mode=True)
        assert result is True
        assert mock_divoom.send_command.call_count == 3
        n2_call = mock_divoom.send_command.call_args_list[0]
        assert n2_call.args[0] == 0x8C  # new mode
        k0_call = mock_divoom.send_command.call_args_list[-1]
        assert k0_call.args[1] == [0x02]

    @pytest.mark.asyncio
    async def test_push_page_fails_on_n2(self, mock_divoom):
        mock_divoom.send_command.return_value = False
        result = await push_page(mock_divoom, page=0, encoded_frames=[b"data"] * 12)
        assert result is False
        assert mock_divoom.send_command.call_count == 1  # only N2 sent

    @pytest.mark.asyncio
    async def test_push_page_fails_on_data(self, mock_divoom):
        call_count = 0

        async def side_effect(cmd, args):
            nonlocal call_count
            call_count += 1
            return call_count <= 1

        mock_divoom.send_command.side_effect = side_effect
        result = await push_page(mock_divoom, page=0, encoded_frames=[b"data"] * 12)
        assert result is False

    @pytest.mark.asyncio
    async def test_push_page_fails_on_k0(self, mock_divoom):
        call_count = 0
        total_calls = 2  # N2 + 1 data chunk

        async def side_effect(cmd, args):
            nonlocal call_count
            call_count += 1
            return call_count <= total_calls  # fail on the 3rd call (K0)

        mock_divoom.send_command.side_effect = side_effect
        result = await push_page(mock_divoom, page=0, encoded_frames=[b"data"] * 12)
        assert result is False

    @pytest.mark.asyncio
    async def test_push_page_empty_frames(self, mock_divoom):
        result = await push_page(mock_divoom, page=0, encoded_frames=[])
        assert result is True  # empty page: N2 + K0 (no data chunks)
        assert mock_divoom.send_command.call_count == 2


# ── push_slot ────────────────────────────────────────────────────────────────

class TestPushSlot:
    @pytest.mark.asyncio
    async def test_push_slot_specific(self, mock_divoom):
        frame = bytes(range(50))
        result = await push_slot(mock_divoom, page=0, slot=3, encoded_frame=frame)
        assert result is True
        # should have pushed 12 frames (1 real + 11 empty)
        assert mock_divoom.send_command.call_count >= 2  # at least N2 + K0

    @pytest.mark.asyncio
    async def test_push_slot_auto_assign(self, mock_divoom):
        frame = bytes(range(50))
        result = await push_slot(mock_divoom, page=0, slot=None, encoded_frame=frame)
        assert result is True

    @pytest.mark.asyncio
    async def test_push_slot_with_existing(self, mock_divoom):
        existing = [b"existing"] * SLOTS_PER_PAGE
        frame = bytes(range(50))
        result = await push_slot(
            mock_divoom, page=1, slot=5, encoded_frame=frame, existing_frames=existing
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_push_slot_pads_partial(self, mock_divoom):
        existing = [b"a", b"b"]  # only 2 frames
        frame = bytes(range(50))
        result = await push_slot(
            mock_divoom, page=0, slot=2, encoded_frame=frame, existing_frames=existing
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_push_slot_out_of_range(self, mock_divoom):
        frame = bytes(range(50))
        result = await push_slot(mock_divoom, page=0, slot=99, encoded_frame=frame)
        assert result is True  # auto-assigns to slot 0

    @pytest.mark.asyncio
    async def test_push_slot_old_mode(self, mock_divoom):
        frame = bytes(range(50))
        result = await push_slot(
            mock_divoom, page=0, slot=0, encoded_frame=frame, use_new_mode=False
        )
        assert result is True
        n2_call = mock_divoom.send_command.call_args_list[0]
        assert n2_call.args[0] == 0xB1

    @pytest.mark.asyncio
    async def test_push_slot_all_filled_auto_assign(self, mock_divoom):
        """When all 12 slots are occupied and slot=None, the auto-assign loop
        finds no empty slot and falls through — pushes the existing page."""
        existing = [b"occupied"] * SLOTS_PER_PAGE
        frame = bytes([i % 256 for i in range(50)])
        result = await push_slot(
            mock_divoom, page=0, slot=None, encoded_frame=frame,
            existing_frames=existing,
        )
        assert result is True
        # push_page was called; the new frame was NOT inserted (no slot found)
        assert mock_divoom.send_command.call_count >= 2


# ── query_page ───────────────────────────────────────────────────────────────

class TestQueryPage:
    @pytest.fixture
    def mock_divoom_with_response(self):
        d = AsyncMock()
        d.send_command_and_wait_for_response = AsyncMock()
        return d

    @pytest.mark.asyncio
    async def test_query_type1_with_ids(self, mock_divoom_with_response):
        # type=1 response with 3 slot IDs: [0x01, page=0, total=3, cur=0, count=3, id1:4, id2:4, id3:4]
        response = bytes([
            0x01, 0x00,  # type=1, page=0
            0x03, 0x00,  # total_count=3 LE
            0x00, 0x00,  # cur_seq=0
            0x03, 0x00,  # item_count=3 LE
            0x01, 0x00, 0x00, 0x00,  # id=1
            0x02, 0x00, 0x00, 0x00,  # id=2
            0x03, 0x00, 0x00, 0x00,  # id=3
        ])
        mock_divoom_with_response.send_command_and_wait_for_response.return_value = response
        ids = await query_page(mock_divoom_with_response, page=0)
        assert ids == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_query_type2_empty(self, mock_divoom_with_response):
        # type=2 = end-of-page, no items
        response = bytes([0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        mock_divoom_with_response.send_command_and_wait_for_response.return_value = response
        ids = await query_page(mock_divoom_with_response, page=0)
        assert ids == []

    @pytest.mark.asyncio
    async def test_query_short_response(self, mock_divoom_with_response):
        mock_divoom_with_response.send_command_and_wait_for_response.return_value = bytes([0x01, 0x00])
        ids = await query_page(mock_divoom_with_response, page=0)
        assert ids is None

    @pytest.mark.asyncio
    async def test_query_returns_none(self, mock_divoom_with_response):
        mock_divoom_with_response.send_command_and_wait_for_response.return_value = None
        ids = await query_page(mock_divoom_with_response, page=1)
        assert ids is None

    @pytest.mark.asyncio
    async def test_query_passes_bounded_timeout(self, mock_divoom_with_response):
        """0x8E read-back must use the bounded QUERY_TIMEOUT, not the 10s default —
        a device that never answers (HW-verified: Pixoo) must not wedge the
        serialized command queue for 10s. Default and explicit override both apply."""
        from divoom_lib.tools.custom_art_push import QUERY_TIMEOUT
        mock_divoom_with_response.send_command_and_wait_for_response.return_value = None
        await query_page(mock_divoom_with_response, page=0)
        _, kwargs = mock_divoom_with_response.send_command_and_wait_for_response.call_args
        assert kwargs.get("timeout") == QUERY_TIMEOUT
        assert QUERY_TIMEOUT < 10.0

        await query_page(mock_divoom_with_response, page=0, timeout=1.5)
        _, kwargs = mock_divoom_with_response.send_command_and_wait_for_response.call_args
        assert kwargs.get("timeout") == 1.5

    @pytest.mark.asyncio
    async def test_query_page_unexpected_type(self, mock_divoom_with_response):
        """type=0x03 (neither data nor end) → returns None."""
        response = bytes([0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        mock_divoom_with_response.send_command_and_wait_for_response.return_value = response
        ids = await query_page(mock_divoom_with_response, page=0)
        assert ids is None

    @pytest.mark.asyncio
    async def test_query_page_truncated_ids(self, mock_divoom_with_response):
        """Response claims 5 IDs but only has 3 → returns only 3 without crashing."""
        # type=1, page=0, total=5, cur=0, count=5, but only 3×4=12 bytes of IDs
        response = bytes([
            0x01, 0x00,  # type=1, page=0
            0x05, 0x00,  # total_count=5
            0x00, 0x00,  # cur_seq=0
            0x05, 0x00,  # item_count=5
            0x01, 0x00, 0x00, 0x00,  # id=1
            0x02, 0x00, 0x00, 0x00,  # id=2
            0x03, 0x00, 0x00, 0x00,  # id=3 (only 12 bytes, not 20)
        ])
        mock_divoom_with_response.send_command_and_wait_for_response.return_value = response
        ids = await query_page(mock_divoom_with_response, page=0)
        assert ids == [1, 2, 3]
