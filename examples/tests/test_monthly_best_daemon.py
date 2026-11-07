#!/usr/bin/env python3
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


class TestPushItemsToTarget(unittest.IsolatedAsyncioTestCase):
    """Covers monthly_best_daemon._push_items_to_target (lines 298-332)."""

    async def test_push_discovers_device_and_streams_all_item_types(self):
        """No target_addr given -> discovery path is used; a gif item, a bin
        item, and an unknown-type item are all pushed (success + failure +
        unknown branches), inter-item sleep(15) fires, and disconnect runs
        because is_connected is True at the end (lines 300-332)."""
        ble_device = SimpleNamespace(name="Timoo-1234")
        mock_discover = AsyncMock(return_value=(ble_device, "AA:BB:CC:DD:EE:FF"))

        mock_instance = MagicMock()
        mock_instance.connect = AsyncMock()
        mock_instance.disconnect = AsyncMock()
        mock_instance.is_connected = True
        mock_instance.display.show_image = AsyncMock(side_effect=[True, False])
        mock_instance.animation.stream_animation_8b = AsyncMock(return_value=True)
        mock_divoom_cls = MagicMock(return_value=mock_instance)

        items = [
            {"type": "gif", "path": "/tmp/a.gif", "name": "GifOk"},
            {"type": "gif", "path": "/tmp/b.gif", "name": "GifFail"},
            {"type": "bin", "path": "/tmp/c.bin", "name": "BinItem", "bytes": b"xyz"},
            {"type": "weird", "path": "/tmp/d", "name": "Unknown"},
        ]
        logger = MagicMock()

        with (
            patch("divoom_legacy.monthly_best_daemon.discovery.discover_device", mock_discover),
            patch("divoom_legacy.monthly_best_daemon.Divoom", mock_divoom_cls),
            patch("divoom_legacy.monthly_best_daemon.asyncio.sleep", AsyncMock()) as mock_sleep,
        ):
            await monthly_best_daemon._push_items_to_target(None, "Timoo", items, logger)

        mock_discover.assert_awaited_once_with(name_substring="Timoo", address=None)
        mock_divoom_cls.assert_called_once()
        _, kwargs = mock_divoom_cls.call_args
        self.assertEqual(kwargs["mac"], "AA:BB:CC:DD:EE:FF")
        self.assertEqual(kwargs["device_name"], "Timoo-1234")
        mock_instance.connect.assert_awaited_once()
        self.assertEqual(mock_instance.display.show_image.await_count, 2)
        mock_instance.animation.stream_animation_8b.assert_awaited_once_with(b"xyz")
        # sleep(15) fires between items but not after the last one.
        self.assertEqual(mock_sleep.await_count, 3)
        mock_instance.disconnect.assert_awaited_once()

    async def test_push_no_device_found_is_caught(self):
        """discover_device finding nothing raises RuntimeError internally,
        which is caught by the outer except -- no disconnect is attempted
        because divoom was never constructed (lines 304-305, 327-332)."""
        mock_discover = AsyncMock(return_value=(None, None))
        mock_divoom_cls = MagicMock()

        with (
            patch("divoom_legacy.monthly_best_daemon.discovery.discover_device", mock_discover),
            patch("divoom_legacy.monthly_best_daemon.Divoom", mock_divoom_cls),
        ):
            # Must not raise -- the error is swallowed and logged.
            await monthly_best_daemon._push_items_to_target(
                None, "Nonexistent", [{"type": "gif", "path": "x", "name": "n"}], MagicMock()
            )

        mock_divoom_cls.assert_not_called()

    async def test_push_connect_failure_skips_disconnect(self):
        """An explicit target_addr skips discovery; a connect() failure is
        caught, and since is_connected stays False, disconnect() is never
        called in the finally block (lines 309-312, 327-332)."""
        mock_instance = MagicMock()
        mock_instance.connect = AsyncMock(side_effect=ConnectionError("BLE gone"))
        mock_instance.disconnect = AsyncMock()
        mock_instance.is_connected = False
        mock_divoom_cls = MagicMock(return_value=mock_instance)
        mock_discover = AsyncMock()

        with (
            patch("divoom_legacy.monthly_best_daemon.discovery.discover_device", mock_discover),
            patch("divoom_legacy.monthly_best_daemon.Divoom", mock_divoom_cls),
        ):
            await monthly_best_daemon._push_items_to_target(
                "11:22:33:44:55:66", "Timoo", [{"type": "gif", "path": "x", "name": "n"}], MagicMock()
            )

        mock_discover.assert_not_awaited()
        mock_instance.connect.assert_awaited_once()
        mock_instance.disconnect.assert_not_awaited()


class TestMainAsync(unittest.IsolatedAsyncioTestCase):
    """Covers monthly_best_daemon.main_async orchestration (lines 103-211).

    _fetch_and_download and _push_items_to_target are exercised directly in
    the classes above, so here they're mocked out and we assert on the
    orchestration: arg parsing, credential/virtual-device loading, hot-channel
    config grouping, and the loop/sleep control flow.
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._home = Path(self._tmpdir.name)
        self._home_patch = patch("pathlib.Path.home", return_value=self._home)
        self._home_patch.start()
        self.creds = SimpleNamespace(token=1, user_id=2)

    def tearDown(self):
        self._home_patch.stop()
        self._tmpdir.cleanup()

    @staticmethod
    def _hc(**overrides):
        cfg = {"enabled": False, "interval": 3600, "classify": 18, "targets": [], "device_galleries": {}}
        cfg.update(overrides)
        return cfg

    async def test_dry_run_legacy_skips_push(self):
        fetch_mock = AsyncMock(return_value=[{"type": "gif", "path": "x", "name": "n"}])
        push_mock = AsyncMock()
        with (
            patch.object(sys, "argv", ["monthly_best_daemon.py", "--dry-run"]),
            patch("divoom_lib.divoom_auth.get_credentials", return_value=self.creds),
            patch("divoom_legacy.hotchannel_config.load_config", return_value=self._hc()),
            patch.object(monthly_best_daemon, "_fetch_and_download", fetch_mock),
            patch.object(monthly_best_daemon, "_push_items_to_target", push_mock),
        ):
            await monthly_best_daemon.main_async()

        fetch_mock.assert_awaited_once()
        push_mock.assert_not_awaited()

    async def test_legacy_mode_pushes_when_items_found(self):
        fetch_mock = AsyncMock(return_value=[{"type": "gif", "path": "x", "name": "n"}])
        push_mock = AsyncMock()
        with (
            patch.object(sys, "argv", ["monthly_best_daemon.py"]),
            patch("divoom_lib.divoom_auth.get_credentials", return_value=self.creds),
            patch("divoom_legacy.hotchannel_config.load_config", return_value=self._hc()),
            patch.object(monthly_best_daemon, "_fetch_and_download", fetch_mock),
            patch.object(monthly_best_daemon, "_push_items_to_target", push_mock),
        ):
            await monthly_best_daemon.main_async()

        push_mock.assert_awaited_once()
        args, _ = push_mock.call_args
        self.assertEqual(args[0], None)  # target address (falls back to name discovery)
        self.assertEqual(args[1], "Timoo")

    async def test_credentials_failure_exits(self):
        with (
            patch.object(sys, "argv", ["monthly_best_daemon.py"]),
            patch("divoom_lib.divoom_auth.get_credentials", side_effect=RuntimeError("no login")),
            patch("divoom_legacy.hotchannel_config.load_config", return_value=self._hc()),
            patch.object(monthly_best_daemon, "_fetch_and_download", AsyncMock()),
            patch.object(monthly_best_daemon, "_push_items_to_target", AsyncMock()),
        ):
            with self.assertRaises(SystemExit):
                await monthly_best_daemon.main_async()

    async def test_virtual_device_config_loaded(self):
        cache_path = self._home / ".config" / "divoom-control" / "virtual_device.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"BluetoothDeviceId": 123, "DevicePassword": 456}))

        fetch_mock = AsyncMock(return_value=[])
        with (
            patch.object(sys, "argv", ["monthly_best_daemon.py", "--dry-run"]),
            patch("divoom_lib.divoom_auth.get_credentials", return_value=self.creds),
            patch("divoom_legacy.hotchannel_config.load_config", return_value=self._hc()),
            patch.object(monthly_best_daemon, "_fetch_and_download", fetch_mock),
            patch.object(monthly_best_daemon, "_push_items_to_target", AsyncMock()),
        ):
            await monthly_best_daemon.main_async()

        call_args = fetch_mock.call_args[0]
        self.assertEqual(call_args[3], 123)  # device_id
        self.assertEqual(call_args[4], 456)  # device_pw

    async def test_virtual_device_config_corrupt_falls_back_to_zero(self):
        cache_path = self._home / ".config" / "divoom-control" / "virtual_device.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text("{not valid json")

        fetch_mock = AsyncMock(return_value=[])
        with (
            patch.object(sys, "argv", ["monthly_best_daemon.py", "--dry-run"]),
            patch("divoom_lib.divoom_auth.get_credentials", return_value=self.creds),
            patch("divoom_legacy.hotchannel_config.load_config", return_value=self._hc()),
            patch.object(monthly_best_daemon, "_fetch_and_download", fetch_mock),
            patch.object(monthly_best_daemon, "_push_items_to_target", AsyncMock()),
        ):
            await monthly_best_daemon.main_async()

        call_args = fetch_mock.call_args[0]
        self.assertEqual(call_args[3], 0)
        self.assertEqual(call_args[4], 0)

    async def test_use_config_multi_classify_groups_and_loop_sleeps(self):
        """--use-config with two targets on different gallery styles hits the
        multi-group push branch (193-199); enabled=True keeps args.loop True
        so the loop reaches asyncio.sleep(interval) (210-211), which we make
        raise to end the test deterministically."""
        hc_cfg = self._hc(enabled=True, interval=77, targets=["AA:BB", "CC:DD"], device_galleries={"AA:BB": 9})
        fetch_mock = AsyncMock(return_value=[{"type": "gif", "path": "x", "name": "n"}])
        push_mock = AsyncMock()
        sleep_mock = AsyncMock(side_effect=RuntimeError("stop-test-loop"))

        with (
            patch.object(sys, "argv", ["monthly_best_daemon.py", "--use-config"]),
            patch("divoom_lib.divoom_auth.get_credentials", return_value=self.creds),
            patch("divoom_legacy.hotchannel_config.load_config", return_value=hc_cfg),
            patch.object(monthly_best_daemon, "_fetch_and_download", fetch_mock),
            patch.object(monthly_best_daemon, "_push_items_to_target", push_mock),
            patch("divoom_legacy.monthly_best_daemon.asyncio.sleep", sleep_mock),
        ):
            with self.assertRaises(RuntimeError):
                await monthly_best_daemon.main_async()

        self.assertEqual(fetch_mock.await_count, 2)  # one per classify group
        self.assertEqual(push_mock.await_count, 2)  # one per target
        pushed_targets = {c.args[0] for c in push_mock.await_args_list}
        self.assertEqual(pushed_targets, {"AA:BB", "CC:DD"})
        sleep_mock.assert_awaited_once_with(77)

    async def test_use_config_reload_exception_is_caught(self):
        """The per-cycle config reload (inside the while loop) raising is
        caught and logged; the previous cycle's classify/targets are reused
        so the push still runs before the (disabled) loop breaks
        (lines 176-179)."""
        hc_cfg_initial = self._hc(enabled=False, targets=["X"])
        fetch_mock = AsyncMock(return_value=[{"type": "gif", "path": "x", "name": "n"}])
        push_mock = AsyncMock()

        with (
            patch.object(sys, "argv", ["monthly_best_daemon.py", "--use-config"]),
            patch("divoom_lib.divoom_auth.get_credentials", return_value=self.creds),
            patch(
                "divoom_legacy.hotchannel_config.load_config", side_effect=[hc_cfg_initial, RuntimeError("disk fail")]
            ),
            patch.object(monthly_best_daemon, "_fetch_and_download", fetch_mock),
            patch.object(monthly_best_daemon, "_push_items_to_target", push_mock),
        ):
            await monthly_best_daemon.main_async()

        fetch_mock.assert_awaited_once()
        push_mock.assert_awaited_once()

    async def test_use_config_disabled_breaks_before_push(self):
        """When --loop is passed explicitly but the reloaded config says
        disabled, the daemon prints and breaks before ever fetching/pushing
        (lines 181-183)."""
        hc_cfg = self._hc(enabled=False)
        fetch_mock = AsyncMock()
        push_mock = AsyncMock()

        with (
            patch.object(sys, "argv", ["monthly_best_daemon.py", "--use-config", "--loop"]),
            patch("divoom_lib.divoom_auth.get_credentials", return_value=self.creds),
            patch("divoom_legacy.hotchannel_config.load_config", return_value=hc_cfg),
            patch.object(monthly_best_daemon, "_fetch_and_download", fetch_mock),
            patch.object(monthly_best_daemon, "_push_items_to_target", push_mock),
        ):
            await monthly_best_daemon.main_async()

        fetch_mock.assert_not_awaited()
        push_mock.assert_not_awaited()

    async def test_use_config_no_targets_warns_and_still_falls_back(self):
        """An empty target list under --use-config warns up front
        (lines 130-132); since enabled=False the very next reload at the top
        of the loop breaks before any fetch/push is attempted."""
        hc_cfg = self._hc(enabled=False, targets=[])
        fetch_mock = AsyncMock(return_value=[])
        push_mock = AsyncMock()

        with (
            patch.object(sys, "argv", ["monthly_best_daemon.py", "--use-config"]),
            patch("divoom_lib.divoom_auth.get_credentials", return_value=self.creds),
            patch("divoom_legacy.hotchannel_config.load_config", return_value=hc_cfg),
            patch.object(monthly_best_daemon, "_fetch_and_download", fetch_mock),
            patch.object(monthly_best_daemon, "_push_items_to_target", push_mock),
            patch("builtins.print") as mock_print,
        ):
            await monthly_best_daemon.main_async()

        fetch_mock.assert_not_awaited()
        push_mock.assert_not_awaited()
        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list)
        self.assertIn("Hot-channel config has no selected target devices", printed)


if __name__ == "__main__":
    unittest.main()
