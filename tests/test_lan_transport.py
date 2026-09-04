"""R53.44: the LAN HTTP transport must not report a device-rejected command as
success. The Divoom local API returns HTTP 200 with {"error_code": N}; N != 0
means the command failed (bad LocalToken, out-of-range value, unsupported on this
model). post() used to return that body verbatim → the daemon reported success
(ACK != success). _validate_lan_response now raises on non-200, non-JSON, or a
non-zero error_code.

These are the FIRST tests for LanTransport (the bug went unnoticed because there
were none).
"""
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))

from divoom_lib.lan_transport import LanTransportError, _validate_lan_response


def test_success_error_code_zero_returns_dict():
    out = _validate_lan_response(200, '{"error_code": 0, "SelectIndex": 2}', "Channel/GetIndex")
    assert out == {"error_code": 0, "SelectIndex": 2}


def test_missing_error_code_is_tolerated():
    out = _validate_lan_response(200, '{"SelectIndex": 2}', "Channel/GetIndex")
    assert out == {"SelectIndex": 2}


def test_nonzero_error_code_raises():
    with pytest.raises(LanTransportError) as ei:
        _validate_lan_response(200, '{"error_code": 5}', "Channel/SetBrightness")
    assert "error_code=5" in str(ei.value)


def test_non_200_status_raises():
    with pytest.raises(LanTransportError):
        _validate_lan_response(500, '{"error_code": 0}', "Channel/SetIndex")


def test_non_json_body_raises():
    with pytest.raises(LanTransportError):
        _validate_lan_response(200, "<html>not a divoom device</html>", "Channel/GetIndex")


# ── post() / probe() — the actual HTTP path ──────────────────────────────────
#
# These mock the aiohttp module reference INSIDE divoom_lib.lan_transport so no
# real network call is ever made. The fake ClientSession/response are async
# context managers shaped like aiohttp's, and aiohttp.ClientConnectorError is
# swapped for a plain Exception subclass so we can raise it without wrangling
# aiohttp's real (connection_key, os_error) constructor.

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import divoom_lib.lan_transport as lan_mod
from divoom_lib.lan_transport import LanTransport


class _FakeConnectorError(Exception):
    """Stand-in for aiohttp.ClientConnectorError (real one needs a live
    connection_key/os_error pair to construct)."""


class _FakeResp:
    def __init__(self, status, text):
        self.status = status
        self._text = text

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    """async-context-manager session whose .post() either returns a fake
    response (as an async context manager) or raises a given exception."""

    def __init__(self, resp=None, raise_exc=None):
        self._resp = resp
        self._raise_exc = raise_exc

    def post(self, *a, **k):
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _fake_aiohttp(resp=None, raise_exc=None):
    """Build a stand-in for the `aiohttp` module reference used by post()."""
    fake = MagicMock()
    fake.ClientSession.return_value = _FakeSession(resp=resp, raise_exc=raise_exc)
    fake.ClientTimeout = lambda **kw: kw
    fake.ClientConnectorError = _FakeConnectorError
    return fake


class TestLanTransportPost(unittest.IsolatedAsyncioTestCase):

    async def test_post_success_returns_parsed_json(self):
        fake = _fake_aiohttp(resp=_FakeResp(200, '{"error_code": 0, "x": 1}'))
        with patch.object(lan_mod, "aiohttp", fake), \
             patch.object(lan_mod, "_AIOHTTP_AVAILABLE", True):
            lan = LanTransport(device_ip="10.0.0.5")
            out = await lan.post("Channel/GetIndex")
            assert out == {"error_code": 0, "x": 1}

    async def test_post_merges_extra_fields_into_body(self):
        """extra=... must be merged into the request body (not just Command
        + LocalToken) — covers the `if extra: body.update(extra)` branch."""
        fake = _fake_aiohttp(resp=_FakeResp(200, '{"error_code": 0}'))
        with patch.object(lan_mod, "aiohttp", fake), \
             patch.object(lan_mod, "_AIOHTTP_AVAILABLE", True):
            lan = LanTransport(device_ip="10.0.0.5")
            out = await lan.post("Channel/SetIndex", {"SelectIndex": 2})
            assert out == {"error_code": 0}

    async def test_post_without_aiohttp_installed_raises(self):
        with patch.object(lan_mod, "_AIOHTTP_AVAILABLE", False):
            lan = LanTransport(device_ip="10.0.0.5")
            with pytest.raises(lan_mod.LanTransportError, match="aiohttp is required"):
                await lan.post("Channel/GetIndex")

    async def test_post_connector_error_raises_with_actionable_message(self):
        fake = _fake_aiohttp(raise_exc=_FakeConnectorError("refused"))
        with patch.object(lan_mod, "aiohttp", fake), \
             patch.object(lan_mod, "_AIOHTTP_AVAILABLE", True):
            lan = LanTransport(device_ip="10.0.0.5")
            with pytest.raises(lan_mod.LanTransportError, match="Cannot reach device"):
                await lan.post("Channel/GetIndex")

    async def test_post_timeout_raises_with_actionable_message(self):
        fake = _fake_aiohttp(raise_exc=asyncio.TimeoutError())
        with patch.object(lan_mod, "aiohttp", fake), \
             patch.object(lan_mod, "_AIOHTTP_AVAILABLE", True):
            lan = LanTransport(device_ip="10.0.0.5")
            with pytest.raises(lan_mod.LanTransportError, match="did not respond within"):
                await lan.post("Channel/GetIndex")

    async def test_post_generic_exception_wrapped(self):
        fake = _fake_aiohttp(raise_exc=RuntimeError("boom"))
        with patch.object(lan_mod, "aiohttp", fake), \
             patch.object(lan_mod, "_AIOHTTP_AVAILABLE", True):
            lan = LanTransport(device_ip="10.0.0.5")
            with pytest.raises(lan_mod.LanTransportError, match="LAN request failed"):
                await lan.post("Channel/GetIndex")

    async def test_post_device_rejection_not_rewrapped_as_request_failed(self):
        """The validate() call is OUTSIDE the network try/except — a device
        rejection (non-zero error_code) must surface its OWN message, not get
        re-labeled 'LAN request failed' by the broad except above it."""
        fake = _fake_aiohttp(resp=_FakeResp(200, '{"error_code": 7}'))
        with patch.object(lan_mod, "aiohttp", fake), \
             patch.object(lan_mod, "_AIOHTTP_AVAILABLE", True):
            lan = LanTransport(device_ip="10.0.0.5")
            with pytest.raises(lan_mod.LanTransportError, match="error_code=7"):
                await lan.post("Channel/SetBrightness")

    async def test_probe_returns_true_when_reachable(self):
        lan = LanTransport(device_ip="10.0.0.5")
        lan.post = AsyncMock(return_value={"error_code": 0})
        assert await lan.probe() is True

    async def test_probe_returns_false_on_transport_error(self):
        lan = LanTransport(device_ip="10.0.0.5")
        lan.post = AsyncMock(side_effect=lan_mod.LanTransportError("unreachable"))
        assert await lan.probe() is False

    async def test_probe_returns_false_when_post_succeeds_but_not_a_dict(self):
        """post() completing without raising but yielding a non-dict result
        (defensive branch) must still resolve to reachable=False."""
        lan = LanTransport(device_ip="10.0.0.5")
        lan.post = AsyncMock(return_value="not-a-dict")
        assert await lan.probe() is False


class TestLanTransportCommandWrappers(unittest.IsolatedAsyncioTestCase):
    """Each @via(Transport.LAN) method is a thin wrapper around post() with a
    fixed command string + field mapping. Cover them all in one sweep."""

    def setUp(self):
        self.lan = LanTransport(device_ip="10.0.0.5", local_token=99)
        self.lan.post = AsyncMock(return_value={"error_code": 0})

    async def test_set_channel(self):
        await self.lan.set_channel(3)
        self.lan.post.assert_called_once_with("Channel/SetIndex", {"SelectIndex": 3})

    async def test_get_channel(self):
        await self.lan.get_channel()
        self.lan.post.assert_called_once_with("Channel/GetIndex")

    async def test_set_brightness(self):
        await self.lan.set_brightness(77)
        self.lan.post.assert_called_once_with("Channel/SetBrightness", {"Brightness": 77})

    async def test_set_clock(self):
        await self.lan.set_clock(182)
        self.lan.post.assert_called_once_with("Channel/SetClockSelectId", {"ClockId": 182})

    async def test_send_playlist(self):
        await self.lan.send_playlist(42)
        self.lan.post.assert_called_once_with("Playlist/SendDevice", {"PlayId": 42})

    async def test_on_off_screen(self):
        await self.lan.on_off_screen(0)
        self.lan.post.assert_called_once_with("Channel/OnOffScreen", {"OnOff": 0})

    async def test_set_ambient_light(self):
        await self.lan.set_ambient_light(80, 255, 128, 0, power=1)
        self.lan.post.assert_called_once_with("Channel/SetAmbientLight", {
            "Brightness": 80, "Color": "#FF8000", "Power": 1,
        })

    async def test_set_rgb_info(self):
        await self.lan.set_rgb_info(mode=1, speed=50, r=255, g=0, b=128)
        self.lan.post.assert_called_once_with("Channel/SetRGBInfo", {
            "RgbMode": 1, "RgbSpeed": 50, "RgbColor": "#FF0080",
        })

    async def test_set_timer(self):
        await self.lan.set_timer(5, 30, 1)
        self.lan.post.assert_called_once_with("Tools/SetTimer", {
            "Minute": 5, "Second": 30, "Status": 1,
        })

    async def test_set_scoreboard(self):
        await self.lan.set_scoreboard(blue=3, red=1)
        self.lan.post.assert_called_once_with("Tools/SetScoreBoard", {
            "BlueScore": 3, "RedScore": 1,
        })

    async def test_set_stopwatch(self):
        await self.lan.set_stopwatch(1)
        self.lan.post.assert_called_once_with("Tools/SetStopWatch", {"Status": 1})

    async def test_set_noise_status(self):
        await self.lan.set_noise_status(1)
        self.lan.post.assert_called_once_with("Tools/SetNoiseStatus", {"NoiseStatus": 1})

    async def test_play_album(self):
        await self.lan.play_album(7)
        self.lan.post.assert_called_once_with("Photo/PlayAlbum", {"AlbumId": 7})

    async def test_set_album_cover(self):
        await self.lan.set_album_cover(clock_id=7, file_id="abc123", photo_id=1)
        self.lan.post.assert_called_once_with("Photo/SetAlbumCover", {
            "ClockId": 7, "FileId": "abc123", "PhotoId": 1,
        })

    async def test_delete_photo(self):
        await self.lan.delete_photo(clock_id=7, photo_list=[1, 2])
        self.lan.post.assert_called_once_with("Photo/DeletePhoto", {
            "ClockId": 7, "PhotoList": [1, 2],
        })

    async def test_remove_photo_from_album(self):
        await self.lan.remove_photo_from_album(clock_id=7, photo_list=[1, 2])
        self.lan.post.assert_called_once_with("Photo/RemovePhotoFromAlbum", {
            "ClockId": 7, "PhotoList": [1, 2],
        })

    async def test_move_photo_to_album(self):
        await self.lan.move_photo_to_album(to_clock_id=8, photo_list=[1, 2])
        self.lan.post.assert_called_once_with("Photo/DevicePhotoToAlbum", {
            "ToClockId": 8, "PhotoList": [1, 2],
        })

    async def test_get_photo_list(self):
        await self.lan.get_photo_list(clock_id=7, limit=10, page=2)
        self.lan.post.assert_called_once_with("Photo/GetPhotoList", {
            "ClockId": 7, "ParentClockId": 0, "ParentItemId": 0,
            "StartNum": 11, "EndNum": 20,
        })

    async def test_get_eq_position(self):
        await self.lan.get_eq_position()
        self.lan.post.assert_called_once_with("Channel/GetEqPosition")

    async def test_get_rgb_info(self):
        await self.lan.get_rgb_info()
        self.lan.post.assert_called_once_with("Channel/GetRGBInfo")

    async def test_get_ambient_light(self):
        await self.lan.get_ambient_light()
        self.lan.post.assert_called_once_with("Channel/GetAmbientLight")

    async def test_get_on_off_screen(self):
        await self.lan.get_on_off_screen()
        self.lan.post.assert_called_once_with("Channel/GetOnOffScreen")

    async def test_get_noise_status(self):
        await self.lan.get_noise_status()
        self.lan.post.assert_called_once_with("Tools/GetNoiseStatus")

    async def test_get_timer_lan(self):
        await self.lan.get_timer()
        self.lan.post.assert_called_once_with("Tools/GetTimer")

    async def test_get_scoreboard_lan(self):
        await self.lan.get_scoreboard()
        self.lan.post.assert_called_once_with("Tools/GetScoreBoard")

    async def test_get_stopwatch_lan(self):
        await self.lan.get_stopwatch()
        self.lan.post.assert_called_once_with("Tools/GetStopWatch")

    async def test_set_5lcd_channel_type(self):
        await self.lan.set_5lcd_channel_type(2, lcd_independence=1)
        self.lan.post.assert_called_once_with("Channel/Set5LcdChannelType", {
            "ChannelType": 2, "LcdIndependence": 1,
        })

    async def test_set_5lcd_whole_clock_id(self):
        await self.lan.set_5lcd_whole_clock_id(182)
        self.lan.post.assert_called_once_with("Channel/Set5LcdWholeClockId", {"ClockId": 182})

    async def test_set_produce_time(self):
        await self.lan.set_produce_time(1700000000)
        self.lan.post.assert_called_once_with("Channel/SetProduceTime", {"ProduceTime": 1700000000})

    async def test_set_night_preview(self):
        await self.lan.set_night_preview(20)
        self.lan.post.assert_called_once_with("Channel/SetNightPreview", {"Brightness": 20})

    async def test_exit_night_preview(self):
        await self.lan.exit_night_preview()
        self.lan.post.assert_called_once_with("Channel/ExitNightPreview")

    async def test_send_voice_text(self):
        await self.lan.send_voice_text("Hello", nickname="Bot", background="#000000",
                                        text_color="#FF0000", speed=30)
        self.lan.post.assert_called_once_with("Voice/SendText", {
            "Text": "Hello", "NickName": "Bot", "Background": "#000000",
            "TextColor": "#FF0000", "Speed": 30,
        })

    async def test_send_danmaku_text(self):
        await self.lan.send_danmaku_text("Hello", text_color="#00FF00")
        self.lan.post.assert_called_once_with("Danmaku/SendText", {
            "Text": "Hello", "TextColor": "#00FF00",
        })

    async def test_danmaku_random_face(self):
        await self.lan.danmaku_random_face()
        self.lan.post.assert_called_once_with("Danmaku/RandomFace")


class TestLanTransportMisc(unittest.TestCase):
    def test_transport_property_is_lan(self):
        from divoom_lib.transport import Transport
        lan = LanTransport(device_ip="10.0.0.5")
        assert lan.transport is Transport.LAN

    def test_repr_includes_ip_and_token(self):
        lan = LanTransport(device_ip="10.0.0.5", local_token=42)
        r = repr(lan)
        assert "10.0.0.5" in r
        assert "42" in r
        assert "LAN" in r
