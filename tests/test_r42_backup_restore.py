"""Tests for R42: Settings backup/restore, presets file saving/loading, and wall split caching."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
import pytest

sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / "divoom_gui"))

def test_settings_export_import_roundtrip(tmp_path, monkeypatch):
    from divoom_gui.presets_manager import PresetsManagerMixin

    # Set up mock home config dir
    cfg_dir = tmp_path / ".config" / "divoom-control"
    cfg_dir.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    # 1. Create fake config files
    (cfg_dir / "presets.json").write_text(json.dumps({"my_preset": {"slots": []}}), encoding="utf-8")
    (cfg_dir / "config.ini").write_text("[test_section]\nkey = value", encoding="utf-8")
    (cfg_dir / "alarms.json").write_text(json.dumps([{"alarm": 1}]), encoding="utf-8")
    (cfg_dir / "hotchannel.json").write_text(json.dumps({"hot": "channel"}), encoding="utf-8")
    (cfg_dir / "notification_routing.json").write_text(json.dumps({"routing": []}), encoding="utf-8")

    class Host(PresetsManagerMixin):
        pass

    h = Host()
    backup_file = tmp_path / "backup.json"

    # Export
    res_export = h._export_settings_to_path(str(backup_file))
    assert res_export is True
    assert backup_file.exists()

    # Load and verify backup file contents
    backup_data = json.loads(backup_file.read_text(encoding="utf-8"))
    assert backup_data["presets"] == {"my_preset": {"slots": []}}
    assert backup_data["config_ini"] == "[test_section]\nkey = value"
    assert backup_data["alarms"] == [{"alarm": 1}]
    assert backup_data["hotchannel"] == {"hot": "channel"}
    assert backup_data["notification_routing"] == {"routing": []}

    # Clean target files and test import
    (cfg_dir / "presets.json").unlink()
    (cfg_dir / "config.ini").unlink()
    (cfg_dir / "alarms.json").unlink()
    (cfg_dir / "hotchannel.json").unlink()
    (cfg_dir / "notification_routing.json").unlink()

    res_import = h._import_settings_from_path(str(backup_file))
    assert res_import is True
    assert (cfg_dir / "presets.json").exists()
    assert (cfg_dir / "config.ini").exists()
    assert (cfg_dir / "alarms.json").exists()
    assert (cfg_dir / "hotchannel.json").exists()
    assert (cfg_dir / "notification_routing.json").exists()

    # Verify import content
    assert json.loads((cfg_dir / "presets.json").read_text(encoding="utf-8")) == {"my_preset": {"slots": []}}
    assert (cfg_dir / "config.ini").read_text(encoding="utf-8") == "[test_section]\nkey = value"


@pytest.mark.asyncio
async def test_wall_split_cache(tmp_path, monkeypatch):
    from divoom_lib.wall import DivoomWall

    # Mock home for ~/.config/divoom-control/cache_wall/
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    # Create mock device configs
    device_configs = [
        {"mac": "AA:BB:CC:DD:EE:FF", "x": 0, "y": 0, "size": 16}
    ]

    # Patch Divoom class
    mock_divoom = MagicMock()
    mock_divoom.mac = "AA:BB:CC:DD:EE:FF"
    mock_divoom.display.show_image = AsyncMock(return_value=True)

    with patch('divoom_lib.wall.Divoom', return_value=mock_divoom):
        wall = DivoomWall(device_configs)

        # Create a small dummy image file
        from PIL import Image
        img_path = tmp_path / "test_image.png"
        img = Image.new("RGB", (16, 16), color="red")
        img.save(img_path)

        ok = await wall.show_image(str(img_path))
        assert ok is True

    # Verify that the cropped quadrant was saved in the cache
    cache_dir = tmp_path / ".config" / "divoom-control" / "cache_wall"
    assert cache_dir.exists()

    # There should be exactly one png file in the cache directory
    cached_files = list(cache_dir.glob("*.png"))
    assert len(cached_files) == 1
    assert cached_files[0].name.endswith("AA_BB_CC_DD_EE_FF.png")
