#!/usr/bin/env python3
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from pathlib import Path
from PIL import Image

sys.path.append(str(Path(__file__).parent.parent))

from divoom_lib.wall import DivoomWall, wall_resolution

class TestDivoomWall(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.device_configs = [
            {"mac": "AA:BB:CC:DD:EE:01", "x": 0, "y": 0, "size": 16}, # Top-left
            {"mac": "AA:BB:CC:DD:EE:02", "x": 1, "y": 0, "size": 16}, # Top-right
            {"mac": "AA:BB:CC:DD:EE:03", "x": 0, "y": 1, "size": 16}, # Bottom-left
            {"mac": "AA:BB:CC:DD:EE:04", "x": 1, "y": 1, "size": 16}  # Bottom-right
        ]

    @patch('divoom_lib.wall.Divoom', new_callable=MagicMock)
    def test_wall_init(self, mock_divoom_class):
        """Test DivoomWall initialization and dimensions."""
        wall = DivoomWall(self.device_configs)
        
        self.assertEqual(len(wall.devices), 4)
        self.assertEqual(wall.total_width, 32)
        self.assertEqual(wall.total_height, 32)
        self.assertEqual(wall.grid_unit_size, 16)

    @patch('divoom_lib.wall.Divoom', new_callable=MagicMock)
    async def test_wall_connect_disconnect(self, mock_divoom_class):
        """Test DivoomWall connect and disconnect async methods."""
        # Setup mocks — start DISCONNECTED and flip to connected on connect(),
        # mirroring reality. The P3 honest connect (ensure_connected) skips a
        # device that already reports is_connected, so a mock pinned True would
        # never call connect().
        mock_clients = []
        for _ in range(4):
            mc = MagicMock()

            async def _connect(_m=mc):
                _m.is_connected = True
                _m.is_alive = True
            mc.connect = AsyncMock(side_effect=_connect)
            mc.disconnect = AsyncMock(return_value=None)
            mc.is_connected = False
            # R53: model is_alive honestly (a real device is not alive until
            # connected) — else the is_alive-aware ensure_connected fast-path
            # would treat the auto-truthy MagicMock attr as "already alive".
            mc.is_alive = False
            mock_clients.append(mc)

        mock_divoom_class.side_effect = mock_clients
        
        wall = DivoomWall(self.device_configs)
        await wall.connect()
        
        for mc in mock_clients:
            mc.connect.assert_called_once()
            
        self.assertTrue(wall.is_connected)
        
        await wall.disconnect()
        for mc in mock_clients:
            mc.disconnect.assert_called_once()

    @patch('divoom_lib.wall.Divoom', new_callable=MagicMock)
    @patch('divoom_lib.wall.Image.open')
    async def test_wall_show_image(self, mock_image_open, mock_divoom_class):
        """Test DivoomWall splitting and cropping logic for show_image."""
        # Mock main image
        mock_img = MagicMock(spec=Image.Image)
        mock_img.is_animated = False
        mock_img.crop = MagicMock(return_value=mock_img)
        mock_img.resize = MagicMock(return_value=mock_img)
        mock_image_open.return_value = mock_img
        
        # Setup mock Divoom clients
        mock_clients = []
        for _ in range(4):
            mc = MagicMock()
            mc.display.show_image = AsyncMock(return_value=True)
            mock_clients.append(mc)
        mock_divoom_class.side_effect = mock_clients
        
        orig_exists = Path.exists
        def mock_exists(self_path):
            return "mock_path.png" in str(self_path)

        Path.exists = mock_exists
        try:
            wall = DivoomWall(self.device_configs)
            success = await wall.show_image("mock_path.png")
            self.assertTrue(success)
        finally:
            Path.exists = orig_exists
            
            # Verify cropping bounds for each grid coordinate
            # Top-left slot (0, 0)
            mock_img.resize.assert_called_with((32, 32), Image.NEAREST)
            mock_img.crop.assert_any_call((0, 0, 16, 16))
            # Top-right slot (1, 0)
            mock_img.crop.assert_any_call((16, 0, 32, 16))
            # Bottom-left slot (0, 1)
            mock_img.crop.assert_any_call((0, 16, 16, 32))
            # Bottom-right slot (1, 1)
            mock_img.crop.assert_any_call((16, 16, 32, 32))
            
            # Verify all Divoom show_image methods were called
            for mc in mock_clients:
                mc.display.show_image.assert_called_once()

    @patch('divoom_lib.wall.Divoom', new_callable=MagicMock)
    @patch('divoom_lib.wall.ImageSequence.Iterator')
    @patch('divoom_lib.wall.Image.open')
    async def test_wall_show_image_zero_frames_reports_failure(
        self, mock_image_open, mock_iter, mock_divoom_class
    ):
        """R53.28: a truncated/animated source that yields 0 frames must make
        show_image report FAILURE (the screens got nothing) — not vacuous
        success. Teeth: the old code did a bare `continue`, leaving all_ok=True
        with an empty task list, so it returned True for a no-op render.
        """
        mock_img = MagicMock(spec=Image.Image)
        mock_img.is_animated = True
        mock_image_open.return_value = mock_img
        mock_iter.return_value = iter([])  # animated, but zero frames

        mock_clients = []
        for _ in range(4):
            mc = MagicMock()
            mc.display.show_image = AsyncMock(return_value=True)
            mock_clients.append(mc)
        mock_divoom_class.side_effect = mock_clients

        orig_exists = Path.exists
        Path.exists = lambda self_path: "mock_path.gif" in str(self_path)
        try:
            wall = DivoomWall(self.device_configs)
            success = await wall.show_image("mock_path.gif")
            self.assertFalse(success)  # NOT vacuous True
            # Nothing was pushed to any device.
            for mc in mock_clients:
                mc.display.show_image.assert_not_called()
        finally:
            Path.exists = orig_exists

    @patch('divoom_lib.wall.Divoom', new_callable=MagicMock)
    async def test_wall_set_light_and_clock(self, mock_divoom_class):
        """Test DivoomWall batch operations: set_light and show_clock."""
        mock_clients = []
        for _ in range(4):
            mc = MagicMock()
            mc.display.show_light = AsyncMock(return_value=True)
            mc.display.show_clock = AsyncMock(return_value=True)
            mock_clients.append(mc)
        mock_divoom_class.side_effect = mock_clients
        
        wall = DivoomWall(self.device_configs)
        
        res_light = await wall.set_light("FF0000", brightness=80)
        self.assertTrue(res_light)
        for mc in mock_clients:
            mc.display.show_light.assert_called_once_with(color="FF0000", brightness=80)
            
        res_clock = await wall.show_clock(clock=2)
        self.assertTrue(res_clock)
        for mc in mock_clients:
            mc.display.show_clock.assert_called_once_with(clock=2)

    @patch('divoom_lib.wall.Divoom', new_callable=MagicMock)
    async def test_wall_switch_channel_volume_brightness(self, mock_divoom_class):
        """R17 P5: wall-level fan-out methods added so the daemon-owned wall is
        callable via a single device_call (no GUI-side per-device iteration)."""
        mock_clients = []
        for _ in range(4):
            mc = MagicMock()
            mc.lan = None
            mc.display.switch_channel = AsyncMock(return_value=True)
            mc.music.set_volume = AsyncMock(return_value=True)
            mc.device.set_brightness = AsyncMock(return_value=True)
            mock_clients.append(mc)
        mock_divoom_class.side_effect = mock_clients

        wall = DivoomWall(self.device_configs)

        self.assertTrue(await wall.switch_channel("cloud"))
        for mc in mock_clients:
            mc.display.switch_channel.assert_called_once_with("cloud")

        self.assertTrue(await wall.set_volume(7))
        for mc in mock_clients:
            mc.music.set_volume.assert_called_once_with(7)

        # No LAN transport on any panel -> BLE device.set_brightness path.
        self.assertTrue(await wall.set_brightness(55))
        for mc in mock_clients:
            mc.device.set_brightness.assert_called_once_with(55)

    @patch('divoom_lib.wall.Divoom', new_callable=MagicMock)
    async def test_wall_push_text(self, mock_divoom_class):
        """Wall push_text runs the LPWA sequence on every screen with its size."""
        from divoom_lib.models import LPWA_CONTROL_CONTENT
        mock_clients = []
        for _ in range(4):
            mc = MagicMock()
            mc.text.set_light_phone_word_attr = AsyncMock(return_value=True)
            mock_clients.append(mc)
        mock_divoom_class.side_effect = mock_clients

        wall = DivoomWall(self.device_configs)
        self.assertTrue(await wall.push_text("HI", color="#00FF00", speed=30))
        for mc in mock_clients:
            controls = [c.args[0] for c in mc.text.set_light_phone_word_attr.call_args_list]
            self.assertIn(LPWA_CONTROL_CONTENT, controls)


    @patch('divoom_lib.wall.Divoom', new_callable=MagicMock)
    async def test_wall_show_image_missing_file_returns_false(self, mock_divoom_class):
        """show_image on a nonexistent path must fail fast (no crop/stream attempt)."""
        wall = DivoomWall(self.device_configs)
        ok = await wall.show_image("/no/such/file/anywhere.png")
        self.assertFalse(ok)

    @patch('divoom_lib.wall.Divoom', new_callable=MagicMock)
    async def test_is_alive_true_when_all_slots_alive(self, mock_divoom_class):
        mock_clients = []
        for _ in range(4):
            mc = MagicMock()
            mc.is_alive = True
            mock_clients.append(mc)
        mock_divoom_class.side_effect = mock_clients
        wall = DivoomWall(self.device_configs)
        self.assertTrue(wall.is_alive)

    @patch('divoom_lib.wall.Divoom', new_callable=MagicMock)
    async def test_is_alive_false_when_no_devices(self, mock_divoom_class):
        wall = DivoomWall(self.device_configs)
        wall.devices = []
        self.assertFalse(wall.is_alive)

    @patch('divoom_lib.wall.Divoom', new_callable=MagicMock)
    async def test_wall_set_brightness_lan_path(self, mock_divoom_class):
        """R17: a slot with a LAN transport attached uses lan.set_brightness,
        not the BLE device.set_brightness fallback."""
        mock_clients = []
        for _ in range(4):
            mc = MagicMock()
            mc.lan = MagicMock()
            mc.lan.set_brightness = AsyncMock(return_value={"error_code": 0})
            mock_clients.append(mc)
        mock_divoom_class.side_effect = mock_clients
        wall = DivoomWall(self.device_configs)
        self.assertTrue(await wall.set_brightness(42))
        for mc in mock_clients:
            mc.lan.set_brightness.assert_called_once_with(42)

    @patch('divoom_lib.wall.Divoom', new_callable=MagicMock)
    @patch('divoom_lib.wall.Image.open')
    async def test_wall_show_image_partial_slot_failure(self, mock_image_open, mock_divoom_class):
        """A slot whose show_image returns False (not an exception) must flip
        all_ok to False (the `elif not res` branch)."""
        mock_img = MagicMock(spec=Image.Image)
        mock_img.is_animated = False
        mock_img.crop = MagicMock(return_value=mock_img)
        mock_img.resize = MagicMock(return_value=mock_img)
        mock_image_open.return_value = mock_img

        mock_clients = []
        for i in range(4):
            mc = MagicMock()
            # First slot's push reports a soft failure (False, no exception).
            mc.display.show_image = AsyncMock(return_value=(i != 0))
            mock_clients.append(mc)
        mock_divoom_class.side_effect = mock_clients

        orig_exists = Path.exists
        Path.exists = lambda self_path: "mock_path.png" in str(self_path)
        try:
            wall = DivoomWall(self.device_configs)
            ok = await wall.show_image("mock_path.png")
            self.assertFalse(ok)
        finally:
            Path.exists = orig_exists

    @patch('divoom_lib.wall.Divoom', new_callable=MagicMock)
    async def test_get_last_previews_encodes_data_urls(self, mock_divoom_class):
        """get_last_previews base64-encodes cached preview bytes and picks the
        MIME type from the GIF magic bytes vs PNG default."""
        wall = DivoomWall(self.device_configs)
        wall.last_previews = {
            "AA:BB:CC:DD:EE:01": b"GIF89a\x00\x00fakegifdata",
            "AA:BB:CC:DD:EE:02": b"\x89PNGfakepngdata",
            "AA:BB:CC:DD:EE:03": b"",  # empty -> skipped
        }
        previews = wall.get_last_previews()
        self.assertIn("AA:BB:CC:DD:EE:01", previews)
        self.assertTrue(previews["AA:BB:CC:DD:EE:01"].startswith("data:image/gif;base64,"))
        self.assertTrue(previews["AA:BB:CC:DD:EE:02"].startswith("data:image/png;base64,"))
        self.assertNotIn("AA:BB:CC:DD:EE:03", previews)


    @patch('divoom_lib.wall.Divoom', new_callable=MagicMock)
    async def test_grid_animated_image_real_frames_skips_freeform_resize(self, mock_divoom_class):
        """Uniform-grid (non-free-form) animated show_image: the per-frame
        loop must take the `is_free_form is False` branch (crop only, no
        extra per-slot resize)."""
        import tempfile
        mock_clients = []
        for _ in range(4):
            mc = MagicMock()
            mc.display.show_image = AsyncMock(return_value=True)
            mock_clients.append(mc)
        mock_divoom_class.side_effect = mock_clients

        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as home_td:
            gif_path = str(Path(td) / "grid_anim.gif")
            frame1 = Image.new("RGB", (32, 32), (255, 0, 0))
            frame2 = Image.new("RGB", (32, 32), (0, 255, 0))
            frame1.save(gif_path, save_all=True, append_images=[frame2], duration=100, loop=0)

            orig_home = Path.home
            Path.home = staticmethod(lambda: Path(home_td))
            try:
                wall = DivoomWall(self.device_configs)
                ok = await wall.show_image(gif_path)
                self.assertTrue(ok)
                for mc in mock_clients:
                    mc.display.show_image.assert_called_once()
            finally:
                Path.home = orig_home


class TestDivoomWallFreeForm(unittest.IsolatedAsyncioTestCase):
    """Free-form (absolute width/height, non-grid) layout — the show_image crop
    math takes a different branch (left/upper/right/lower from absolute
    coordinates, plus a per-slot resize down to `size`) than the uniform-grid
    layout covered by TestDivoomWall."""

    def setUp(self):
        self.device_configs = [
            {"mac": "AA:BB:CC:DD:EE:01", "x": 0, "y": 0, "width": 32, "height": 16, "size": 16},
            {"mac": "AA:BB:CC:DD:EE:02", "x": 32, "y": 0, "width": 32, "height": 16, "size": 16},
        ]

    @patch('divoom_lib.wall.Divoom', new_callable=MagicMock)
    @patch('divoom_lib.wall.Image.open')
    async def test_free_form_static_image_crop_and_resize(self, mock_image_open, mock_divoom_class):
        mock_img = MagicMock(spec=Image.Image)
        mock_img.is_animated = False
        mock_img.crop = MagicMock(return_value=mock_img)
        mock_img.resize = MagicMock(return_value=mock_img)
        mock_image_open.return_value = mock_img

        mock_clients = []
        for _ in range(2):
            mc = MagicMock()
            mc.display.show_image = AsyncMock(return_value=True)
            mock_clients.append(mc)
        mock_divoom_class.side_effect = mock_clients

        import tempfile
        with tempfile.TemporaryDirectory() as home_td:
            orig_home = Path.home
            Path.home = staticmethod(lambda: Path(home_td))
            orig_exists = Path.exists
            Path.exists = lambda self_path: "free_form.png" in str(self_path)
            try:
                wall = DivoomWall(self.device_configs)
                ok = await wall.show_image("free_form.png")
                self.assertTrue(ok)
            finally:
                Path.exists = orig_exists
                Path.home = orig_home

        # Free-form path resizes the crop DOWN to the slot's uniform `size`.
        mock_img.resize.assert_any_call((16, 16), Image.NEAREST)
        for mc in mock_clients:
            mc.display.show_image.assert_called_once()

    @patch('divoom_lib.wall.Divoom', new_callable=MagicMock)
    async def test_free_form_animated_image_real_frames(self, mock_divoom_class):
        """Real (non-mocked) 2-frame animated GIF through the free-form path
        exercises the per-frame crop+resize loop and the frames[0].save call.
        Redirects Path.home() to a tmp dir so the split-cache write doesn't
        touch the real ~/.config/divoom-control/cache_wall."""
        import tempfile
        mock_clients = []
        for _ in range(2):
            mc = MagicMock()
            mc.display.show_image = AsyncMock(return_value=True)
            mock_clients.append(mc)
        mock_divoom_class.side_effect = mock_clients

        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as home_td:
            gif_path = str(Path(td) / "anim.gif")
            frame1 = Image.new("RGB", (64, 16), (255, 0, 0))
            frame2 = Image.new("RGB", (64, 16), (0, 255, 0))
            frame1.save(gif_path, save_all=True, append_images=[frame2], duration=100, loop=0)

            orig_home = Path.home
            Path.home = staticmethod(lambda: Path(home_td))
            try:
                wall = DivoomWall(self.device_configs)
                ok = await wall.show_image(gif_path)
                self.assertTrue(ok)
                for mc in mock_clients:
                    mc.display.show_image.assert_called_once()
            finally:
                Path.home = orig_home


class TestWallResolution(unittest.TestCase):
    """R13 §1 — the wall_resolution() helper. It must be derived from
    panel_resolution (per-panel pixels), not the wall canvas size."""

    def test_2x2_wall_of_16px_panels(self):
        """Four Pixoos (16×16) in a 2×2 grid = 32×32 composite."""
        self.assertEqual(wall_resolution(16, 2, 2), (32, 32))

    def test_2x1_wall_of_32px_panels(self):
        """Two Tivoo Maxes (32×32) side-by-side = 64×32 composite."""
        self.assertEqual(wall_resolution(32, 2, 1), (64, 32))

    def test_4x2_wall_of_32px_panels(self):
        """Eight Timoos (32×32) in a 4×2 grid = 128×64 composite."""
        self.assertEqual(wall_resolution(32, 4, 2), (128, 64))

    def test_single_panel_returns_panel_resolution(self):
        """A 1×1 wall is just one panel — the canvas is panel_resolution square."""
        self.assertEqual(wall_resolution(16, 1, 1), (16, 16))
        self.assertEqual(wall_resolution(32, 1, 1), (32, 32))

    def test_64px_panels(self):
        """A Pixoo 64 (64×64) in a 1×1 wall = 64×64; in 2×1 = 128×64."""
        self.assertEqual(wall_resolution(64, 1, 1), (64, 64))
        self.assertEqual(wall_resolution(64, 2, 1), (128, 64))

    def test_invalid_panel_resolution_rejected(self):
        """panel_resolution must be 16, 32, or 64. Other values raise."""
        with self.assertRaises(ValueError):
            wall_resolution(8, 1, 1)
        with self.assertRaises(ValueError):
            wall_resolution(128, 1, 1)
        with self.assertRaises(ValueError):
            wall_resolution(0, 1, 1)

    def test_invalid_grid_rejected(self):
        """Grid must be at least 1×1."""
        with self.assertRaises(ValueError):
            wall_resolution(32, 0, 1)
        with self.assertRaises(ValueError):
            wall_resolution(32, 1, 0)


if __name__ == '__main__':
    unittest.main()
