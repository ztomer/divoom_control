"""Round 11 (items 1c/2a/9): Animation.stream_animation_8b.

Verifies the 0x8B 3-phase streamer matches the futpib reference: a sequential
chunk-INDEX offset_id (0,1,2,…) with 256-byte chunks, sent as start + N data +
terminate. The chunk size MUST be 256 — the device places chunk N at byte N*256,
so the monthly-best daemon's 200-byte chunks left gaps and stalled the device.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from divoom_lib.models import (
    COMMANDS,
    ANSGC_CONTROL_START_SENDING,
    ANSGC_CONTROL_SENDING_DATA,
    ANSGC_CONTROL_TERMINATE_SENDING,
)
from divoom_lib.display.animation import Animation


def _make_anim():
    comm = MagicMock()
    comm.logger = MagicMock()
    comm.lan = None
    comm.use_spp = False
    comm.send_command = AsyncMock(return_value=True)
    # R34 §1b: by default the fake device never replies on 0x8b — the streamer
    # must fall back to the legacy fixed-sleep flow (APK ACK-gating is optional).
    comm.wait_for_response = AsyncMock(return_value=None)
    return Animation(comm), comm


@pytest.mark.asyncio
async def test_stream_phases_and_chunk_index_offsets():
    anim, comm = _make_anim()
    blob = bytes(range(256)) * 2 + bytes(50)  # 562 bytes → ceil(562/256) = 3 chunks
    with patch("divoom_lib.display.animation.asyncio.sleep", new=AsyncMock()):
        ok = await anim.stream_animation_8b(blob)
    assert ok is True

    calls = [c for c in comm.send_command.await_args_list
             if c.args and c.args[0] == COMMANDS["app new send gif cmd"]]
    # start + 3 data (APK does NOT send terminate — R35d)
    assert len(calls) == 4
    control_words = [c.args[1][0] for c in calls]
    assert control_words[0] == ANSGC_CONTROL_START_SENDING
    assert all(cw == ANSGC_CONTROL_SENDING_DATA for cw in control_words[1:])

    # data phases: args = [CW, fs(4 LE), offset_id(2 LE), *chunk]
    data_calls = calls[1:]
    offset_ids = [int.from_bytes(bytes(c.args[1][5:7]), "little") for c in data_calls]
    assert offset_ids == [0, 1, 2], "offset_id must be a sequential chunk index"
    # First two chunks must be the full 256 bytes (chunk N lands at byte N*256).
    assert len(data_calls[0].args[1]) == 1 + 4 + 2 + 256
    assert len(data_calls[1].args[1]) == 1 + 4 + 2 + 256
    assert len(data_calls[2].args[1]) == 1 + 4 + 2 + 50


@pytest.mark.asyncio
async def test_stream_empty_blob_returns_false():
    anim, comm = _make_anim()
    with patch("divoom_lib.display.animation.asyncio.sleep", new=AsyncMock()):
        assert await anim.stream_animation_8b(b"") is False
    comm.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_stream_aborts_on_chunk_failure():
    anim, comm = _make_anim()
    # start ok, first data chunk fails
    comm.send_command = AsyncMock(side_effect=[True, False])
    with patch("divoom_lib.display.animation.asyncio.sleep", new=AsyncMock()):
        ok = await anim.stream_animation_8b(bytes(300))
    assert ok is False


# ── R34 §1b: APK-aligned device-driven flow ──────────────────────────────


@pytest.mark.asyncio
async def test_stream_waits_for_start_ack_before_chunks():
    """APK: after START, the device replies [0] ('send the animation') and only
    then does the app stream chunks (bluetooth/s.java → startSendAllAni)."""
    anim, comm = _make_anim()
    order = []
    comm.send_command = AsyncMock(side_effect=lambda *a, **k: order.append(("send", a[1][0])) or True)
    comm.wait_for_response = AsyncMock(side_effect=lambda *a, **k: order.append(("wait",)) or bytes([0]))
    with patch("divoom_lib.display.animation.asyncio.sleep", new=AsyncMock()):
        # quiet retransmit phase: after the ready ACK, subsequent waits go quiet
        comm.wait_for_response.side_effect = [bytes([0]), None]
        ok = await anim.stream_animation_8b(bytes(300))
    assert ok is True
    assert comm.wait_for_response.await_count >= 1
    # The ready wait targets the 0x8b command id.
    assert comm.wait_for_response.await_args_list[0].args[0] == COMMANDS["app new send gif cmd"]


@pytest.mark.asyncio
async def test_stream_serves_retransmit_requests():
    """APK: the device may reply [1][idx:2 LE] requesting chunk idx again
    (bluetooth/s.java → resendBlueData). The streamer must re-send that chunk."""
    anim, comm = _make_anim()
    blob = bytes(range(256)) * 2 + bytes(50)  # 3 chunks
    # ready ACK, then one retransmit request for chunk 1, then quiet
    comm.wait_for_response = AsyncMock(side_effect=[bytes([0]), bytes([1, 1, 0]), None])
    with patch("divoom_lib.display.animation.asyncio.sleep", new=AsyncMock()):
        ok = await anim.stream_animation_8b(blob)
    assert ok is True
    data_calls = [c for c in comm.send_command.await_args_list
                  if c.args and c.args[0] == COMMANDS["app new send gif cmd"]
                  and c.args[1][0] == ANSGC_CONTROL_SENDING_DATA]
    offset_ids = [int.from_bytes(bytes(c.args[1][5:7]), "little") for c in data_calls]
    assert offset_ids == [0, 1, 2, 1], "chunk 1 must be re-sent on request"
    # The retransmitted chunk carries the same bytes as the original.
    assert data_calls[3].args[1][7:] == data_calls[1].args[1][7:]


@pytest.mark.asyncio
async def test_stream_falls_back_when_device_never_acks():
    """No 0x8b reply at all (older firmware / LAN): the streamer must still
    complete via the legacy fixed-sleep flow."""
    anim, comm = _make_anim()  # wait_for_response → None
    with patch("divoom_lib.display.animation.asyncio.sleep", new=AsyncMock()):
        ok = await anim.stream_animation_8b(bytes(300))
    assert ok is True
    calls = [c for c in comm.send_command.await_args_list
             if c.args and c.args[0] == COMMANDS["app new send gif cmd"]]
    assert len(calls) == 3  # start + 2 data, no terminate (R35d), no retransmits


@pytest.mark.asyncio
async def test_stream_clears_expected_response_command_on_failure():
    """R53.23: the 0x8B streamer sets communicator._expected_response_command before
    START. On the device-ready-timeout + chunk-failure path it used to leave it
    pinned to 0x8B, mis-routing the NEXT op's notifications (cross-talk). A
    try/finally must always clear it."""
    anim, comm = _make_anim()
    comm._expected_response_command = None              # real BLE-path attribute
    comm.wait_for_response = AsyncMock(return_value=None)   # device never ACKs ready
    comm.send_command = AsyncMock(side_effect=[True, False])  # start ok, chunk fails
    with patch("divoom_lib.display.animation.asyncio.sleep", new=AsyncMock()):
        ok = await anim.stream_animation_8b(bytes(300))
    assert ok is False
    assert comm._expected_response_command is None, "scalar leaked after failed stream"


@pytest.mark.asyncio
async def test_stream_clears_expected_response_command_on_success():
    anim, comm = _make_anim()
    comm._expected_response_command = None
    comm.wait_for_response = AsyncMock(return_value=None)   # falls back to sleep
    with patch("divoom_lib.display.animation.asyncio.sleep", new=AsyncMock()):
        ok = await anim.stream_animation_8b(bytes(300))
    assert ok is True
    assert comm._expected_response_command is None, "scalar leaked after successful stream"


# ── R53.x HW: 0x8B retransmit dead-path fix ──────────────────────────────────


@pytest.mark.asyncio
async def test_stream_listens_for_0x8b_during_stream_and_cleans_up():
    """The retransmit window runs with _expected_response_command == None (the
    start-ACK wait cleared it). Without 0x8B in _listen_commands the real handler
    DROPS every unsolicited retransmit request, so the streamer must LISTEN for
    0x8B for the stream's duration and remove it afterward.

    Teeth: drop the `_listen.add(...)` and seen_during is all-False; drop the
    `_listen.discard(...)` and 0x8B leaks into _listen_commands after the stream."""
    cmd8b = COMMANDS["app new send gif cmd"]
    comm = MagicMock()
    comm.logger = MagicMock()
    comm.lan = None
    comm.use_spp = False
    comm.send_command = AsyncMock(return_value=True)
    comm._expected_response_command = None
    comm._listen_commands = set()  # a REAL set so the fix engages (isinstance check)

    seen_during = []

    async def _wait(cmd, timeout):
        seen_during.append(cmd8b in comm._listen_commands)
        return None  # device quiet → ready-wait falls back, retransmit phase ends

    comm.wait_for_response = _wait
    anim = Animation(comm)
    with patch("divoom_lib.display.animation.asyncio.sleep", new=AsyncMock()):
        ok = await anim.stream_animation_8b(bytes(300))
    assert ok is True
    assert any(seen_during), "0x8B must be in _listen_commands DURING the stream"
    assert cmd8b not in comm._listen_commands, "0x8B must be removed after the stream"


def test_listened_0x8b_retransmit_queues_without_consuming_scalar():
    """The mechanism the fix relies on: with the scalar cleared mid-stream, a 0x8B
    frame survives ONLY because it's in _listen_commands (the handler is_listened
    branch queues it without touching the scalar). Not-listening = dropped = the bug."""
    import asyncio
    import logging
    from divoom_lib.ble_notify import BleNotifyMixin
    from divoom_lib import framing

    cmd8b = COMMANDS["app new send gif cmd"]
    frame = bytes(framing.encode_ios_le_payload([cmd8b, 0x01, 0x05, 0x00]))  # "resend chunk 5"

    def _mk(listen):
        o = object.__new__(BleNotifyMixin)
        o._expected_response_command = None  # cleared by the start-ACK wait
        o.notification_queue = asyncio.Queue()
        o._listen_commands = listen
        o.use_ios_le_protocol = True
        o.logger = logging.getLogger("t8b")
        return o

    listening = _mk({cmd8b})
    listening._handle_ios_le_notification(frame)
    assert listening.notification_queue.qsize() == 1, "listened 0x8B must be queued"
    assert listening._expected_response_command is None, "listening must not touch the scalar"

    # teeth: not listening → the retransmit request is silently dropped (the bug)
    not_listening = _mk(set())
    not_listening._handle_ios_le_notification(frame)
    assert not_listening.notification_queue.qsize() == 0


# ── R61 coverage push: set_gif_speed / set_light_phone_gif ───────────────────


@pytest.mark.asyncio
async def test_set_gif_speed_sends_le_speed():
    anim, comm = _make_anim()
    result = await anim.set_gif_speed(300)
    assert result is True
    cmd, args = comm.send_command.await_args_list[-1].args
    assert cmd == COMMANDS["set gif speed"]
    assert args == list((300).to_bytes(2, byteorder='little'))


@pytest.mark.asyncio
async def test_set_light_phone_gif_builds_expected_payload():
    anim, comm = _make_anim()
    result = await anim.set_light_phone_gif(total_len=10, gif_id=2, gif_data=[1, 2, 3])
    assert result is True
    cmd, args = comm.send_command.await_args_list[-1].args
    assert cmd == COMMANDS["set light phone gif"]
    expected = list((10).to_bytes(2, byteorder='little')) + [2] + [1, 2, 3]
    assert args == expected


# ── R61 coverage push: app_new_send_gif_cmd handler error/edge paths ─────────


@pytest.mark.asyncio
async def test_app_new_send_gif_cmd_start_sending_missing_file_size():
    anim, comm = _make_anim()
    result = await anim.app_new_send_gif_cmd(control_word=ANSGC_CONTROL_START_SENDING)
    assert result is False
    comm.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_app_new_send_gif_cmd_sending_data_missing_params():
    anim, comm = _make_anim()
    result = await anim.app_new_send_gif_cmd(
        control_word=ANSGC_CONTROL_SENDING_DATA, file_size=10
    )
    assert result is False
    comm.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_app_new_send_gif_cmd_terminate_sending():
    anim, comm = _make_anim()
    result = await anim.app_new_send_gif_cmd(control_word=ANSGC_CONTROL_TERMINATE_SENDING)
    assert result is True
    cmd, args = comm.send_command.await_args_list[-1].args
    assert cmd == COMMANDS["app new send gif cmd"]
    assert args == [ANSGC_CONTROL_TERMINATE_SENDING]


@pytest.mark.asyncio
async def test_app_new_send_gif_cmd_unknown_control_word():
    anim, comm = _make_anim()
    result = await anim.app_new_send_gif_cmd(control_word=0xFF)
    assert result is False
    comm.send_command.assert_not_called()


# ── R61 coverage push: stream_animation_8b non-BLE (LAN/SPP) branch ──────────


@pytest.mark.asyncio
async def test_stream_animation_8b_lan_transport_skips_ble_only_steps():
    """When comm.lan is set, is_ble is False: no start-ACK wait, no listen-set
    bookkeeping, no retransmit serving, and the finally block skips clearing
    the (nonexistent) BLE-only scalar."""
    comm = MagicMock()
    comm.logger = MagicMock()
    comm.lan = MagicMock()  # non-None -> is_lan True -> is_ble False
    comm.use_spp = False
    comm.send_command = AsyncMock(return_value=True)
    comm.wait_for_response = AsyncMock(return_value=None)
    anim = Animation(comm)
    with patch("divoom_lib.display.animation.asyncio.sleep", new=AsyncMock()):
        ok = await anim.stream_animation_8b(bytes(300))
    assert ok is True
    comm.wait_for_response.assert_not_awaited()


# ── R61 coverage push: start phase failure ───────────────────────────────────


@pytest.mark.asyncio
async def test_stream_animation_8b_start_phase_failure_returns_false():
    anim, comm = _make_anim()
    comm.send_command = AsyncMock(return_value=False)  # start phase itself fails
    with patch("divoom_lib.display.animation.asyncio.sleep", new=AsyncMock()):
        ok = await anim.stream_animation_8b(bytes(300))
    assert ok is False


# ── R61 coverage push: _await_8b_device_ready direct tests ───────────────────


@pytest.mark.asyncio
async def test_await_8b_device_ready_no_wait_channel():
    anim, comm = _make_anim()
    comm.wait_for_response = None  # transport has no response channel
    assert await anim._await_8b_device_ready(timeout=1.0) is False


@pytest.mark.asyncio
async def test_await_8b_device_ready_times_out_on_non_matching_payloads():
    anim, comm = _make_anim()
    # Never a start-ACK (payload[0] != 0) -> loop keeps waiting until the real
    # clock exceeds the (tiny) timeout.
    comm.wait_for_response = AsyncMock(return_value=bytes([9, 0, 0]))
    assert await anim._await_8b_device_ready(timeout=0.05) is False


@pytest.mark.asyncio
async def test_await_8b_device_ready_ignores_non_ack_then_succeeds():
    anim, comm = _make_anim()
    comm.wait_for_response = AsyncMock(side_effect=[bytes([9]), bytes([0])])
    assert await anim._await_8b_device_ready(timeout=1.0) is True


# ── R61 coverage push: _serve_8b_retransmits direct tests ────────────────────


@pytest.mark.asyncio
async def test_serve_8b_retransmits_no_wait_channel_returns_immediately():
    anim, comm = _make_anim()
    comm.wait_for_response = None
    await anim._serve_8b_retransmits(bytes(300), 300, 256, False)
    # No exception, and nothing sent (function returned on the `wait is None` guard).
    comm.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_serve_8b_retransmits_swallows_wait_exception():
    anim, comm = _make_anim()
    comm.wait_for_response = AsyncMock(side_effect=Exception("BLE gone"))
    await anim._serve_8b_retransmits(bytes(300), 300, 256, False)
    comm.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_serve_8b_retransmits_ignores_non_retransmit_payload_then_stops():
    anim, comm = _make_anim()
    # payload[0] == 0 (late start-ACK) is neither a retransmit nor quiet -> the
    # fallthrough branch, then the next wait goes quiet.
    comm.wait_for_response = AsyncMock(side_effect=[bytes([0]), None])
    await anim._serve_8b_retransmits(bytes(300), 300, 256, False)
    comm.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_serve_8b_retransmits_skips_out_of_range_index():
    anim, comm = _make_anim()
    # idx=100 * chunk_size(256) >= file_size(300) -> out-of-range, `continue`.
    comm.wait_for_response = AsyncMock(
        side_effect=[bytes([1]) + (100).to_bytes(2, "little"), None]
    )
    await anim._serve_8b_retransmits(bytes(300), 300, 256, False)
    comm.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_serve_8b_retransmits_exhausts_max_requests_without_going_quiet():
    anim, comm = _make_anim()
    # Device always asks for chunk 0 retransmit; the safety valve (max_requests)
    # must end the loop by falling off the end, not by returning early.
    comm.wait_for_response = AsyncMock(return_value=bytes([1, 0, 0]))
    await anim._serve_8b_retransmits(bytes(300), 300, 256, False, max_requests=3)
    assert comm.send_command.await_count == 3


# ── R61 coverage push: set_rhythm_gif / app_send_eq_gif ──────────────────────


@pytest.mark.asyncio
async def test_set_rhythm_gif_builds_expected_payload():
    anim, comm = _make_anim()
    result = await anim.set_rhythm_gif(pos=1, total_length=10, gif_id=2, data=[9, 9])
    assert result is True
    cmd, args = comm.send_command.await_args_list[-1].args
    assert cmd == COMMANDS["set rhythm gif"]
    expected = [1] + list((10).to_bytes(2, byteorder='little')) + [2] + [9, 9]
    assert args == expected


@pytest.mark.asyncio
async def test_app_send_eq_gif_builds_expected_payload():
    anim, comm = _make_anim()
    result = await anim.app_send_eq_gif(pos=1, total_length=10, gif_id=2, data=[9, 9])
    assert result is True
    cmd, args = comm.send_command.await_args_list[-1].args
    assert cmd == COMMANDS["app send eq gif"]
    expected = [1] + list((10).to_bytes(2, byteorder='little')) + [2] + [9, 9]
    assert args == expected
