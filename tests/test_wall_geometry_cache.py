"""Coverage for DivoomWall.__init__'s two under-tested branches:

1. The free-form layout path (configs carry "width"/"height" instead of a
   uniform grid "size") — total_width/height and min_x/min_y are derived
   from absolute bounding boxes, not grid_cols * grid_unit_size.
2. The geometry-change cache: __init__ hashes device_configs, compares
   against ~/.config/divoom-control/cache_wall/last_geometry.txt, and
   purges the cache dir when the hash differs (or the file is unreadable),
   swallowing unlink/write errors so a broken cache dir never blocks
   wall construction.

All tests redirect Path.home() to a pytest tmp_path so nothing touches the
real user cache directory.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).parent.parent))

from divoom_lib import wall as wall_mod
from divoom_lib.wall import DivoomWall


def _cache_dir(home: Path) -> Path:
    return home / ".config" / "divoom-control" / "cache_wall"


@patch("divoom_lib.wall.Divoom", new_callable=MagicMock)
def test_free_form_layout_computes_absolute_bounding_box(mock_divoom, tmp_path, monkeypatch):
    """Configs with "width"/"height" take the free-form path: total size and
    min_x/min_y come from the absolute (x, y, width, height) boxes, and each
    DeviceSlot carries its own width/height (not just a uniform grid size)."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    configs = [
        {"mac": "AA:01", "x": 10, "y": 20, "width": 32, "height": 16, "size": 16},
        {"mac": "AA:02", "x": 42, "y": 20, "width": 64, "height": 64, "size": 16},
    ]
    w = DivoomWall(configs)
    assert w.is_free_form is True
    assert w.min_x == 10 and w.min_y == 20
    # max_x = max(10+32, 42+64) = 106; max_y = max(20+16, 20+64) = 84
    assert w.total_width == 106 - 10
    assert w.total_height == 84 - 20
    assert len(w.devices) == 2
    slot0 = w.devices[0]
    assert slot0.x == 10 and slot0.y == 20 and slot0.width == 32 and slot0.height == 16


@patch("divoom_lib.wall.Divoom", new_callable=MagicMock)
def test_free_form_layout_defaults_when_width_height_missing_on_other_slots(
    mock_divoom, tmp_path, monkeypatch
):
    """Only ONE config needs "width" to trigger is_free_form; a sibling config
    without width/height must still get the (120, 120) defaults, not KeyError."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    configs = [
        {"mac": "AA:01", "x": 0, "y": 0, "width": 32, "height": 32},
        {"mac": "AA:02", "x": 0, "y": 0},  # no width/height/size at all
    ]
    w = DivoomWall(configs)
    assert w.is_free_form is True
    slot1 = w.devices[1]
    assert slot1.width == 120 and slot1.height == 120 and slot1.size == 16


@patch("divoom_lib.wall.Divoom", new_callable=MagicMock)
def test_geometry_first_run_purges_and_writes_hash(mock_divoom, tmp_path, monkeypatch):
    """No last_geometry.txt yet -> geometry_changed=True -> stale cache files
    are purged and the new hash is written."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cache_dir = _cache_dir(tmp_path)
    cache_dir.mkdir(parents=True)
    stale = cache_dir / "stale_split.png"
    stale.write_bytes(b"junk")

    configs = [{"mac": "AA:01", "x": 0, "y": 0, "size": 16}]
    DivoomWall(configs)

    assert not stale.exists()                       # purged
    geom_file = cache_dir / "last_geometry.txt"
    assert geom_file.exists() and geom_file.read_text().strip()  # hash written


@patch("divoom_lib.wall.Divoom", new_callable=MagicMock)
def test_geometry_unchanged_skips_purge(mock_divoom, tmp_path, monkeypatch):
    """Constructing the SAME wall twice: the second run's hash matches the
    first's, so geometry_changed is False and the cache survives untouched."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    configs = [{"mac": "AA:01", "x": 0, "y": 0, "size": 16}]
    DivoomWall(configs)

    cache_dir = _cache_dir(tmp_path)
    survivor = cache_dir / "keep_me.png"
    survivor.write_bytes(b"keep")

    DivoomWall(configs)  # same config -> same hash -> no purge this time
    assert survivor.exists()


@patch("divoom_lib.wall.Divoom", new_callable=MagicMock)
def test_geometry_changed_when_hash_differs(mock_divoom, tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    DivoomWall([{"mac": "AA:01", "x": 0, "y": 0, "size": 16}])

    cache_dir = _cache_dir(tmp_path)
    survivor = cache_dir / "old_split.png"
    survivor.write_bytes(b"old")

    # Different config (different mac) -> different hash -> purge triggers.
    DivoomWall([{"mac": "BB:02", "x": 0, "y": 0, "size": 16}])
    assert not survivor.exists()


@patch("divoom_lib.wall.Divoom", new_callable=MagicMock)
def test_unreadable_geometry_file_treated_as_changed(mock_divoom, tmp_path, monkeypatch):
    """If last_geometry.txt exists but read_text() raises (corrupted / a
    directory in its place), the except branch still forces a purge instead
    of crashing __init__."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cache_dir = _cache_dir(tmp_path)
    cache_dir.mkdir(parents=True)
    geom_file = cache_dir / "last_geometry.txt"
    geom_file.mkdir()  # a directory in place of the expected file -> read_text() raises

    survivor = cache_dir / "split.png"
    survivor.write_bytes(b"x")

    # Must not raise despite the unreadable geometry marker.
    DivoomWall([{"mac": "AA:01", "x": 0, "y": 0, "size": 16}])
    assert not survivor.exists()


@patch("divoom_lib.wall.Divoom", new_callable=MagicMock)
def test_unlink_failure_during_purge_is_swallowed(mock_divoom, tmp_path, monkeypatch):
    """A file that can't be deleted (permissions, race) must not blow up wall
    construction — the purge loop wraps unlink() in try/except."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cache_dir = _cache_dir(tmp_path)
    cache_dir.mkdir(parents=True)
    stubborn = cache_dir / "stubborn.png"
    stubborn.write_bytes(b"x")

    orig_unlink = Path.unlink

    def _boom(self, *a, **k):
        if self.name == "stubborn.png":
            raise OSError("permission denied")
        return orig_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", _boom)
    DivoomWall([{"mac": "AA:01", "x": 0, "y": 0, "size": 16}])  # must not raise
    assert stubborn.exists()  # the failing unlink left it in place


@patch("divoom_lib.wall.Divoom", new_callable=MagicMock)
def test_write_text_failure_is_swallowed(mock_divoom, tmp_path, monkeypatch):
    """A read-only cache dir (write_text raises) must not block construction."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    orig_write_text = Path.write_text

    def _boom(self, *a, **k):
        if self.name == "last_geometry.txt":
            raise OSError("read-only filesystem")
        return orig_write_text(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", _boom)
    DivoomWall([{"mac": "AA:01", "x": 0, "y": 0, "size": 16}])  # must not raise
