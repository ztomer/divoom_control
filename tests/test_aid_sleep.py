"""AidSleep (cloud sound library playback) -- wire-byte pinning.

AidSleep/Play (+ Add/Delete/Exit) aren't sent as HTTP requests -- the
decompiled APK builds a small JSON object and writes it directly over
BLE/SPP using command id 1 (SPP_JSON), the same low-level frame every
binary-opcode command already goes through (confirmed byte-for-byte
against divoom_lib/framing.py). These tests pin that encoding: command id
1, and a JSON payload with the exact field names/values.
"""
import json
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock

from divoom_lib.tools.aid_sleep import AidSleep, SPP_JSON_COMMAND_ID


def _mock_divoom():
    mock = MagicMock()
    mock.send_command = AsyncMock(return_value=True)
    mock.logger = logging.getLogger("test_aid_sleep")
    return mock


def _sent_command_json(mock_divoom_instance) -> dict:
    (command_id, payload), _kwargs = mock_divoom_instance.send_command.call_args
    assert command_id == SPP_JSON_COMMAND_ID
    return json.loads(bytes(payload).decode("utf-8"))


@pytest.mark.asyncio
async def test_play_sends_spp_json_command_id():
    mock = _mock_divoom()
    aid_sleep = AidSleep(mock)

    ok = await aid_sleep.play(sleep_id=123, sleep_type=1)

    assert ok is True
    body = _sent_command_json(mock)
    assert body == {"Command": "AidSleep/Play", "SleepId": 123, "Type": 1}


@pytest.mark.asyncio
async def test_exit_sends_bare_command():
    mock = _mock_divoom()
    aid_sleep = AidSleep(mock)

    await aid_sleep.exit()

    body = _sent_command_json(mock)
    assert body == {"Command": "AidSleep/Exit"}


@pytest.mark.asyncio
async def test_add_sends_all_track_fields():
    mock = _mock_divoom()
    aid_sleep = AidSleep(mock)

    await aid_sleep.add(
        sleep_id=5, sleep_type=2, name="Rain", file_id="group1/abc",
        language="en", audio_type=1, video_type=0)

    body = _sent_command_json(mock)
    assert body == {
        "Command": "AidSleep/Add",
        "SleepId": 5, "Type": 2, "Name": "Rain", "FileId": "group1/abc",
        "Language": "en", "AudioType": 1, "VideoType": 0,
    }


@pytest.mark.asyncio
async def test_delete_sends_id_and_type():
    mock = _mock_divoom()
    aid_sleep = AidSleep(mock)

    await aid_sleep.delete(sleep_id=5, sleep_type=2)

    body = _sent_command_json(mock)
    assert body == {"Command": "AidSleep/Delete", "SleepId": 5, "Type": 2}


@pytest.mark.asyncio
async def test_facade_exposes_aid_sleep():
    """The Divoom facade must wire up .aid_sleep, matching .sleep/.noise/etc."""
    from divoom_lib.divoom import Divoom
    from divoom_lib import models

    divoom = Divoom(config=models.DivoomConfig(mac="AA:BB:CC:DD:EE:FF"))
    assert isinstance(divoom.aid_sleep, AidSleep)
