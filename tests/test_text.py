import pytest
from unittest.mock import AsyncMock, MagicMock
from divoom_lib.divoom import Divoom
from divoom_lib.models import (
    DivoomConfig,
    LPWA_CONTROL_SPEED,
    LPWA_CONTROL_EFFECTS,
    LPWA_CONTROL_DISPLAY_BOX,
    LPWA_CONTROL_FONT,
    LPWA_CONTROL_COLOR,
    LPWA_CONTROL_CONTENT,
    LPWA_CONTROL_IMAGE_EFFECTS,
)

@pytest.fixture
def divoom_device():
    config = DivoomConfig(mac="XX:XX:XX:XX:XX:XX")
    device = Divoom(config)
    device.send_command = AsyncMock(return_value=True)
    return device

@pytest.mark.asyncio
async def test_set_text_content(divoom_device):
    text = "Hello"
    text_box_id = 1
    await divoom_device.text.set_text_content(text, text_box_id=text_box_id)

    content_bytes = text.encode('utf-8')
    expected_payload = [LPWA_CONTROL_CONTENT] + list(len(content_bytes).to_bytes(2, byteorder='little')) + list(content_bytes) + [text_box_id]

    divoom_device.send_command.assert_called_once_with(0x87, expected_payload)


# ── R61 coverage push: each LPWA control-word handler, success + missing-param ──


@pytest.mark.asyncio
async def test_set_light_phone_word_attr_speed_success(divoom_device):
    result = await divoom_device.text.set_light_phone_word_attr(
        LPWA_CONTROL_SPEED, speed=300, text_box_id=2
    )
    assert result is True
    expected = [LPWA_CONTROL_SPEED] + list((300).to_bytes(2, byteorder='little')) + [2]
    divoom_device.send_command.assert_called_once_with(0x87, expected)


@pytest.mark.asyncio
async def test_set_light_phone_word_attr_speed_missing_params(divoom_device):
    result = await divoom_device.text.set_light_phone_word_attr(LPWA_CONTROL_SPEED, speed=300)
    assert result is False
    divoom_device.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_set_light_phone_word_attr_effects_success(divoom_device):
    result = await divoom_device.text.set_light_phone_word_attr(
        LPWA_CONTROL_EFFECTS, effect_style=4
    )
    assert result is True
    expected = [LPWA_CONTROL_EFFECTS, 4]
    divoom_device.send_command.assert_called_once_with(0x87, expected)


@pytest.mark.asyncio
async def test_set_light_phone_word_attr_effects_missing_params(divoom_device):
    result = await divoom_device.text.set_light_phone_word_attr(LPWA_CONTROL_EFFECTS)
    assert result is False
    divoom_device.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_set_light_phone_word_attr_display_box_success(divoom_device):
    result = await divoom_device.text.set_light_phone_word_attr(
        LPWA_CONTROL_DISPLAY_BOX, x=1, y=2, width=10, height=8, text_box_id=3
    )
    assert result is True
    expected = [LPWA_CONTROL_DISPLAY_BOX, 1, 2, 10, 8, 3]
    divoom_device.send_command.assert_called_once_with(0x87, expected)


@pytest.mark.asyncio
async def test_set_light_phone_word_attr_display_box_missing_params(divoom_device):
    # Missing height and text_box_id -> handler returns None.
    result = await divoom_device.text.set_light_phone_word_attr(
        LPWA_CONTROL_DISPLAY_BOX, x=1, y=2, width=10
    )
    assert result is False
    divoom_device.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_set_light_phone_word_attr_font_success(divoom_device):
    result = await divoom_device.text.set_light_phone_word_attr(
        LPWA_CONTROL_FONT, font_size=5, text_box_id=1
    )
    assert result is True
    expected = [LPWA_CONTROL_FONT, 5, 1]
    divoom_device.send_command.assert_called_once_with(0x87, expected)


@pytest.mark.asyncio
async def test_set_light_phone_word_attr_font_missing_params(divoom_device):
    result = await divoom_device.text.set_light_phone_word_attr(LPWA_CONTROL_FONT, font_size=5)
    assert result is False
    divoom_device.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_set_light_phone_word_attr_color_success(divoom_device):
    result = await divoom_device.text.set_light_phone_word_attr(
        LPWA_CONTROL_COLOR, color="FF0000", text_box_id=1
    )
    assert result is True
    expected = [LPWA_CONTROL_COLOR, 255, 0, 0, 1]
    divoom_device.send_command.assert_called_once_with(0x87, expected)


@pytest.mark.asyncio
async def test_set_light_phone_word_attr_color_missing_params(divoom_device):
    result = await divoom_device.text.set_light_phone_word_attr(LPWA_CONTROL_COLOR, color="FF0000")
    assert result is False
    divoom_device.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_set_light_phone_word_attr_content_missing_params(divoom_device):
    # Missing text_box_id -> the content handler's error branch (not exercised
    # by test_set_text_content, which always supplies both params).
    result = await divoom_device.text.set_light_phone_word_attr(
        LPWA_CONTROL_CONTENT, text_content="Hi"
    )
    assert result is False
    divoom_device.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_set_light_phone_word_attr_image_effects_success(divoom_device):
    result = await divoom_device.text.set_light_phone_word_attr(
        LPWA_CONTROL_IMAGE_EFFECTS, effect_style=2, text_box_id=1
    )
    assert result is True
    expected = [LPWA_CONTROL_IMAGE_EFFECTS, 2, 1]
    divoom_device.send_command.assert_called_once_with(0x87, expected)


@pytest.mark.asyncio
async def test_set_light_phone_word_attr_image_effects_missing_params(divoom_device):
    result = await divoom_device.text.set_light_phone_word_attr(
        LPWA_CONTROL_IMAGE_EFFECTS, effect_style=2
    )
    assert result is False
    divoom_device.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_set_light_phone_word_attr_unknown_control_word(divoom_device):
    result = await divoom_device.text.set_light_phone_word_attr(0xFF)
    assert result is False
    divoom_device.send_command.assert_not_called()
