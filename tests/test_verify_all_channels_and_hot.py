import asyncio
import json
import sys
from pathlib import Path
import pytest

sys.path.append(str(Path(__file__).parent.parent / "scripts"))
from divoom_lib.divoom import Divoom
from divoom_lib import models, framing
from mock_device import MockBleakClient

MAC = "AA:BB:CC:DD:EE:FF"


async def _connected_divoom():
    mock = MockBleakClient(MAC)
    dev = Divoom(mac=MAC, client=mock, use_ios_le_protocol=False)
    await dev.connect()
    mock.written.clear()
    return dev, mock


def _decoded_frames(mock):
    out = []
    for _char, data in mock.written:
        msgs, _ = framing.parse_basic_protocol_frames(bytearray(data))
        out.extend(msgs)
    return out


@pytest.mark.asyncio
@pytest.mark.parametrize("channel_name,expected_mode_byte", [
    ("clock", 0x00),
    ("ambient", 0x01),
    ("lighting", 0x01),
    ("hot", 0x02),
    ("cloud", 0x02),
    ("vj", 0x03),
    ("visualizer", 0x04),
    ("eq", 0x04),
    ("design", 0x05),
    ("custom", 0x05),
    ("scoreboard", 0x06),
])
async def test_all_channels_dispatch_correct_wire_bytes(channel_name, expected_mode_byte):
    """Verify that every channel name switches the physical device via 0x45."""
    dev, mock = await _connected_divoom()
    ok = await dev.display.switch_channel(channel_name)
    assert ok is True, f"switch_channel('{channel_name}') returned False"

    frames = _decoded_frames(mock)
    cmds = [f["command_id"] for f in frames]
    assert models.COMMANDS["set light mode"] in cmds, (
        f"Channel '{channel_name}' did not emit 'set light mode' (0x45)"
    )

    cmd = next(f for f in frames if f["command_id"] == models.COMMANDS["set light mode"])
    payload = list(cmd["payload"])
    assert len(payload) >= 10, f"Payload must be padded to 10 bytes: {payload}"
    assert payload[0] == expected_mode_byte, (
        f"Channel '{channel_name}' expected byte {expected_mode_byte:#04x}, got {payload[0]:#04x}"
    )


@pytest.mark.asyncio
async def test_hot_channel_direct_switch_wire_bytes():
    """Verify that switching to the hot/cloud channel sends 0x45 [0x02]."""
    dev, mock = await _connected_divoom()
    ok = await dev.display.switch_channel("hot")
    assert ok is True
    frames = _decoded_frames(mock)
    cmd = next(f for f in frames if f["command_id"] == models.COMMANDS["set light mode"])
    assert cmd["payload"][0] == 0x02


@pytest.mark.asyncio
async def test_text_channel_pushes_frames():
    """Verify that pushing text renders and sends image display frames."""
    from PIL import Image
    dev, mock = await _connected_divoom()
    img = Image.new("RGB", (16, 16), color=(255, 0, 0))
    tmp_path = Path("/tmp/test_text_frame.png")
    img.save(tmp_path)
    ok = await dev.display.show_image(str(tmp_path))
    assert ok is True
    frames = _decoded_frames(mock)
    assert len(frames) > 0
    cmds = [f["command_id"] for f in frames]
    assert 0x8B in cmds, f"Expected 0x8B frame in {cmds}"
