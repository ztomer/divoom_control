"""R52: the hot-channel PREVIEW must show what the UPDATE actually sends.

The danger is the preview resolving a DIFFERENT manifest than the send — e.g.
always the 16px one while a 64px Pixoo gets the 64px one (the ghost-default bug
already fixed once for the community gallery). These tests pin the invariant:
the preview asks at the ACTIVE device size, and identical sizes yield identical
file sets.

**R70 P2.3 made the invariant structural rather than watched.** Both paths now
go through `divoomd`, which owns the size -> DeviceType mapping
(`art::device_type_for_size`) and the manifest cache. The GUI used to call the
Python `fetch_hot_manifest` against the same endpoint with its OWN copy of that
mapping — two clients of one API, kept in step by a test rather than by there
being one of them.

The `TestGetAnimatedPreview` class that used to live here went with the code it
covered: ~90 lines of in-GUI download and decode (magic-43, raw GIF/PNG/JPEG,
cloud containers, a PIL catch-all) replaced by one daemon call whose decoder
handles strictly more. `tests/test_gallery_assets.py` covers what remains.
"""
from __future__ import annotations

import json

from divoom_gui.gallery_hot_api import GalleryHotApiMixin

#: What `art::device_type_for_size` answers. Duplicated here ON PURPOSE: this
#: must fail if the daemon's mapping changes without anyone noticing, which it
#: could not do if it imported the value under test.
DEVICE_TYPE_BY_SIZE = {16: 1, 32: 0, 64: 2, 128: 3, 256: 4}


class _FakeClient:
    """Records the device_size the preview asks for."""

    def __init__(self, items=None, error=None):
        self.items = items if items is not None else [
            {"file_id": "g/abc", "version": 3, "vendor_id": 1, "sha1": "x"}]
        self.error = error
        self.sizes = []

    def hot_manifest(self, device_size=16):
        self.sizes.append(device_size)
        if self.error is not None:
            raise self.error
        return self.items


class _Api(GalleryHotApiMixin):
    """Minimal host for the mixin with a controllable active device size."""

    def __init__(self, size, client=None):
        self._size = size
        self._fake = client if client is not None else _FakeClient()

    def _active_device_size(self, default: int = 16) -> int:
        return self._size

    def _client(self):
        return self._fake


def _patch_manifest(monkeypatch, tmp_path):
    """Keep the gallery-cache lookup out of the real home dir."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return {}


def test_preview_asks_at_the_active_device_size(monkeypatch, tmp_path):
    _patch_manifest(monkeypatch, tmp_path)
    api = _Api(64)
    out = json.loads(api.hot_update_preview())
    assert out["success"] is True
    # A 64px Pixoo must not silently get the 16px manifest.
    assert api._fake.sizes == [64]
    assert [i["file_id"] for i in out["items"]] == ["g/abc"]


def test_preview_size_tracks_the_device_at_every_size(monkeypatch, tmp_path):
    _patch_manifest(monkeypatch, tmp_path)
    for size in (16, 32, 64, 128, 256):
        api = _Api(size)
        api.hot_update_preview()
        assert api._fake.sizes == [size], (
            f"preview at size {size} asked for the wrong manifest")


def test_the_daemon_maps_every_size_this_gui_can_report(monkeypatch, tmp_path):
    """The mapping moved INTO the daemon, so pin that it still covers the sizes
    the GUI can ask about — a size the daemon silently defaults to 16 would
    reproduce the ghost-default bug one layer down."""
    from pathlib import Path as _P
    src = (_P(__file__).resolve().parent.parent
           / "divoomd" / "src" / "art.rs").read_text()
    for size, device_type in DEVICE_TYPE_BY_SIZE.items():
        assert f"{size} => {device_type}," in src, (
            f"art.rs no longer maps {size}px to DeviceType {device_type}")


def test_preview_uses_gallery_cache_names_and_marks_has_cache(monkeypatch, tmp_path):
    """Cache-hit items get their friendly name/likes/preview_url from the
    local gallery cache (lines 87-98) instead of falling back to the raw
    file_id tail."""
    seen = _patch_manifest(monkeypatch, tmp_path)

    cache_dir = tmp_path / ".config" / "divoom-control"
    cache_dir.mkdir(parents=True)
    cache_file = cache_dir / "gallery_cache.json"
    cache_file.write_text(json.dumps([
        {"file_id": "g/abc", "name": "Cool Art", "likes": 42, "preview_url": "http://x/y.gif"},
    ]), encoding="utf-8")

    out = json.loads(_Api(16).hot_update_preview())
    assert out["success"] is True
    item = out["items"][0]
    assert item["name"] == "Cool Art"
    assert item["likes"] == 42
    assert item["preview_url"] == "http://x/y.gif"
    assert item["has_cache"] is True


def test_preview_falls_back_to_file_id_tail_when_uncached(monkeypatch, tmp_path):
    """No gallery cache on disk → name falls back to the file_id tail and
    has_cache is False."""
    _patch_manifest(monkeypatch, tmp_path)
    out = json.loads(_Api(16).hot_update_preview())
    item = out["items"][0]
    assert item["name"] == "abc"  # "g/abc".rsplit("/", 1)[-1]
    assert item["has_cache"] is False


def test_preview_survives_corrupt_gallery_cache(monkeypatch, tmp_path):
    """A malformed gallery_cache.json must not blow up the preview — the
    inner try/except swallows the parse error and falls back to file_id."""
    _patch_manifest(monkeypatch, tmp_path)
    cache_dir = tmp_path / ".config" / "divoom-control"
    cache_dir.mkdir(parents=True)
    (cache_dir / "gallery_cache.json").write_text("{not valid json", encoding="utf-8")

    out = json.loads(_Api(16).hot_update_preview())
    assert out["success"] is True
    assert out["items"][0]["name"] == "abc"
    assert out["items"][0]["has_cache"] is False


def test_preview_reports_manifest_fetch_failure(monkeypatch, tmp_path):
    """A manifest that cannot be fetched is a structured failure carrying the
    daemon's reason, not an exception and not an empty grid."""
    from divoom_client.daemon_cloud import CloudUnavailable

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    api = _Api(16, _FakeClient(error=CloudUnavailable("hot_manifest: timed out", "cloud")))
    out = json.loads(api.hot_update_preview())
    assert out["success"] is False
    assert "timed out" in out["error"]


def test_preview_without_a_daemon_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    class _NoDaemon(_Api):
        def _client(self):
            return None

    out = json.loads(_NoDaemon(16).hot_update_preview())
    assert out["success"] is False
    assert "background service" in out["error"]


def test_preview_and_send_share_one_manifest_source():
    """Both the preview and the send resolve the manifest through the DAEMON.

    This used to pin that two Python call sites referenced the same
    `DEVICE_TYPE_BY_SIZE` map and the same `fetch_hot_manifest`. There is only
    one implementation now, so the guard is that the GUI has no second one:
    the preview asks `hot_manifest`, the send asks `hot_update`, and neither
    imports the Python manifest fetcher.
    """
    import inspect
    from divoom_gui.gallery_hot_api import GalleryHotApiMixin as _M

    preview_src = inspect.getsource(_M.hot_update_preview)
    assert "hot_manifest" in preview_src
    assert "fetch_hot_manifest" not in preview_src, (
        "the preview must not fetch the manifest itself")

    send_src = inspect.getsource(_M.hot_channel_update)
    assert "hot_update" in send_src
    assert "fetch_hot_manifest" not in send_src
