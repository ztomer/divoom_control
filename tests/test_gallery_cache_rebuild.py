"""
Regression test for the Monthly Best gallery cache rebuild path.

Bug history (2026-06-05): the gallery_cache.json was overwritten with a
single manual test entry `{"name": "NeonSkull", "file_id": "9999", ...}`
while the on-disk cache_gallery/ directory held 500+ real Divoom
artworks. `_load_cached_gallery()` returned the stale JSON, so the
gallery rendered only NeonSkull instead of the full library.

The fix: when the JSON cache is empty OR contains only manual
file_id="9999" entries, fall back to scanning the on-disk directory
via `get_cached_gallery_files()`.
"""
import json
import shutil
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

import pytest

# Stub the C dylib (not available in the test environment) so that the
# top-level `from divoom_lib import media_decoder` inside
# divoom_gui/gallery_sync.py succeeds without loading the native lib.
if "divoom_lib.media_decoder" not in sys.modules:
    import divoom_lib
    _shim = types.ModuleType("divoom_lib.media_decoder")
    _shim.extract_image_from_magic_43 = lambda b: None
    _shim.extract_gif_from_magic_43 = lambda b: None
    _shim.decode_and_save_preview = lambda *a, **k: None
    sys.modules["divoom_lib.media_decoder"] = _shim
    divoom_lib.media_decoder = _shim


def _import_gallery_sync():
    """Import gui/gallery_sync.py. media_decoder stub is set up at module load."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from divoom_gui.gallery_sync import GallerySyncMixin
    return GallerySyncMixin


def _make_mixin():
    """Instantiate the mixin via a tiny host class so `self` is bound."""
    mixin = _import_gallery_sync()

    class _Host(mixin):
        pass

    return _Host()


def test_load_cached_gallery_rebuilds_from_directory_when_stale(tmp_path, monkeypatch):
    """Stale JSON cache (only file_id=9999) → fall back to directory scan."""
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _make_mixin()

    # Fake cache directory with 3 real items.
    cache_dir = tmp_path / ".config" / "divoom-control" / "cache_gallery"
    cache_dir.mkdir(parents=True)
    for name, ext in [("group1_M00_01_AAA", "gif"),
                      ("group1_M00_02_BBB", "png"),
                      ("group1_M00_03_CCC", "jpg")]:
        (cache_dir / f"{name}.{ext}").write_bytes(b"\x00" * 16)

    # Stale JSON cache with a manual entry.
    cache_file = tmp_path / ".config" / "divoom-control" / "gallery_cache.json"
    cache_file.write_text(json.dumps([
        {"name": "NeonSkull", "file_id": "9999", "likes": 1500, "preview_url": ""}
    ]))

    out = m._load_cached_gallery()

    arr = json.loads(out)
    assert len(arr) == 3, f"expected 3 items rebuilt from directory, got {len(arr)}: {arr}"
    names = {a["name"] for a in arr}
    # The directory-scan uses filename (including extension) as the display name
    # when there's no name_map (Kare: minimal, no fake names).
    assert "group1_M00_01_AAA.gif" in names
    assert "group1_M00_02_BBB.png" in names
    assert "group1_M00_03_CCC.jpg" in names
    # No bogus NeonSkull from the stale cache.
    assert "NeonSkull" not in names
    # No 9999 file_id from the stale cache.
    for a in arr:
        assert a.get("file_id") != "9999", f"stale entry leaked through: {a}"


def test_load_cached_gallery_keeps_real_cache(tmp_path, monkeypatch):
    """Real cache with non-9999 file_ids → return as-is (no rebuild)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _make_mixin()

    real_items = [
        {"name": "RealArt1", "file_id": "group1/M00/01/AAA", "preview_url": "data:,"},
        {"name": "RealArt2", "file_id": "group1/M00/02/BBB", "preview_url": "data:,"},
    ]
    cfg_dir = tmp_path / ".config" / "divoom-control"
    cfg_dir.mkdir(parents=True)
    cache_file = cfg_dir / "gallery_cache.json"
    cache_file.write_text(json.dumps(real_items))

    # Even if the directory has items, the real cache should win.
    cache_dir = cfg_dir / "cache_gallery"
    cache_dir.mkdir(parents=True)
    (cache_dir / "decoy.bin").write_bytes(b"\x00")

    out = m._load_cached_gallery()

    arr = json.loads(out)
    assert arr == real_items, f"real cache should be returned unchanged, got {arr}"


def test_load_cached_gallery_rebuilds_when_empty(tmp_path, monkeypatch):
    """Empty JSON cache `[]` + non-empty directory → rebuild."""
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _make_mixin()

    cache_dir = tmp_path / ".config" / "divoom-control" / "cache_gallery"
    cache_dir.mkdir(parents=True)
    for name in ("artA", "artB"):
        (cache_dir / f"{name}.png").write_bytes(b"\x00" * 8)

    cache_file = tmp_path / ".config" / "divoom-control" / "gallery_cache.json"
    cache_file.write_text("[]")

    out = m._load_cached_gallery()

    arr = json.loads(out)
    assert len(arr) == 2
    # The directory-scan uses the filename as the display name (Kare: minimal).
    assert {a["name"] for a in arr} == {"artA.png", "artB.png"}


def test_load_cached_gallery_returns_empty_when_no_cache_and_no_directory(tmp_path, monkeypatch):
    """No JSON cache, no directory → return `[]` (graceful empty)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _make_mixin()

    out = m._load_cached_gallery()

    assert out == "[]"
