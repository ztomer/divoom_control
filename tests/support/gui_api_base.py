"""Shared base for the split DivoomGuiAPI test modules (ex test_gui_api.py)."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add paths to imports
sys.path.append(str(Path(__file__).parent.parent.parent))
sys.path.append(str(Path(__file__).parent.parent.parent / "divoom_gui"))

from gui_main import DivoomGuiAPI


class GuiApiTestBase(unittest.TestCase):
    def setUp(self):
        # Prevent actually touching credentials files or presetting configs on disk during unit testing
        self.presets_patcher = patch("pathlib.Path.exists", return_value=False)
        self.presets_patcher.start()

        import tempfile
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home_patcher = patch("pathlib.Path.home", return_value=Path(self.temp_dir.name))
        self.home_patcher.start()

        self.api = DivoomGuiAPI()
        self.api.window = MagicMock()

    def tearDown(self):
        self.presets_patcher.stop()
        self.home_patcher.stop()
        self.temp_dir.cleanup()
