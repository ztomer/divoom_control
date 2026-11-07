#!/usr/bin/env python3
"""monthly_best_daemon: GIF extraction and _fetch_and_download (split from
test_monthly_best_daemon.py, which keeps the push and main-loop paths)."""

import json
import struct
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch
from pathlib import Path

# Add paths to sys.path
sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / "api_scraper"))

from divoom_legacy import monthly_best_daemon


class TestMonthlyBestDaemon(unittest.IsolatedAsyncioTestCase):
    def test_extract_gif_from_magic_43_invalid(self):
        """Test extract_gif_from_magic_43 returns None for non-Magic 43 data."""
        # Non-magic-43 bytes
        data = b"\x1a\x00\x00\x00\x00\x00"
        result = monthly_best_daemon.extract_gif_from_magic_43(data)
        self.assertIsNone(result)

    def test_extract_gif_from_magic_43_valid(self):
        """Test extract_gif_from_magic_43 correctly parses valid Magic 43 payload."""
        # Magic 43 payload structure:
        # Magic byte 43 (0x2b) - 1 byte
        # Offset 1-5: arbitrary padding
        # Offset 6-9: text_len (4 bytes little-endian)
        # Offset 10: text content (text_len bytes)
        # Next 4 bytes: gif_len (4 bytes little-endian)
        # Next gif_len bytes: GIF data starting with GIF89a
        text = b"Hello, World!"
        gif = b"GIF89aXXXXXX"

        payload = bytearray([43, 0, 0, 0, 0, 0])
        payload.extend(len(text).to_bytes(4, byteorder="little"))
        payload.extend(text)
        payload.extend(len(gif).to_bytes(4, byteorder="little"))
        payload.extend(gif)

        result = monthly_best_daemon.extract_gif_from_magic_43(bytes(payload))
        self.assertEqual(result, gif)

    async def test_stream_raw_bin_payload_delegates_to_shared_streamer(self):
        """R34 §1b: stream_raw_bin_payload is a thin delegator to the single
        APK-aligned 0x8b streamer (Animation.stream_animation_8b) — the 3-phase
        wire format itself is covered by tests/test_animation_8b_stream.py."""
        mock_divoom = MagicMock()
        mock_divoom.animation.stream_animation_8b = AsyncMock(return_value=True)
        file_data = b"X" * 600

        success = await monthly_best_daemon.stream_raw_bin_payload(mock_divoom, file_data)
        self.assertTrue(success)
        mock_divoom.animation.stream_animation_8b.assert_awaited_once_with(file_data)

        mock_divoom.animation.stream_animation_8b = AsyncMock(return_value=False)
        self.assertFalse(await monthly_best_daemon.stream_raw_bin_payload(mock_divoom, file_data))

    def test_extract_gif_from_magic_43_truncated_header(self):
        """gif_len field would read past the buffer end -> None (line 66)."""
        text = b"hi"
        payload = bytearray([43, 0, 0, 0, 0, 0])
        payload.extend(len(text).to_bytes(4, byteorder="little"))
        payload.extend(text)
        # No gif_len bytes appended at all: gif_len_offset + 4 > len(file_data).
        result = monthly_best_daemon.extract_gif_from_magic_43(bytes(payload))
        self.assertIsNone(result)

    def test_extract_gif_from_magic_43_gif_len_overruns_buffer(self):
        """Declared gif_len is larger than the remaining bytes -> gif_end is
        clamped to len(file_data) (line 73) and the truncated GIF is still
        recovered when its header is intact."""
        text = b""
        gif = b"GIF89aXYZ"
        payload = bytearray([43, 0, 0, 0, 0, 0])
        payload.extend(len(text).to_bytes(4, byteorder="little"))
        payload.extend(text)
        # Claim a gif_len far larger than what's actually appended.
        payload.extend((1000).to_bytes(4, byteorder="little"))
        payload.extend(gif)
        result = monthly_best_daemon.extract_gif_from_magic_43(bytes(payload))
        self.assertEqual(result, gif)

    def test_extract_gif_from_magic_43_struct_error_caught(self):
        """An unpack failure inside the try block is caught, warned, and
        returns None (lines 78-80) rather than propagating."""
        text = b"hi"
        gif = b"GIF89aXYZ"
        payload = bytearray([43, 0, 0, 0, 0, 0])
        payload.extend(len(text).to_bytes(4, byteorder="little"))
        payload.extend(text)
        payload.extend(len(gif).to_bytes(4, byteorder="little"))
        payload.extend(gif)
        with patch("divoom_legacy.monthly_best_daemon.struct.unpack", side_effect=struct.error("bad unpack")):
            result = monthly_best_daemon.extract_gif_from_magic_43(bytes(payload))
        self.assertIsNone(result)


def _fake_response(data: bytes):
    """A minimal context-manager stand-in for urllib's addinfourl response."""
    resp = MagicMock()
    resp.read.return_value = data
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


class TestFetchAndDownload(unittest.IsolatedAsyncioTestCase):
    """Covers monthly_best_daemon._fetch_and_download (lines 217-292)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.scratch_dir = Path(self._tmpdir.name)
        self.creds = SimpleNamespace(token=111, user_id=222)
        self.logger = MagicMock()

    def tearDown(self):
        self._tmpdir.cleanup()

    async def test_fetch_and_download_mixed_results_and_limit_break(self):
        """Exercises: missing FileId skip, magic-43 extraction, direct GIF,
        native bin fallback, a per-item download exception (caught + continue),
        a too-short response (continue), and the downloaded_count >= limit
        break once the limit is reached (lines 259-260, 263-264, 271-272,
        283-292)."""
        text, gif = b"", b"GIF89aABC"
        magic43_payload = bytearray([43, 0, 0, 0, 0, 0])
        magic43_payload.extend(len(text).to_bytes(4, byteorder="little"))
        magic43_payload.extend(text)
        magic43_payload.extend(len(gif).to_bytes(4, byteorder="little"))
        magic43_payload.extend(gif)

        file_list = [
            {"FileId": None, "FileName": "NoId"},
            {"FileId": "id_magic43", "FileName": "Magic43Item"},
            {"FileId": "id_directgif", "FileName": "DirectGif"},
            {"FileId": "id_fail", "FileName": "FailItem"},
            {"FileId": "id_short", "FileName": "ShortItem"},
            {"FileId": "id_bin", "FileName": "NativeBin"},
            {"FileId": "id_never_reached", "FileName": "NeverReached"},
        ]
        list_body = {"ReturnCode": 0, "FileList": file_list}
        downloads = {
            "id_magic43": bytes(magic43_payload),
            "id_directgif": gif,
            "id_fail": RuntimeError("network blew up"),
            "id_short": b"ab",
            "id_bin": b"\x01\x02\x03\x04binarystuff",
        }

        def fake_urlopen(req, timeout=None):
            url = req.full_url
            if url.endswith("GetCategoryFileListV2"):
                return _fake_response(json.dumps(list_body).encode("utf-8"))
            for file_id, result in downloads.items():
                if url.endswith(file_id):
                    if isinstance(result, Exception):
                        raise result
                    return _fake_response(result)
            raise AssertionError(f"unexpected download url: {url}")

        args = SimpleNamespace(limit=3)
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            items = await monthly_best_daemon._fetch_and_download(
                18, args, self.creds, 0, 0, self.scratch_dir, self.logger
            )

        # Only the 3 successful downloads count toward the limit; the trailing
        # "NeverReached" item is cut off by the limit break.
        self.assertEqual(len(items), 3)
        types = [it["type"] for it in items]
        self.assertEqual(types, ["gif", "gif", "bin"])
        self.assertEqual(items[0]["name"], "Magic43Item")
        self.assertEqual(items[1]["name"], "DirectGif")
        self.assertEqual(items[2]["name"], "NativeBin")
        self.assertEqual(items[2]["bytes"], downloads["id_bin"])
        # The extracted/direct GIFs were actually written under scratch_dir.
        self.assertTrue(Path(items[0]["path"]).exists())
        self.assertTrue(Path(items[1]["path"]).exists())
        self.assertEqual(Path(items[0]["path"]).read_bytes(), gif)

    async def test_fetch_and_download_device_password_included_in_body(self):
        """When device_pw is truthy it's added to the outgoing request body
        (line 231-232)."""
        list_body = {"ReturnCode": 0, "FileList": []}
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            return _fake_response(json.dumps(list_body).encode("utf-8"))

        args = SimpleNamespace(limit=5)
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            items = await monthly_best_daemon._fetch_and_download(
                9, args, self.creds, 42, 999, self.scratch_dir, self.logger
            )

        self.assertEqual(items, [])
        self.assertEqual(captured["payload"]["DevicePassword"], 999)
        self.assertEqual(captured["payload"]["DeviceId"], 42)
        self.assertEqual(captured["payload"]["Classify"], 9)

    async def test_fetch_and_download_return_code_error(self):
        """A non-zero ReturnCode from the gallery API returns an empty list
        (lines 251-253)."""
        list_body = {"ReturnCode": 3, "ReturnMessage": "denied"}

        def fake_urlopen(req, timeout=None):
            return _fake_response(json.dumps(list_body).encode("utf-8"))

        args = SimpleNamespace(limit=5)
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            items = await monthly_best_daemon._fetch_and_download(
                18, args, self.creds, 0, 0, self.scratch_dir, self.logger
            )
        self.assertEqual(items, [])

    async def test_fetch_and_download_outer_request_exception(self):
        """A hard failure making the list request (e.g. network down) is
        caught by the outer try/except and yields an empty list
        (lines 290-292)."""

        def fake_urlopen(req, timeout=None):
            raise OSError("network unreachable")

        args = SimpleNamespace(limit=5)
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            items = await monthly_best_daemon._fetch_and_download(
                18, args, self.creds, 0, 0, self.scratch_dir, self.logger
            )
        self.assertEqual(items, [])
