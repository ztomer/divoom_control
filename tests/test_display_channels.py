"""Unit tests for divoom_lib.display.Display channel-switching and light/
image plumbing (R61 coverage push).

Covers what test_display_functions.py (hardware-only) and
test_display_image_wrapper.py / test_show_clock_wire.py don't: the LAN
branches of every show_*/switch_channel method, the show_clock out-of-range
style branch, _set_work_mode, _get_screensize with a real cfg, and the
show_image 0x49 fallback path. Mocks the CommandSender/BLE boundary entirely.
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from divoom_lib.display import Display


@pytest.fixture
def mock_communicator() -> MagicMock:
    comm = MagicMock()
    comm.chunksize = 200
    comm.lan = None
    comm.logger = logging.getLogger("test_display_channels")
    return comm


@pytest.fixture
def display(mock_communicator: MagicMock) -> Display:
    return Display(mock_communicator)


@pytest.fixture
def test_image(tmp_path) -> str:
    path = str(tmp_path / "test_divoom_channels.png")
    Image.new("RGB", (16, 16), (0, 255, 0)).save(path)
    return path


# ── show_clock ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_show_clock_uses_lan_set_clock(display: Display) -> None:
    display.communicator.lan = MagicMock()
    display.communicator.lan.set_clock = AsyncMock()
    result = await display.show_clock(clock=3)
    assert result is True
    display.communicator.lan.set_clock.assert_awaited_once_with(3)


@pytest.mark.asyncio
async def test_show_clock_out_of_range_style_deactivates(display: Display) -> None:
    """clock outside 0-15 -> mode/style byte 0 and 'clock activated' False."""
    display.communicator.send_command = AsyncMock(return_value=True)
    display.communicator.convert_color = MagicMock(return_value=[1, 2, 3])
    result = await display.show_clock(clock=99)
    assert result is True
    args = display.communicator.send_command.await_args.args[1]
    # [FALSE(lan-flag placeholder), twentyfour, mode=0, activated=0, humidity, weather, date, R, G, B]
    assert args[2] == 0  # clock mode/style
    assert args[3] == 0  # clock deactivated


@pytest.mark.asyncio
async def test_show_clock_hot_mode(display: Display) -> None:
    display.communicator.send_command = AsyncMock(return_value=True)
    result = await display.show_clock(hot=True)
    assert result is True
    display.communicator.send_command.assert_awaited_once_with("set hot", [0x01])


# ── _set_work_mode ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_work_mode_without_sub_command(display: Display) -> None:
    display.communicator.send_command = AsyncMock(return_value=True)
    result = await display._set_work_mode(5)
    assert result is True
    display.communicator.send_command.assert_awaited_once_with("set work mode", [5])


@pytest.mark.asyncio
async def test_set_work_mode_with_sub_command_args(display: Display) -> None:
    display.communicator.send_command = AsyncMock(side_effect=[True, True])
    result = await display._set_work_mode(5, sub_command_args=[1, 2, 3])
    assert result is True
    assert display.communicator.send_command.await_count == 2
    display.communicator.send_command.assert_any_call("set work mode", [5])
    display.communicator.send_command.assert_any_call("set design", [1, 2, 3])


# ── show_design ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_show_design_uses_lan_set_channel(display: Display) -> None:
    display.communicator.lan = MagicMock()
    display.communicator.lan.set_channel = AsyncMock()
    result = await display.show_design()
    assert result is True
    display.communicator.lan.set_channel.assert_awaited_once_with(3)


# ── show_scoreboard ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_show_scoreboard_lan_success(display: Display) -> None:
    display.communicator.lan = MagicMock()
    display.communicator.lan.set_channel = AsyncMock()
    result = await display.show_scoreboard()
    assert result is True
    display.communicator.lan.set_channel.assert_awaited_once_with(6)


@pytest.mark.asyncio
async def test_show_scoreboard_lan_exception_returns_false(display: Display) -> None:
    display.communicator.lan = MagicMock()
    display.communicator.lan.set_channel = AsyncMock(side_effect=Exception("LAN down"))
    result = await display.show_scoreboard()
    assert result is False


# ── show_image fallback (0x49 chunked) path ──────────────────────────────


@pytest.mark.asyncio
async def test_show_image_falls_back_to_0x49_when_no_animation_attr(
    display: Display, test_image: str
) -> None:
    """No `.animation` attribute on the communicator (or it's explicitly None)
    -> skip the 0x8B path entirely and stream via 'set animation frame'."""
    display.communicator.animation = None
    display.communicator.cfg = None  # deterministic screensize=16 (avoid MagicMock int() quirk)
    display.communicator.send_command = AsyncMock(return_value=True)
    fake_packets = [bytes([1, 2, 3]), bytes([4, 5, 6])]
    with patch("divoom_lib.display.encode_animation", return_value=fake_packets):
        result = await display.show_image(test_image)
    assert result is True
    calls = [c for c in display.communicator.send_command.await_args_list
             if c.args and c.args[0] == "set animation frame"]
    assert len(calls) == 2
    assert calls[0].args[1] == [1, 2, 3]
    assert calls[1].args[1] == [4, 5, 6]


@pytest.mark.asyncio
async def test_show_image_fallback_stops_on_first_failed_packet(
    display: Display, test_image: str
) -> None:
    display.communicator.animation = None
    display.communicator.cfg = None
    # show_design's "set light mode" call must succeed; the two animation-frame
    # pushes are the ones under test (first ok, second fails).
    display.communicator.send_command = AsyncMock(side_effect=[True, True, False])
    fake_packets = [bytes([1]), bytes([2])]
    with patch("divoom_lib.display.encode_animation", return_value=fake_packets):
        result = await display.show_image(test_image)
    assert result is False
    calls = [c for c in display.communicator.send_command.await_args_list
             if c.args and c.args[0] == "set animation frame"]
    assert len(calls) == 2  # loop stopped after the failing packet, no 3rd attempt


@pytest.mark.asyncio
async def test_show_image_stream_8b_failure_falls_back_to_0x49(
    display: Display, test_image: str
) -> None:
    """When the 0x8B streamer is present but fails, show_image must fall back
    to the 0x49 chunked path rather than giving up."""
    display.communicator.animation = MagicMock()
    display.communicator.animation.stream_animation_8b = AsyncMock(return_value=False)
    display.communicator.cfg = None
    display.communicator.send_command = AsyncMock(return_value=True)
    fake_packets = [bytes([7, 7, 7])]
    with patch("divoom_lib.display.encode_animation", return_value=fake_packets):
        result = await display.show_image(test_image)
    assert result is True
    display.communicator.animation.stream_animation_8b.assert_awaited_once()
    calls = [c for c in display.communicator.send_command.await_args_list
             if c.args and c.args[0] == "set animation frame"]
    assert len(calls) == 1


# ── _get_screensize ───────────────────────────────────────────────────────


def test_get_screensize_reads_cfg_value(display: Display) -> None:
    display.communicator.cfg = MagicMock(screensize=32)
    assert display._get_screensize() == 32


def test_get_screensize_defaults_to_16_when_cfg_screensize_falsy(display: Display) -> None:
    display.communicator.cfg = MagicMock(screensize=0)
    assert display._get_screensize() == 16


def test_get_screensize_defaults_to_16_without_cfg(display: Display) -> None:
    # MagicMock auto-creates any attribute on access, so force the "no cfg"
    # path explicitly rather than relying on an absent attribute.
    display.communicator.cfg = None
    assert display._get_screensize() == 16


# ── show_light ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_show_light_lan_branch(display: Display) -> None:
    display.communicator.lan = MagicMock()
    display.communicator.lan.set_ambient_light = AsyncMock()
    display.communicator.convert_color = MagicMock(return_value=[10, 20, 30])
    result = await display.show_light(color="0A141E", brightness=50, power=True)
    assert result is True
    display.communicator.lan.set_ambient_light.assert_awaited_once_with(50, 10, 20, 30, 1)


@pytest.mark.asyncio
async def test_show_light_defaults_brightness_and_power_when_none(display: Display) -> None:
    display.communicator.send_command = AsyncMock(return_value=True)
    display.communicator.convert_color = MagicMock(return_value=[1, 2, 3])
    result = await display.show_light(color="010203", brightness=None, power=None)
    assert result is True
    args = display.communicator.send_command.await_args.args[1]
    # args = [channel, R, G, B, brightness, type, power, fixed, fixed, fixed]
    assert args[4] == 100  # default brightness
    assert args[6] == 0x01  # default power = True -> 0x01


@pytest.mark.asyncio
async def test_show_light_explicit_power_false(display: Display) -> None:
    display.communicator.send_command = AsyncMock(return_value=True)
    display.communicator.convert_color = MagicMock(return_value=[1, 2, 3])
    result = await display.show_light(color="010203", brightness=75, power=False)
    assert result is True
    args = display.communicator.send_command.await_args.args[1]
    assert args[4] == 75
    assert args[6] == 0x00


# ── show_visualization ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_show_visualization_lan_branch(display: Display) -> None:
    display.communicator.lan = MagicMock()
    display.communicator.lan.set_channel = AsyncMock()
    result = await display.show_visualization(number=1)
    assert result is True
    display.communicator.lan.set_channel.assert_awaited_once_with(2)


@pytest.mark.asyncio
async def test_show_visualization_returns_false_when_number_none_non_lan(display: Display) -> None:
    result = await display.show_visualization(number=None)
    assert result is False


# ── switch_channel ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_switch_channel_lan_vj_not_supported(display: Display) -> None:
    display.communicator.lan = MagicMock()
    result = await display.switch_channel("vj")
    assert result is False


@pytest.mark.asyncio
async def test_switch_channel_lan_valid_mapping(display: Display) -> None:
    display.communicator.lan = MagicMock()
    display.communicator.lan.set_channel = AsyncMock()
    result = await display.switch_channel("scoreboard")
    assert result is True
    display.communicator.lan.set_channel.assert_awaited_once_with(6)


@pytest.mark.asyncio
async def test_switch_channel_lan_invalid_mapping(display: Display) -> None:
    display.communicator.lan = MagicMock()
    result = await display.switch_channel("nonsense")
    assert result is False


@pytest.mark.asyncio
async def test_switch_channel_non_lan_dispatch_table(display: Display) -> None:
    display.communicator.send_command = AsyncMock(return_value=True)
    display.communicator.convert_color = MagicMock(return_value=[1, 2, 3])
    assert await display.switch_channel("clock") is True
    assert await display.switch_channel("visualizer") is True
    assert await display.switch_channel("vj") is True
    assert await display.switch_channel("design") is True
    assert await display.switch_channel("scoreboard") is True


@pytest.mark.asyncio
async def test_switch_channel_non_lan_unknown_channel_returns_false(display: Display) -> None:
    result = await display.switch_channel("teleport")
    assert result is False


# ── R67/C1: the ambient effect byte ───────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("effect", [0, 1, 2, 3, 4])
async def test_show_light_ble_carries_the_effect_byte(display: Display, effect: int) -> None:
    """Every ambient mode must reach byte 5 of the 0x45 lighting packet.

    R67/C1: the Rust device_call handler hardcoded this byte to 0x00, so all
    five modes rendered as Plain Colour while the RPC reported success. The
    Python builder always had it right; this pins that so the two cannot drift
    apart again (see divoomd/src/packets.rs::LightPacket).
    """
    display.communicator.lan = None
    display.communicator.send_command = AsyncMock(return_value=True)
    display.communicator.convert_color = MagicMock(return_value=[0, 255, 204])

    await display.show_light(color="00FFCC", brightness=80, power=True,
                             lightning_type=effect)

    _, args = display.communicator.send_command.await_args.args
    assert args[5] == effect, f"effect byte must be {effect}, got {args[5]}"
    assert args[0] == 0x01, "byte 0 is the lighting channel"
    assert args[1:4] == [0, 255, 204], "bytes 1-3 are RGB"
    assert args[4] == 80, "byte 4 is brightness"
    assert args[6] == 1, "byte 6 is power"


@pytest.mark.asyncio
async def test_show_light_ble_modes_produce_distinct_payloads(display: Display) -> None:
    """Five modes, five different packets — the R67 defect in one assertion."""
    display.communicator.lan = None
    display.communicator.convert_color = MagicMock(return_value=[0, 255, 204])
    seen = set()
    for effect in range(5):
        display.communicator.send_command = AsyncMock(return_value=True)
        await display.show_light(color="00FFCC", brightness=80, power=True,
                                 lightning_type=effect)
        seen.add(tuple(display.communicator.send_command.await_args.args[1]))
    assert len(seen) == 5, f"expected 5 distinct payloads, got {len(seen)}"


@pytest.mark.asyncio
@pytest.mark.parametrize("effect", [1, 2, 3, 4])
async def test_show_light_lan_refuses_effects_it_cannot_express(
        display: Display, effect: int) -> None:
    """LAN must REFUSE a non-Plain effect, not silently render Plain.

    Divoom's HTTP API has no effect field — Channel/SetAmbientLight takes only
    Brightness/Color/Power — so the effect is genuinely unreachable over Wi-Fi.
    Reporting success for a mode the device never received is the dishonest
    state this asserts against (house rule: honest placeholders).
    """
    display.communicator.lan = MagicMock()
    display.communicator.lan.set_ambient_light = AsyncMock()
    display.communicator.convert_color = MagicMock(return_value=[0, 255, 204])

    result = await display.show_light(color="00FFCC", brightness=80, power=True,
                                      lightning_type=effect)

    assert result is False, "LAN must not claim success for an unreachable effect"
    display.communicator.lan.set_ambient_light.assert_not_awaited()


@pytest.mark.asyncio
async def test_show_light_lan_still_serves_plain_colour(display: Display) -> None:
    """The refusal above must be narrow: Plain Colour still works over LAN."""
    display.communicator.lan = MagicMock()
    display.communicator.lan.set_ambient_light = AsyncMock()
    display.communicator.convert_color = MagicMock(return_value=[0, 255, 204])

    result = await display.show_light(color="00FFCC", brightness=80, power=True,
                                      lightning_type=0)

    assert result is True
    display.communicator.lan.set_ambient_light.assert_awaited_once_with(80, 0, 255, 204, 1)
