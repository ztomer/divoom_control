"""gallery_sync coverage: single-pass recovery of corrupt/stale .bin cache
entries in fetch_gallery_asset (split from
test_gallery_sync_coverage.py)."""
import json
import logging
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.support.gallery_sync_common import (  # noqa: F401
    _Host,
    _wait_for_fetch_thread,
)


# ─────────── single-pass recovery of corrupt/stale .bin cache ───────────

def test_fetch_gallery_asset_recovers_corrupt_bin_in_one_pass(tmp_path, monkeypatch):
    """A corrupt/truncated cached .bin must be dropped and re-downloaded +
    decoded in a single call — NOT left for a second fetch. Regression guard
    for the "gallery items have names but render as black placeholders" bug:
    an empty preview_url (from a .bin that failed to decode) is what the
    frontend shows as a black tile."""
    import divoom_gui.gallery_sync as gs_mod
    cache_dir = tmp_path / "cache_gallery"
    cache_dir.mkdir()
    file_id = "group1/M00/00/AA/corrupt_test_asset"
    safe = file_id.replace("/", "_")

    # Seed a corrupt .bin (as a prior failed download would leave behind).
    (cache_dir / f"{safe}.bin").write_bytes(b"\x00\x01TRUNCATED-GARBAGE")

    # The CDN download returns a real, decodable GIF.
    good_gif = b"GIF89a" + b"\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00;"
    with patch.object(urllib.request, "urlopen") as mock_urlopen:
        class _Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return good_gif
        mock_urlopen.return_value = _Resp()

        ok = gs_mod.GallerySyncMixin._fetch_gallery_asset(cache_dir, file_id)

    assert ok is True
    # The decoded preview now exists on disk...
    assert (cache_dir / f"{safe}.gif").exists()
    # ...and the corrupt .bin was replaced (re-downloaded), not left as-is.
    assert (cache_dir / f"{safe}.bin").read_bytes() == good_gif


def test_fetch_gallery_asset_skips_when_preview_already_decoded(tmp_path, monkeypatch):
    """If a decoded, non-blank preview already exists, no network call
    is made (R64: preview_valid must accept a real preview, not drop it)."""
    import divoom_gui.gallery_sync as gs_mod
    cache_dir = tmp_path / "cache_gallery"
    cache_dir.mkdir()
    file_id = "group1/M00/00/BB/already_decoded"
    safe = file_id.replace("/", "_")
    (cache_dir / f"{safe}.png").write_bytes(b"\x89PNG\r\n\x1a\nFAKE")

    with patch("divoom_gui.gallery_download.media_decoder.is_black_image",
               return_value=False), \
         patch.object(urllib.request, "urlopen") as mock_urlopen:
        ok = gs_mod.GallerySyncMixin._fetch_gallery_asset(cache_dir, file_id)
    mock_urlopen.assert_not_called()
    assert ok is True


def test_fetch_gallery_asset_drops_black_preview_and_redownloads(tmp_path, monkeypatch):
    """R64 — a stale all-black (or unreadable) preview must be dropped and
    re-decoded in the same call, not rendered as a permanent black tile.
    Regression for 'most images don't render' where a pre-fix build left
    blank previews on disk that were reused forever."""
    import divoom_gui.gallery_sync as gs_mod
    cache_dir = tmp_path / "cache_gallery"
    cache_dir.mkdir()
    file_id = "group1/M00/00/DD/black_preview"
    safe = file_id.replace("/", "_")
    (cache_dir / f"{safe}.png").write_bytes(b"\x01\x02\x03")  # treated as blank

    good_gif = b"GIF89a" + b"\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00;"
    with patch("divoom_gui.gallery_download.media_decoder.is_black_image",
               return_value=True), \
         patch.object(urllib.request, "urlopen") as mock_urlopen:
        class _Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return good_gif
        mock_urlopen.return_value = _Resp()

        ok = gs_mod.GallerySyncMixin._fetch_gallery_asset(cache_dir, file_id)

    assert ok is True
    # The blank .png was dropped (not reused)...
    assert not (cache_dir / f"{safe}.png").exists()
    # ...and a real, decodable preview now exists.
    assert (cache_dir / f"{safe}.gif").exists()


def test_fetch_gallery_asset_drops_unreadable_preview(tmp_path, monkeypatch):
    """R64 — an unreadable/corrupt preview file is treated as broken and
    dropped + re-decoded (is_black_image returns True on open failure)."""
    import divoom_gui.gallery_sync as gs_mod
    cache_dir = tmp_path / "cache_gallery"
    cache_dir.mkdir()
    file_id = "group1/M00/00/EE/unreadable"
    safe = file_id.replace("/", "_")
    (cache_dir / f"{safe}.png").write_bytes(b"\x89PNG\r\n\x1a\nGARBAGE")

    good_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    with patch("divoom_gui.gallery_download.media_decoder.is_black_image",
               return_value=True), \
         patch.object(urllib.request, "urlopen") as mock_urlopen:
        class _Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return good_png
        mock_urlopen.return_value = _Resp()

        ok = gs_mod.GallerySyncMixin._fetch_gallery_asset(cache_dir, file_id)

    assert ok is True
    # The corrupt .png was dropped and re-decoded into a fresh, valid one.
    assert (cache_dir / f"{safe}.png").read_bytes() == good_png


def test_fetch_gallery_asset_handles_download_failure(tmp_path, monkeypatch):
    """A failed download must not raise and must report no preview."""
    import divoom_gui.gallery_sync as gs_mod
    cache_dir = tmp_path / "cache_gallery"
    cache_dir.mkdir()
    file_id = "group1/M00/00/CC/unreachable"
    safe = file_id.replace("/", "_")
    (cache_dir / f"{safe}.bin").write_bytes(b"stale")

    with patch.object(urllib.request, "urlopen", side_effect=OSError("offline")):
        ok = gs_mod.GallerySyncMixin._fetch_gallery_asset(cache_dir, file_id)
    assert ok is False
    # stale .bin was dropped so the next fetch retries cleanly
    assert not (cache_dir / f"{safe}.bin").exists()
