"""Shared scaffolding for the split ScannerMixin test modules."""
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent.parent))

from divoom_gui.scanner_mixin import ScannerMixin


class _Host(ScannerMixin):
    """Minimal composition root: ScannerMixin + the two collaborator methods
    it expects from sibling mixins (``_client``, ``_get_presets_file``) in the
    real ``DivoomGuiAPI``. Avoids constructing the full GUI API (webview,
    daemon spawn, credential load) just to exercise this mixin."""

    def __init__(self, presets_file: Path):
        self.current_divoom = None
        self.discovered_list = []
        self.wall_slots = {}
        self.wall_instance = None
        self.current_target_mode = "single"
        self._daemon_client = None
        self._presets_file = presets_file

    def _get_presets_file(self) -> Path:
        return self._presets_file

    def _client(self):
        return self._daemon_client


CONFIG_REL = Path(".config") / "divoom-control" / "config.ini"
CACHE_REL = Path(".config") / "divoom-control" / "discovered_devices.json"


@pytest.fixture
def host(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return _Host(tmp_path / "presets.json")


def _write_ini(tmp_path, section_body="[gui]\ntimeout = 5\n"):
    cfg_file = tmp_path / CONFIG_REL
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    cfg_file.write_text(section_body, encoding="utf-8")
    return cfg_file
