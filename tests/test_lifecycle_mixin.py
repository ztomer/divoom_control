"""Direct unit tests for `divoom_gui/lifecycle_mixin.py` (LifecycleSettingsMixin).

R61 coverage push: this mixin's get/set methods (and `get_app_version`) were
never called directly in the suite — only the underlying
`divoom_lib.lifecycle_config` functions and the fully-mocked bridge in
test_gui_api.py were exercised. These tests instantiate the mixin directly
and patch the delegate functions at their SOURCE module (the mixin does a
fresh local `from divoom_lib.lifecycle_config import X` on every call, so
patching `divoom_lib.lifecycle_config.X` is picked up).
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))

from divoom_gui.lifecycle_mixin import LifecycleSettingsMixin
import divoom_lib.lifecycle_config as lifecycle_config


@pytest.fixture
def mixin():
    return LifecycleSettingsMixin()


# ── keep_daemon_alive get/set ────────────────────────────────────────────────


def test_get_keep_daemon_alive_delegates(mixin, monkeypatch):
    monkeypatch.setattr(lifecycle_config, "get_keep_daemon_alive", lambda: True)
    assert mixin.get_keep_daemon_alive() is True


def test_set_keep_daemon_alive_coerces_to_bool_and_delegates(mixin, monkeypatch):
    seen = {}

    def _fake_set(value):
        seen["value"] = value
        return True

    monkeypatch.setattr(lifecycle_config, "set_keep_daemon_alive", _fake_set)
    # Pass a non-bool truthy value; the mixin must coerce with bool(...).
    assert mixin.set_keep_daemon_alive(1) is True
    assert seen["value"] is True and isinstance(seen["value"], bool)


# ── quit_menubar_on_exit get/set ─────────────────────────────────────────────


def test_get_quit_menubar_on_exit_delegates(mixin, monkeypatch):
    monkeypatch.setattr(lifecycle_config, "get_quit_menubar_on_exit", lambda: False)
    assert mixin.get_quit_menubar_on_exit() is False


def test_set_quit_menubar_on_exit_coerces_to_bool_and_delegates(mixin, monkeypatch):
    seen = {}

    def _fake_set(value):
        seen["value"] = value
        return True

    monkeypatch.setattr(lifecycle_config, "set_quit_menubar_on_exit", _fake_set)
    assert mixin.set_quit_menubar_on_exit(0) is True
    assert seen["value"] is False and isinstance(seen["value"], bool)


# ── get_app_version ──────────────────────────────────────────────────────────


def test_get_app_version_reads_real_pyproject_toml(mixin):
    """Happy path (dev tree): reads pyproject.toml directly — verified
    against an independent tomllib read of the same file (not a hardcoded
    version string, so this doesn't rot on the next version bump)."""
    repo_root = Path(__file__).resolve().parent.parent
    with (repo_root / "pyproject.toml").open("rb") as f:
        expected = str(tomllib.load(f)["project"]["version"])
    assert mixin.get_app_version() == expected


def test_get_app_version_falls_back_to_meipass_plist_when_no_pyproject(mixin, monkeypatch, tmp_path):
    """Packaged .app path: no pyproject.toml on disk (PyInstaller bundle),
    but sys._MEIPASS is set and Contents/Info.plist has the bundle version."""
    import plistlib

    real_is_file = Path.is_file

    def fake_is_file(self):
        if self.name == "pyproject.toml":
            return False
        return real_is_file(self)

    monkeypatch.setattr(Path, "is_file", fake_is_file)

    contents_dir = tmp_path / "Contents"
    (contents_dir / "Frameworks").mkdir(parents=True)
    with (contents_dir / "Info.plist").open("wb") as f:
        plistlib.dump({"CFBundleShortVersionString": "9.9.9"}, f)

    monkeypatch.setattr(sys, "_MEIPASS", str(contents_dir / "Frameworks"), raising=False)
    assert mixin.get_app_version() == "9.9.9"


def test_get_app_version_returns_unknown_when_nothing_available(mixin, monkeypatch):
    """No pyproject.toml AND no _MEIPASS (not a packaged bundle either) →
    the honest "?" placeholder, never a crash."""
    real_is_file = Path.is_file

    def fake_is_file(self):
        if self.name == "pyproject.toml":
            return False
        return real_is_file(self)

    monkeypatch.setattr(Path, "is_file", fake_is_file)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert mixin.get_app_version() == "?"


def test_get_app_version_tolerates_corrupt_pyproject(mixin, monkeypatch):
    """L47-48: an exception while parsing pyproject.toml (corrupt TOML, odd
    permissions, ...) is swallowed — falls through to the next strategy,
    not raised to the pywebview JS-API thread."""
    import tomllib as real_tomllib

    def _boom(f):
        raise real_tomllib.TOMLDecodeError("bad toml", "", 0)

    monkeypatch.setattr(real_tomllib, "load", _boom)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert mixin.get_app_version() == "?"


def test_get_app_version_meipass_set_but_no_plist_file(mixin, monkeypatch, tmp_path):
    """L56->61 branch: sys._MEIPASS is set (looks like a bundle) but
    Info.plist isn't actually there (odd/partial bundle) — falls through
    to "?" rather than raising."""
    real_is_file = Path.is_file

    def fake_is_file(self):
        if self.name == "pyproject.toml":
            return False
        return real_is_file(self)

    monkeypatch.setattr(Path, "is_file", fake_is_file)
    frameworks_dir = tmp_path / "Contents" / "Frameworks"
    frameworks_dir.mkdir(parents=True)
    # No Info.plist written at tmp_path / "Contents" / "Info.plist".
    monkeypatch.setattr(sys, "_MEIPASS", str(frameworks_dir), raising=False)
    assert mixin.get_app_version() == "?"


def test_get_app_version_tolerates_corrupt_plist(mixin, monkeypatch, tmp_path):
    """L59-60: an exception while parsing Info.plist (corrupt bundle) is
    swallowed too, falling through to "?"."""
    real_is_file = Path.is_file

    def fake_is_file(self):
        if self.name == "pyproject.toml":
            return False
        return real_is_file(self)

    monkeypatch.setattr(Path, "is_file", fake_is_file)

    contents_dir = tmp_path / "Contents"
    (contents_dir / "Frameworks").mkdir(parents=True)
    (contents_dir / "Info.plist").write_bytes(b"not a plist")
    monkeypatch.setattr(sys, "_MEIPASS", str(contents_dir / "Frameworks"), raising=False)
    assert mixin.get_app_version() == "?"
