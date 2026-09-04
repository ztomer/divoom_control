"""Export/import dialog + path helpers and preset file dialogs for
presets_manager.py (split from test_presets_manager.py)."""
import json
import sys
from unittest.mock import MagicMock

import pytest

from tests.support.presets_manager_common import (  # noqa: F401
    Host,
    _cfg_dir,
    home,
    presets_manager,
)


# ── export_settings_dialog (lines 257-280, webview mocked) ─────────────────

def test_export_settings_dialog_no_window(home):
    h = Host()
    h.window = None
    assert h.export_settings_dialog() is False


def test_export_settings_dialog_cancelled(home, monkeypatch):
    fake_webview = MagicMock()
    fake_webview.SAVE_DIALOG = "save"
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    h = Host()
    h.window = MagicMock()
    h.window.create_file_dialog.return_value = None
    assert h.export_settings_dialog() is False


def test_export_settings_dialog_success_calls_export_path(home, monkeypatch, tmp_path):
    fake_webview = MagicMock()
    fake_webview.SAVE_DIALOG = "save"
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    target = tmp_path / "out.json"
    h = Host()
    h.window = MagicMock()
    h.window.create_file_dialog.return_value = [str(target)]
    assert h.export_settings_dialog() is True
    assert target.exists()


def test_export_settings_dialog_list_result_empty_string_path(home, monkeypatch):
    """result is a list whose [0] is empty/falsy -> path falsy -> cancelled."""
    fake_webview = MagicMock()
    fake_webview.SAVE_DIALOG = "save"
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    h = Host()
    h.window = MagicMock()
    h.window.create_file_dialog.return_value = [""]
    assert h.export_settings_dialog() is False


def test_export_settings_dialog_exception_returns_false(home, monkeypatch):
    # An entry of None in sys.modules makes `import webview` raise
    # ImportError even though the real package is installed.
    monkeypatch.setitem(sys.modules, "webview", None)
    h = Host()
    h.window = MagicMock()
    assert h.export_settings_dialog() is False


# ── _export_settings_to_path: all optional-file branches (lines 288-330) ───

def test_export_settings_to_path_no_optional_files(home, tmp_path):
    """None of presets/config/alarms/hotchannel/routing exist -> all
    exists()-False arms taken, export still succeeds with an empty dict."""
    h = Host()
    target = tmp_path / "out.json"
    assert h._export_settings_to_path(str(target)) is True
    assert json.loads(target.read_text(encoding="utf-8")) == {}


def test_export_settings_to_path_all_optional_files_present(home, tmp_path):
    tmp_path_home = home
    cfg_dir = _cfg_dir(tmp_path_home)
    (cfg_dir / "presets.json").write_text(json.dumps({"p": 1}), encoding="utf-8")
    (cfg_dir / "config.ini").write_text("[a]\nb = c\n", encoding="utf-8")
    (cfg_dir / "alarms.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
    (cfg_dir / "hotchannel.json").write_text(json.dumps({"h": 1}), encoding="utf-8")
    (cfg_dir / "notification_routing.json").write_text(json.dumps({"r": 1}), encoding="utf-8")

    h = Host()
    target = tmp_path / "out2.json"
    assert h._export_settings_to_path(str(target)) is True
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data == {
        "presets": {"p": 1},
        "config_ini": "[a]\nb = c\n",
        "alarms": {"a": 1},
        "hotchannel": {"h": 1},
        "notification_routing": {"r": 1},
    }


def test_export_settings_to_path_corrupt_optional_files_are_skipped(home, tmp_path):
    """Each corrupt optional json file logs a warning and is omitted, but
    export still succeeds (lines 293-294, 306-307, 314-315, 322-323)."""
    cfg_dir = _cfg_dir(home)
    (cfg_dir / "presets.json").write_text("not json", encoding="utf-8")
    (cfg_dir / "alarms.json").write_text("not json", encoding="utf-8")
    (cfg_dir / "hotchannel.json").write_text("not json", encoding="utf-8")
    (cfg_dir / "notification_routing.json").write_text("not json", encoding="utf-8")

    h = Host()
    target = tmp_path / "out3.json"
    assert h._export_settings_to_path(str(target)) is True
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data == {}


def test_export_settings_to_path_exception_returns_false(home, monkeypatch, tmp_path):
    monkeypatch.setattr(presets_manager, "atomic_write_text",
                         lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fail")))
    h = Host()
    assert h._export_settings_to_path(str(tmp_path / "x.json")) is False


# ── import_settings_dialog (lines 332-355, webview mocked) ─────────────────

def test_import_settings_dialog_no_window(home):
    h = Host()
    h.window = None
    assert h.import_settings_dialog() is False


def test_import_settings_dialog_cancelled(home, monkeypatch):
    fake_webview = MagicMock()
    fake_webview.OPEN_DIALOG = "open"
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    h = Host()
    h.window = MagicMock()
    h.window.create_file_dialog.return_value = None
    assert h.import_settings_dialog() is False


def test_import_settings_dialog_empty_list_result_cancelled(home, monkeypatch):
    """result is a list of length 0 -> path falsy (the len(result) > 0 arm)."""
    fake_webview = MagicMock()
    fake_webview.OPEN_DIALOG = "open"
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    h = Host()
    h.window = MagicMock()
    h.window.create_file_dialog.return_value = []
    assert h.import_settings_dialog() is False


def test_import_settings_dialog_success(home, monkeypatch, tmp_path):
    fake_webview = MagicMock()
    fake_webview.OPEN_DIALOG = "open"
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    backup = tmp_path / "backup.json"
    backup.write_text(json.dumps({"presets": {"a": 1}}), encoding="utf-8")
    h = Host()
    h.window = MagicMock()
    h.window.create_file_dialog.return_value = [str(backup)]
    assert h.import_settings_dialog() is True


def test_import_settings_dialog_exception_returns_false(home, monkeypatch):
    monkeypatch.setitem(sys.modules, "webview", None)
    h = Host()
    h.window = MagicMock()
    assert h.import_settings_dialog() is False


# ── _import_settings_from_path: each optional key branch (lines 364-393) ───

def test_import_settings_from_path_restores_all_keys(home, tmp_path):
    backup = tmp_path / "backup.json"
    backup.write_text(json.dumps({
        "presets": {"p": 1},
        "config_ini": "[a]\nb = c\n",
        "alarms": {"a": 1},
        "hotchannel": {"h": 1},
        "notification_routing": {"r": 1},
    }), encoding="utf-8")

    h = Host()
    assert h._import_settings_from_path(str(backup)) is True

    cfg_dir = _cfg_dir(home)
    assert json.loads((cfg_dir / "presets.json").read_text(encoding="utf-8")) == {"p": 1}
    assert (cfg_dir / "config.ini").read_text(encoding="utf-8") == "[a]\nb = c\n"
    assert json.loads((cfg_dir / "alarms.json").read_text(encoding="utf-8")) == {"a": 1}
    assert json.loads((cfg_dir / "hotchannel.json").read_text(encoding="utf-8")) == {"h": 1}
    assert json.loads((cfg_dir / "notification_routing.json").read_text(encoding="utf-8")) == {"r": 1}


def test_import_settings_from_path_missing_keys_skips_all_writes(home, tmp_path):
    """Empty backup dict -> every `"key" in backup_data` False arm taken;
    import still reports success and touches no config files."""
    backup = tmp_path / "backup.json"
    backup.write_text(json.dumps({}), encoding="utf-8")

    h = Host()
    assert h._import_settings_from_path(str(backup)) is True

    cfg_dir = _cfg_dir(home)
    assert not (cfg_dir / "presets.json").exists()
    assert not (cfg_dir / "config.ini").exists()
    assert not (cfg_dir / "alarms.json").exists()
    assert not (cfg_dir / "hotchannel.json").exists()
    assert not (cfg_dir / "notification_routing.json").exists()


def test_import_settings_from_path_exception_returns_false(home, tmp_path):
    bad = tmp_path / "missing.json"  # never written -> read_text raises
    h = Host()
    assert h._import_settings_from_path(str(bad)) is False

