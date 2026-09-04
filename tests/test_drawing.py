import pytest
from unittest.mock import AsyncMock, MagicMock
from divoom_lib.divoom import Divoom
from divoom_lib.models import DivoomConfig

@pytest.fixture
def divoom_device():
    config = DivoomConfig(mac="XX:XX:XX:XX:XX:XX")
    device = Divoom(config)
    device.send_command = AsyncMock()
    return device

@pytest.mark.asyncio
async def test_set_light_pic(divoom_device):
    pic_data = [0x01, 0x02, 0x03]
    await divoom_device.drawing.set_light_pic(pic_data)
    divoom_device.send_command.assert_called_once_with(0x44, pic_data)


def _last_args(device):
    """The (command, args) tuple of the most recent send_command call."""
    call = device.send_command.call_args
    args = call.args
    return args[0], (args[1] if len(args) > 1 else None)


# ── pad control builders ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_drawing_mul_pad_ctrl(divoom_device):
    await divoom_device.drawing.drawing_mul_pad_ctrl(
        screen_id=1, r=255, g=0, b=128, num_points=2, offset_list=[10, 20])
    cmd, args = _last_args(divoom_device)
    assert cmd == 0x3a
    assert args == [1, 255, 0, 128, 2, 10, 20]


@pytest.mark.asyncio
async def test_drawing_big_pad_ctrl(divoom_device):
    await divoom_device.drawing.drawing_big_pad_ctrl(
        canvas_width=32, screen_id=0, r=1, g=2, b=3, num_points=1, offset_list=[9])
    cmd, args = _last_args(divoom_device)
    assert cmd == 0x3b
    assert args == [32, 0, 1, 2, 3, 1, 9]


@pytest.mark.asyncio
async def test_drawing_pad_ctrl(divoom_device):
    await divoom_device.drawing.drawing_pad_ctrl(
        r=10, g=20, b=30, num_points=1, offset_list=[5])
    cmd, args = _last_args(divoom_device)
    assert cmd == 0x58
    assert args == [10, 20, 30, 1, 5]


@pytest.mark.asyncio
async def test_drawing_pad_exit(divoom_device):
    await divoom_device.drawing.drawing_pad_exit()
    assert divoom_device.send_command.call_args.args[0] == 0x5a


@pytest.mark.asyncio
async def test_drawing_mul_pad_enter(divoom_device):
    await divoom_device.drawing.drawing_mul_pad_enter(r=0, g=0, b=0)
    cmd, args = _last_args(divoom_device)
    assert cmd == 0x6f
    assert args == [0, 0, 0]


# ── encode / playback builders (little-endian length fields) ─────────────────


@pytest.mark.asyncio
async def test_drawing_mul_encode_single_pic(divoom_device):
    await divoom_device.drawing.drawing_mul_encode_single_pic(
        screen_id=2, data_length=300, data=[0xAA])
    cmd, args = _last_args(divoom_device)
    assert cmd == 0x5b
    # screen_id(1), data_length(2 LE), data
    assert args == [2, 300 & 0xFF, 300 >> 8, 0xAA]


@pytest.mark.asyncio
async def test_drawing_mul_encode_pic(divoom_device):
    await divoom_device.drawing.drawing_mul_encode_pic(
        screen_id=1, total_length=513, pic_id=7, pic_data=[0xBB])
    cmd, args = _last_args(divoom_device)
    assert cmd == 0x5c
    assert args == [1, 513 & 0xFF, 513 >> 8, 7, 0xBB]


@pytest.mark.asyncio
async def test_drawing_mul_encode_gif_play(divoom_device):
    await divoom_device.drawing.drawing_mul_encode_gif_play()
    assert divoom_device.send_command.call_args.args[0] == 0x6b


@pytest.mark.asyncio
async def test_drawing_encode_movie_play(divoom_device):
    await divoom_device.drawing.drawing_encode_movie_play(
        frame_id=258, data_length=4, data=[1, 2, 3, 4])
    cmd, args = _last_args(divoom_device)
    assert cmd == 0x6c
    # frame_id(2 LE), data_length(2 LE), data ; 258 = 0x0102
    assert args == [0x02, 0x01, 4, 0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_drawing_mul_encode_movie_play(divoom_device):
    await divoom_device.drawing.drawing_mul_encode_movie_play(
        screen_id=1, frame_id=2, data_length=1, data=[0xFF])
    cmd, args = _last_args(divoom_device)
    assert cmd == 0x6d
    assert args == [1, 2, 0, 1, 0, 0xFF]


@pytest.mark.asyncio
async def test_drawing_ctrl_movie_play(divoom_device):
    await divoom_device.drawing.drawing_ctrl_movie_play(1)
    cmd, args = _last_args(divoom_device)
    assert cmd == 0x6e
    assert args == [1]


# ── sand_paint_ctrl dispatch ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sand_paint_ctrl_initialize(divoom_device):
    await divoom_device.drawing.sand_paint_ctrl(
        0, device_id=1, image_length=256, image_data=[0xDD])
    cmd, args = _last_args(divoom_device)
    assert cmd == 0x34
    # control(0), device_id(1), image_length(2 LE = 256 -> 0x00,0x01), data
    assert args == [0, 1, 0x00, 0x01, 0xDD]


@pytest.mark.asyncio
async def test_sand_paint_ctrl_reset(divoom_device):
    await divoom_device.drawing.sand_paint_ctrl(1)
    cmd, args = _last_args(divoom_device)
    assert cmd == 0x34
    assert args == [1]  # reset adds no data


@pytest.mark.asyncio
async def test_sand_paint_ctrl_initialize_missing_params_returns_false(divoom_device):
    ok = await divoom_device.drawing.sand_paint_ctrl(0, device_id=1)  # missing data
    assert ok is False
    divoom_device.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_sand_paint_ctrl_unknown_control_returns_false(divoom_device):
    ok = await divoom_device.drawing.sand_paint_ctrl(99)
    assert ok is False
    divoom_device.send_command.assert_not_called()


# ── pic_scan_ctrl dispatch (0x35, UNVERIFIED per R12 audit) ──────────────────


@pytest.mark.asyncio
async def test_pic_scan_ctrl_set_mode_speed(divoom_device):
    await divoom_device.drawing.pic_scan_ctrl(0, mode=1, speed=300)
    cmd, args = _last_args(divoom_device)
    assert cmd == 0x35
    # control(0), mode(1), speed(2 LE = 300 -> 0x2c,0x01)
    assert args == [0, 1, 0x2c, 0x01]


@pytest.mark.asyncio
async def test_pic_scan_ctrl_sending_image_data(divoom_device):
    await divoom_device.drawing.pic_scan_ctrl(1, total_length=2, pic_id=5, data=[0xEE, 0xFF])
    cmd, args = _last_args(divoom_device)
    assert cmd == 0x35
    # control(1), total_length(2 LE), pic_id(1), data
    assert args == [1, 2, 0, 5, 0xEE, 0xFF]


@pytest.mark.asyncio
async def test_pic_scan_ctrl_missing_params_returns_false(divoom_device):
    ok = await divoom_device.drawing.pic_scan_ctrl(0, mode=1)  # missing speed
    assert ok is False
    divoom_device.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_pic_scan_ctrl_sending_data_missing_params_returns_false(divoom_device):
    ok = await divoom_device.drawing.pic_scan_ctrl(1, total_length=2)  # missing pic_id, data
    assert ok is False
    divoom_device.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_pic_scan_ctrl_unknown_control_returns_false(divoom_device):
    ok = await divoom_device.drawing.pic_scan_ctrl(42)
    assert ok is False
    divoom_device.send_command.assert_not_called()
