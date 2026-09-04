"""Gallery previews: cached here, fetched and DECODED by the daemon.

R70 P2.2. Replaces `test_gallery_sync_asset_recovery.py`, which tested
`gallery_download.fetch_gallery_asset` — the GUI's own CDN download plus
`media_decoder`. That module is deleted, and so is the corruption-recovery pass
R64 added for it: `is_black_image` existed to repair previews the GUI decoder
produced, and a workaround for a deleted decoder is not worth carrying.

What replaced it is smaller AND decodes more. `media::resolve_to_gif` in the
daemon handles magic 9 (AES), 18/26 (AES + LZO, tiled) and 0xAA hot files on
top of magic-43 and raw GIF/PNG/JPEG — the container formats the GUI's decoder
fell through on, which is why some gallery tiles were always blank.

The cache here holds the daemon's ANSWERS. Nothing in this module sniffs a
magic byte or decides how to decode; the mime comes from the daemon's own
data-url, and an unknown one is not guessed at.
"""
from __future__ import annotations

import base64
import logging

import pytest

from divoom_gui import gallery_assets
from divoom_client.daemon_cloud import CloudUnavailable

GIF = "data:image/gif;base64," + base64.b64encode(b"GIF89a-fake").decode()
PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()


class FakeClient:
    def __init__(self, previews=None, errors=None):
        self.previews = previews or {}
        self.errors = errors or {}
        self.calls: list[str] = []

    def get_animated_preview(self, file_id):
        self.calls.append(file_id)
        if file_id in self.errors:
            raise self.errors[file_id]
        return self.previews.get(file_id, "")


def test_a_miss_asks_the_daemon_and_caches_the_answer(tmp_path):
    cache = gallery_assets.ensure_cache_dir(tmp_path / "cache")
    client = FakeClient({"group1/x": GIF})

    assert gallery_assets.preview_for(client, cache, "group1/x") == GIF
    assert client.calls == ["group1/x"]
    assert (cache / "group1_x.gif").read_bytes() == b"GIF89a-fake"


def test_a_hit_does_not_ask_the_daemon_again(tmp_path):
    """The reason the cache exists: each miss is a round trip, and a 30-item
    gallery served entirely from misses is a visibly slow panel."""
    cache = gallery_assets.ensure_cache_dir(tmp_path / "cache")
    client = FakeClient({"group1/x": GIF})
    gallery_assets.preview_for(client, cache, "group1/x")
    client.calls.clear()

    assert gallery_assets.preview_for(client, cache, "group1/x") == GIF
    assert client.calls == [], "a cached preview must not re-hit the daemon"


def test_the_extension_names_the_mime_on_the_way_back_out(tmp_path):
    cache = gallery_assets.ensure_cache_dir(tmp_path / "cache")
    client = FakeClient({"a/b": PNG})
    gallery_assets.preview_for(client, cache, "a/b")
    assert gallery_assets.cached_preview(cache, "a/b").startswith("data:image/png;base64,")


def test_an_undecodable_asset_yields_an_empty_preview_not_an_exception(tmp_path, caplog):
    """One bad asset must not empty the whole gallery — that is a different
    failure from the cloud being unreachable, and the caller reports that one."""
    cache = gallery_assets.ensure_cache_dir(tmp_path / "cache")
    client = FakeClient(errors={"bad": CloudUnavailable("unrecognized container", "cloud")})
    with caplog.at_level(logging.WARNING):
        assert gallery_assets.preview_for(client, cache, "bad") == ""
    assert "unrecognized container" in caplog.text


def test_an_empty_file_id_never_reaches_the_daemon(tmp_path):
    cache = gallery_assets.ensure_cache_dir(tmp_path / "cache")
    client = FakeClient()
    assert gallery_assets.preview_for(client, cache, "") == ""
    assert client.calls == []


def test_an_unknown_mime_is_served_but_not_persisted(tmp_path, caplog):
    """A type we cannot name is not a type we should write under a guessed
    extension — `cached_preview` would then have to sniff to read it back."""
    cache = gallery_assets.ensure_cache_dir(tmp_path / "cache")
    weird = "data:image/webp;base64," + base64.b64encode(b"RIFF").decode()
    client = FakeClient({"w": weird})
    with caplog.at_level(logging.INFO):
        assert gallery_assets.preview_for(client, cache, "w") == weird
    assert list(cache.glob("w.*")) == []


def test_a_malformed_data_url_is_warned_not_raised(tmp_path, caplog):
    cache = gallery_assets.ensure_cache_dir(tmp_path / "cache")
    client = FakeClient({"m": "not-a-data-url"})
    with caplog.at_level(logging.WARNING):
        assert gallery_assets.preview_for(client, cache, "m") == "not-a-data-url"
    assert "malformed data url" in caplog.text


def test_a_zero_byte_cached_file_is_treated_as_a_miss(tmp_path):
    """The remaining corruption case worth handling without a decoder: a
    truncated write leaves an empty file, and serving it is a black tile."""
    cache = gallery_assets.ensure_cache_dir(tmp_path / "cache")
    (cache / "a_b.gif").write_bytes(b"")
    client = FakeClient({"a/b": GIF})
    assert gallery_assets.preview_for(client, cache, "a/b") == GIF
    assert client.calls == ["a/b"]


# ── the one-time purge ───────────────────────────────────────────────────────

def test_a_pre_r70_cache_is_cleared_exactly_once(tmp_path, caplog):
    """Old caches hold `.bin` intermediates and previews the deleted GUI
    decoder produced, including the blank ones R64 worked around. They are
    dropped once; the next gallery open re-fetches from the daemon."""
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "legacy.bin").write_bytes(b"old")
    (cache / "legacy.png").write_bytes(b"stale")

    with caplog.at_level(logging.INFO):
        gallery_assets.ensure_cache_dir(cache)
    assert not (cache / "legacy.bin").exists()
    assert not (cache / "legacy.png").exists()
    assert (cache / gallery_assets.CACHE_STAMP).exists()
    assert "old in-GUI decoder" in caplog.text


def test_the_purge_does_not_run_a_second_time(tmp_path):
    cache = gallery_assets.ensure_cache_dir(tmp_path / "cache")
    (cache / "fresh.gif").write_bytes(b"GIF89a")
    gallery_assets.ensure_cache_dir(cache)
    assert (cache / "fresh.gif").exists(), "a stamped cache must survive"


def test_the_purge_creates_a_missing_directory(tmp_path):
    cache = gallery_assets.ensure_cache_dir(tmp_path / "nested" / "cache")
    assert cache.is_dir()
    assert (cache / gallery_assets.CACHE_STAMP).exists()
