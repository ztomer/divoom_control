import json
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import pytest

from tests.support.gui_api_base import GuiApiTestBase

class TestGuiApiWallMedia(GuiApiTestBase):
    def _fake_wall_client(self):
        """A fake daemon client for wall ops: wall_configure succeeds and
        device_call (target='wall') records the dotted method + returns True."""
        fake = MagicMock()
        fake.wall_configure.return_value = {"success": True, "wall": True}
        fake.device_status.return_value = {"success": True, "connected": False,
                                           "mac": None, "lan_ip": None, "wall": True}
        fake.device_call.return_value = {"success": True, "result": True}
        return fake

    def test_wall_operations(self):
        """R17 P5: wall ops route through the daemon-owned wall via device_call
        (target='wall')."""
        fake = self._fake_wall_client()
        self.api._daemon_client = fake
        slots = {"AA:BB:CC:DD:EE:FF": {"x": 0, "y": 0, "size": 16, "width": 120, "height": 120}}
        self.api.update_wall_slots(json.dumps(slots))
        self.assertEqual(self.api.wall_slots, slots)
        self.api.current_target_mode = "wall"

        self.assertTrue(self.api.set_solid_light("00FFCC", 100))
        fake.device_call.assert_called_with("set_light", ["00FFCC", 100], {},
                                            target="wall", blobs=None, token=None)

        self.assertTrue(self.api.set_clock(3))
        # show_clock is called with clock=3 (kwargs)
        last = fake.device_call.call_args
        self.assertEqual(last.args[0], "show_clock")
        self.assertEqual(last.kwargs.get("target"), "wall")

    def test_vj_and_visualization_selectors(self):
        """2.c/2.d: VJ + EQ selectors dispatch to the daemon-owned wall."""
        fake = self._fake_wall_client()
        self.api._daemon_client = fake
        self.api.update_wall_slots(json.dumps(
            {"AA:BB:CC:DD:EE:FF": {"x": 0, "y": 0, "size": 16, "width": 120, "height": 120}}
        ))
        self.api.current_target_mode = "wall"

        self.assertTrue(self.api.set_vj_effect(5))
        self.assertEqual(fake.device_call.call_args.args[0], "show_effects")

        self.assertTrue(self.api.set_visualization(3))
        self.assertEqual(fake.device_call.call_args.args[0], "show_visualization")

    def test_vj_visualization_no_target(self):
        """With no connected device and no wall, selectors fail gracefully (no raise)."""
        self.api.current_divoom = None
        self.api.wall_slots = {}
        self.assertFalse(self.api.set_vj_effect(0))
        self.assertFalse(self.api.set_visualization(0))

    def test_hot_channel_bridges_delegate(self):
        """4.c/4.d: target + schedule bridges delegate to hotchannel_config."""
        cfg = {"enabled": False, "interval": 3600, "classify": 18, "targets": ["AA"]}
        with patch("divoom_lib.hotchannel_config.set_targets", return_value=True) as mset, \
             patch("divoom_lib.hotchannel_config.load_config", return_value=cfg), \
             patch("divoom_lib.hotchannel_config.get_targets", return_value=["AA"]), \
             patch("divoom_lib.hotchannel_config.save_config", return_value=True) as msave:

            self.assertTrue(self.api.set_sync_targets(json.dumps(["AA", "BB"])))
            mset.assert_called_once_with(["AA", "BB"])

            self.assertEqual(json.loads(self.api.get_hot_channel_config())["targets"], ["AA"])

            self.assertTrue(self.api.save_hot_channel_config(json.dumps({"enabled": True})))
            msave.assert_called_once()

            cands = json.loads(self.api.get_sync_candidates())
            sel = {c["address"]: c["selected"] for c in cands}
            self.assertTrue(sel.get("AA"))  # persisted target shows as selected

    def test_ticker_preview_returns_data_url(self):
        """5.d: get_ticker_preview renders a frame and returns a PNG data URL."""
        from pathlib import Path as _P
        with patch("divoom_lib.utils.media_source.fetch_stock_ticker",
                   return_value={"price": 100.0, "change": 1.0, "pct_change": 1.0}), \
             patch("divoom_lib.utils.media_source.render_stock_ticker_frame",
                   return_value=_P("/tmp/ticker_preview_test.png")), \
             patch.object(type(self.api), "_frame_to_data_url",
                          staticmethod(lambda p: "data:image/png;base64,AAA")):
            res = json.loads(self.api.get_ticker_preview("AAPL", 32))
            self.assertTrue(res["ok"])
            self.assertEqual(res["size"], 32)
            self.assertTrue(res["preview"].startswith("data:image/png;base64,"))

    def test_apply_stock_ticker_no_target(self):
        """5.a: clear failure when there is no connected device."""
        self.api.current_divoom = None
        self.api.wall_slots = {}
        with patch("divoom_lib.utils.media_source.fetch_stock_ticker",
                   return_value={"price": 1.0, "change": 0.0, "pct_change": 0.0}):
            res = json.loads(self.api.apply_stock_ticker("AAPL"))
            self.assertFalse(res["success"])
            self.assertEqual(res["error"], "No device connected")

    def test_ticker_persistence(self):
        """5.e: tickers save/load, de-duped and upper-cased."""
        import tempfile, os
        from pathlib import Path as _P
        tmp = _P(tempfile.mkdtemp()) / "tickers.json"
        # Override the setUp-wide Path.exists=False so the read path works.
        with patch.object(type(self.api), "_tickers_path", lambda self: tmp), \
             patch("pathlib.Path.exists", return_value=True):
            self.assertTrue(self.api.set_tickers(json.dumps(["aapl", "AAPL", "btc-usd", ""])))
            self.assertEqual(json.loads(self.api.get_tickers()), ["AAPL", "BTC-USD"])

    def _sysmon_client(self, size=32, **overrides):
        """A daemon stub whose reply carries a correctly sized RGB frame."""
        import base64 as _b64
        reply = {"success": True, "size": size, "cpu": 12, "mem": 43, "battery": 80,
                 "frame_rgb_b64": _b64.b64encode(bytes(size * size * 3)).decode()}
        reply.update(overrides)
        stub = MagicMock()
        stub.sysmon.return_value = reply
        return stub

    def test_system_stats_comes_from_the_daemon_not_a_second_renderer(self):
        """Area 7 / R67-C2: the GUI is a CLIENT for sysmon, not a renderer.

        The seam mocked here is the daemon call. It used to be
        `media_source.get_system_stats` + `render_system_stats_frame`, run in
        the GUI process — a second implementation of the widget the device gets
        from `live_jobs/render.rs`.
        """
        client = self._sysmon_client(size=32)
        with patch.object(type(self.api), "_client", lambda self: client), \
             patch.object(type(self.api), "_frame_to_data_url",
                          staticmethod(lambda p: "data:image/png;base64,BBB")):
            prev = json.loads(self.api.get_system_stats_preview(32))
            self.assertTrue(prev["ok"], prev)
            self.assertEqual(prev["stats"]["cpu"], 12)
            self.assertEqual(prev["stats"]["mem"], 43)
            self.assertEqual(prev["stats"]["battery"], 80)
            self.assertTrue(prev["preview"].startswith("data:image/png;base64,"))
            client.sysmon.assert_called_once_with(size=32)

            # apply with no device → clear failure, but the stats still report
            self.api.current_divoom = None
            self.api.wall_slots = {}
            res = json.loads(self.api.apply_system_stats())
            self.assertFalse(res["success"])
            self.assertEqual(res["error"], "No device connected")
            self.assertEqual(res["stats"]["cpu"], 12)

    def test_system_stats_refuses_a_short_frame_instead_of_drawing_it(self):
        """A truncated buffer must not be shown as if it were the device's frame."""
        client = self._sysmon_client(size=32, frame_rgb_b64="AAAA")
        with patch.object(type(self.api), "_client", lambda self: client):
            prev = json.loads(self.api.get_system_stats_preview(32))
            self.assertFalse(prev["ok"])
            self.assertIn("expected", prev["error"])

    def test_system_stats_reports_an_unavailable_daemon(self):
        """No daemon is an honest error, not an idle-looking zeroed gauge."""
        with patch.object(type(self.api), "_client", lambda self: None):
            prev = json.loads(self.api.get_system_stats_preview(16))
            self.assertFalse(prev["ok"])
            self.assertIn("background service", prev["error"])

    def test_unreachable_daemon_gets_a_sentence_not_an_errno(self):
        """`[Errno 2] No such file or directory` in a widget card is noise.

        The transport marks unreachability with a FIELD (`unreachable`), so the
        GUI can say something human without matching on error text.
        """
        client = MagicMock()
        client.sysmon.return_value = {
            "success": False,
            "error": "[Errno 2] No such file or directory",
            "unreachable": True,
        }
        with patch.object(type(self.api), "_client", lambda self: client):
            prev = json.loads(self.api.get_system_stats_preview(16))
        self.assertFalse(prev["ok"])
        self.assertNotIn("Errno", prev["error"], "raw errno must not reach the card")
        self.assertIn("background service", prev["error"])

    def test_the_failure_reason_is_read_from_the_clients_own_socket(self):
        """The `<socket>.failure` sidecar lives next to the socket in USE.

        Reading it from an env-var guess means a session started with --socket
        silently falls back to the generic message, exactly when the specific
        one would help most.
        """
        import tempfile
        from pathlib import Path as _P
        sock = _P(tempfile.mkdtemp()) / "custom.sock"
        sock.with_suffix(".sock.failure").write_text(
            "reason: /tmp/custom.sock is a regular file, not a socket\n"
            "remedy: Move or delete that file yourself, then start the daemon again.\n"
            "transient: false\n")
        client = MagicMock()
        client.socket_path = str(sock)
        client.sysmon.return_value = {"success": False, "error": "[Errno 2]",
                                      "unreachable": True}
        with patch.object(type(self.api), "_client", lambda self: client):
            prev = json.loads(self.api.get_system_stats_preview(16))
        self.assertFalse(prev["ok"])
        self.assertIn("not a socket", prev["error"],
                      "the daemon's own recorded reason should reach the card")

    def test_a_daemon_level_error_is_surfaced_verbatim(self):
        """The opposite case: the daemon ANSWERED, so use its words, not ours."""
        client = MagicMock()
        client.sysmon.return_value = {"success": False, "error": "sysmon is disabled"}
        with patch.object(type(self.api), "_client", lambda self: client):
            prev = json.loads(self.api.get_system_stats_preview(16))
        self.assertFalse(prev["ok"])
        self.assertEqual(prev["error"], "sysmon is disabled")

    @patch("urllib.request.urlopen")
    def test_fetch_gallery_and_batch_sync(self, mock_urlopen):
        """Test cloud gallery catalog scraping and concurrent monthly best async streams."""
        # Mock fetch_gallery HTTP JSON response
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "FileList": [
                {"FileName": "NeonSkull", "FileId": "9999", "LikeCnt": 1500, "FileType": 5, "PixelAmbId": "amb123"}
            ]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        # Mock authentication credentials
        self.api.cached_creds = MagicMock()
        self.api.cached_creds.token = "token123"
        self.api.cached_creds.user_id = 99
        self.api.cached_creds.is_valid.return_value = True

        # Pre-seed cached data for the offline cache loader check.
        # Use a real-looking file_id (not "9999") so the rebuild-on-stale path
        # doesn't trigger (see gui/gallery_sync.py load_cached_gallery).
        cached_items = [
            {"name": "NeonSkull", "file_id": "group1/M00/01/AAA_neon", "likes": 1500, "magic": 5, "preview_url": "data:image/png;base64,..."}
        ]

        import threading
        import time

        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.read_text", return_value=json.dumps(cached_items)):
            gallery_json = self.api.fetch_gallery(classify=1)
            gallery = json.loads(gallery_json)
            self.assertEqual(len(gallery), 1)
            self.assertEqual(gallery[0]["name"], "NeonSkull")
            self.assertEqual(gallery[0]["file_id"], "group1/M00/01/AAA_neon")

            # Wait for background fetch worker to finish executing under mocked Path
            for t in threading.enumerate():
                if t.name == "DivoomGalleryFetch":
                    t.join(timeout=5.0)

        # R17 P5: the daemon downloads + streams the asset; the GUI delegates
        # via sync_artwork. Wall target because wall_slots is set + no single
        # device is connected.
        fake = MagicMock()
        fake.wall_configure.return_value = {"success": True, "wall": True}
        fake.sync_artwork.return_value = {"success": True}
        self.api._daemon_client = fake
        self.api.wall_slots = {"AA:BB:CC:DD:EE:FF": {"x": 0, "y": 0, "size": 16}}

        artwork_json = json.dumps({"file_id": "9999"})
        sync_success = self.api.batch_sync_artwork(artwork_json)
        self.assertTrue(sync_success)
        fake.sync_artwork.assert_called_once_with("9999", target="wall")

    def test_stock_ticker_apply(self):
        """Test Yahoo Stock ticker downsampling and display coordination pipeline."""
        mock_data = {"price": 105.5, "change": 1.2, "pct_change": 1.15}
        with patch("divoom_lib.utils.media_source.fetch_stock_ticker", return_value=mock_data) as mock_fetch, \
             patch("divoom_lib.utils.media_source.render_stock_ticker_frame", return_value=Path("/tmp/ticker.png")) as mock_render:
            
            # Single connected device path
            self.api.current_divoom = MagicMock()
            self.api.current_divoom.is_connected = True
            self.api.current_divoom.display.show_image = AsyncMock(return_value=True)

            res = self.api.apply_stock_ticker("AAPL")
            res_dict = json.loads(res)
            self.assertTrue(res_dict["success"])
            self.assertEqual(res_dict["price"], 105.5)
            mock_fetch.assert_called_with("AAPL")
            mock_render.assert_called_with("AAPL", mock_data, size=16)

    def test_lan_device_operations(self):
        """Add / load / delete LAN devices against a real temp presets file (the
        writers are atomic — temp-file + os.replace — so a write_text mock would
        be bypassed; use real storage instead)."""
        import tempfile
        # This test needs a real file on disk, so drop setUp's global
        # Path.exists/Path.home patches for its duration.
        self.presets_patcher.stop()
        self.home_patcher.stop()
        try:
            with tempfile.TemporaryDirectory() as d:
                presets = Path(d) / "presets.json"
                with patch.object(self.api, "_get_presets_file", return_value=presets):
                    # Add device
                    self.assertTrue(self.api.add_lan_device("192.168.1.100", 123))

                    # Load devices
                    devices = json.loads(self.api.load_lan_devices())
                    self.assertEqual(len(devices), 1)
                    self.assertEqual(devices[0]["ip"], "192.168.1.100")
                    self.assertEqual(devices[0]["token"], 123)

                    # Delete device
                    self.assertTrue(self.api.delete_lan_device("192.168.1.100"))

                    # Load again to check empty
                    self.assertEqual(json.loads(self.api.load_lan_devices()), [])
        finally:
            # Restore so tearDown's stop() calls match.
            self.presets_patcher.start()
            self.home_patcher.start()

    def test_run_async_times_out_instead_of_hanging(self):
        """A3: a wedged async chain must not block the JS-API thread forever — it
        raises after the timeout instead."""
        async def _hang():
            await asyncio.sleep(5)
        with self.assertRaises(RuntimeError):
            self.api._run_async(_hang(), timeout=0.2)

    def test_run_async_returns_result(self):
        async def _quick():
            return 42
