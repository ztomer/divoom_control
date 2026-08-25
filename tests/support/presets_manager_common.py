"""Shared scaffolding for the split presets_manager test modules."""
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent.parent))
sys.path.append(str(Path(__file__).parent.parent.parent / "divoom_gui"))

from divoom_gui import presets_manager
from divoom_gui.presets_manager import PresetsManagerMixin


class Host(PresetsManagerMixin):
    def __init__(self, cached_creds=None):
        self.cached_creds = cached_creds


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Point Path.home() at tmp_path and redirect the migration source
    (Path(__file__).parent) to a fake, empty dir under tmp_path so the real
    divoom_gui/presets.json in the repo is never touched."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    fake_gui_dir = tmp_path / "fake_gui_module_dir"
    fake_gui_dir.mkdir()
    monkeypatch.setattr(presets_manager, "__file__", str(fake_gui_dir / "presets_manager.py"))
    return tmp_path


def _cfg_dir(tmp_path):
    d = tmp_path / ".config" / "divoom-control"
    d.mkdir(parents=True, exist_ok=True)
    return d
