"""gallery_sync coverage: cached-gallery readers and the fetch_gallery
worker (split from test_gallery_sync_coverage.py)."""
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


# ─────────────────────────── load_cached_gallery ───────────────────────────

def test_load_cached_gallery_malformed_json_returns_empty(tmp_path, monkeypatch):
    """Corrupt JSON on disk must not raise — caught, warned, empty list."""
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()

    cfg_dir = tmp_path / ".config" / "divoom-control"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "gallery_cache.json").write_text("{not valid json[")

    out = m.load_cached_gallery()
    assert out == "[]"


# ───────────────────────── get_cached_gallery_files ─────────────────────────

def test_get_cached_gallery_files_no_dir_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()
    assert m.get_cached_gallery_files() == "[]"


def test_get_cached_gallery_files_malformed_name_map_warns_and_continues(tmp_path, monkeypatch):
    """gallery_cache.json exists but isn't valid JSON -> name-map build fails,
    but the directory scan still proceeds using filenames as display names."""
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()

    cfg_dir = tmp_path / ".config" / "divoom-control"
    cache_dir = cfg_dir / "cache_gallery"
    cache_dir.mkdir(parents=True)
    (cache_dir / "art1.png").write_bytes(b"\x00" * 4)
    (cfg_dir / "gallery_cache.json").write_text("not json at all {{{")

    out = json.loads(m.get_cached_gallery_files())
    assert len(out) == 1
    assert out[0]["name"] == "art1.png"


def test_get_cached_gallery_files_skips_zero_size_and_missing_fid_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()

    cfg_dir = tmp_path / ".config" / "divoom-control"
    cache_dir = cfg_dir / "cache_gallery"
    cache_dir.mkdir(parents=True)
    (cache_dir / "empty.png").write_bytes(b"")  # zero-size -> skipped
    (cache_dir / "real.png").write_bytes(b"\x01\x02")

    # First entry has no file_id (falsy) -> exercises the name_map loop's
    # "if fid" false arm without raising.
    cache_items = [
        {"name": "NoId"},
        {"file_id": "real", "name": "RealName"},
    ]
    (cfg_dir / "gallery_cache.json").write_text(json.dumps(cache_items))

    out = json.loads(m.get_cached_gallery_files())
    names = {item["name"] for item in out}
    assert names == {"RealName"}


def test_get_cached_gallery_files_prioritizes_gif_over_other_ext_both_orders(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()
    cache_dir = tmp_path / ".config" / "divoom-control" / "cache_gallery"
    cache_dir.mkdir(parents=True)

    (cache_dir / "a.png").write_bytes(b"\x01")
    (cache_dir / "a.gif").write_bytes(b"\x02")
    (cache_dir / "b.gif").write_bytes(b"\x03")
    (cache_dir / "b.png").write_bytes(b"\x04")

    out = json.loads(m.get_cached_gallery_files())
    paths = [item["path"] for item in out]
    assert any(p.endswith("a.gif") for p in paths)
    assert not any(p.endswith("a.png") for p in paths)
    assert any(p.endswith("b.gif") for p in paths)
    assert not any(p.endswith("b.png") for p in paths)


def test_get_cached_gallery_files_encode_failure_is_warned_not_raised(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()
    cache_dir = tmp_path / ".config" / "divoom-control" / "cache_gallery"
    cache_dir.mkdir(parents=True)
    (cache_dir / "bad.png").write_bytes(b"\x01\x02")

    with patch.object(Path, "read_bytes", side_effect=OSError("disk gone")):
        out = json.loads(m.get_cached_gallery_files())
    assert out == []  # the one file failed to encode -> excluded, no crash


# ────────────────────────────── fetch_gallery ───────────────────────────────

def _fake_urlopen_factory(*, rc=0, return_message="", file_list=None, dl_bytes_map=None,
                           dl_raises_for=None, list_raises_first_n=0, captured_bodies=None):
    """Build a urlopen side_effect answering both the auth/list POST to
    appin.divoom-gz.com and the per-item GET to fin.divoom-gz.com.

    `list_raises_first_n` lets a test simulate N transient failures on the
    list endpoint before it starts succeeding (retry-path coverage).
    """
    file_list = file_list if file_list is not None else []
    dl_bytes_map = dl_bytes_map or {}
    dl_raises_for = dl_raises_for or set()
    state = {"list_calls": 0}

    def _urlopen(req, timeout=10):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        cm = MagicMock()
        if "GetCategoryFileListV2" in url:
            if captured_bodies is not None:
                captured_bodies.append(json.loads(req.data.decode("utf-8")))
            state["list_calls"] += 1
            if state["list_calls"] <= list_raises_first_n:
                raise RuntimeError("transient network blip")
            body = json.dumps({
                "ReturnCode": rc,
                "ReturnMessage": return_message,
                "FileList": file_list,
            }).encode("utf-8")
            cm.__enter__.return_value.read.return_value = body
        else:
            file_id = url.rsplit("/", 1)[-1]
            if file_id in dl_raises_for:
                raise RuntimeError(f"download failed for {file_id}")
            cm.__enter__.return_value.read.return_value = dl_bytes_map.get(file_id, b"\x00\x00")
        return cm

    return _urlopen


def test_fetch_gallery_success_full_pipeline(tmp_path, monkeypatch):
    """Happy path: cached creds present, one item needs full download+decode
    (magic-43 extraction), one already has a cached preview (skips download
    and decode), one has no FileId at all. Window is present so progressive
    streaming + the final broadcast both fire, and the JSON cache persists."""
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()
    m.window = MagicMock()
    m.cached_creds = MagicMock(token="tok", user_id=42)
    m.device_pw = "secretpw"  # exercise the DevicePassword-in-body branch

    cache_dir = tmp_path / ".config" / "divoom-control" / "cache_gallery"
    cache_dir.mkdir(parents=True)
    (cache_dir / "already_cached.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    file_list = [
        {"FileId": "needs_download", "FileName": "New", "LikeCnt": 3, "FileType": 5},
        {"FileId": "already_cached", "FileName": "Old", "LikeCnt": 1, "FileType": 5},
        {"FileName": "NoFileId"},  # no FileId -> download_item early-returns
    ]
    captured_bodies = []
    urlopen_fn = _fake_urlopen_factory(
        rc=0, file_list=file_list,
        dl_bytes_map={"needs_download": b"rawbytes"},
        captured_bodies=captured_bodies,
    )

    with patch("urllib.request.urlopen", side_effect=urlopen_fn), \
         patch("divoom_gui.gallery_download.media_decoder.extract_image_from_magic_43",
               return_value=(b"decodedpng", ".png")), \
         patch("divoom_gui.gallery_download.media_decoder.is_black_image",
               return_value=False):
        out = m.fetch_gallery(classify=18, target_size=16)
        assert out == "[]"  # no pre-existing gallery_cache.json -> cached_data empty
        _wait_for_fetch_thread()

    assert (cache_dir / "needs_download.png").read_bytes() == b"decodedpng"
    assert captured_bodies[0]["DevicePassword"] == "secretpw"

    cache_file = tmp_path / ".config" / "divoom-control" / "gallery_cache.json"
    saved = json.loads(cache_file.read_text())
    assert len(saved) == 3
    assert {item["name"] for item in saved} == {"New", "Old", "NoFileId"}

    assert m.window.evaluate_js.call_count >= 4  # 3 progressive + 1 final broadcast


def test_fetch_gallery_file_size_bitmask_explicit_vs_lookup(tmp_path, monkeypatch):
    """file_size>0 is used directly; file_size=0 falls back to
    FILE_SIZE_BITMASK.get(target_size, 1), defaulting to 1 for an unknown
    target_size — both arms of that branch."""
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()
    m.cached_creds = MagicMock(token="tok", user_id=1)

    bodies_explicit, bodies_lookup = [], []
    with patch("urllib.request.urlopen",
               side_effect=_fake_urlopen_factory(file_list=[], captured_bodies=bodies_explicit)):
        m.fetch_gallery(classify=1, target_size=16, file_size=64)
        _wait_for_fetch_thread()
    assert bodies_explicit[0]["FileSize"] == 64

    with patch("urllib.request.urlopen",
               side_effect=_fake_urlopen_factory(file_list=[], captured_bodies=bodies_lookup)):
        m.fetch_gallery(classify=1, target_size=99999, file_size=0)  # unknown size
        _wait_for_fetch_thread()
    assert bodies_lookup[0]["FileSize"] == 1  # FILE_SIZE_BITMASK.get(99999, 1)


def test_fetch_gallery_retries_and_refreshes_credentials_on_transient_failure(tmp_path, monkeypatch):
    """First attempt fails -> credentials reset -> second attempt refetches
    creds with force_refresh=True and succeeds. Covers both `force_refresh`
    arms (retries<1 false then true) and the config.ini credential path."""
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()  # cached_creds starts None -> forces the config.ini path

    cfg_dir = tmp_path / ".config" / "divoom-control"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.ini").write_text("[divoom]\nemail = a@b.com\npassword = pw\n")

    fake_creds = MagicMock(token="tok", user_id=7)
    with patch("urllib.request.urlopen",
               side_effect=_fake_urlopen_factory(file_list=[], list_raises_first_n=1)), \
         patch("divoom_gui.gallery_sync.divoom_auth.get_credentials",
               return_value=fake_creds) as mock_get_creds:
        m.fetch_gallery(classify=1)
        _wait_for_fetch_thread()

    assert mock_get_creds.call_count == 2
    assert mock_get_creds.call_args_list[0].kwargs["force_refresh"] is False
    assert mock_get_creds.call_args_list[1].kwargs["force_refresh"] is True


def test_fetch_gallery_credentials_not_configured_reports_error(tmp_path, monkeypatch, caplog):
    """No cached creds and no config.ini -> permanent failure; the error is
    classified as an auth issue (is_expired) and broadcast if a window
    exists, or silently skipped (no crash) if it doesn't."""
    monkeypatch.setenv("HOME", str(tmp_path))

    with caplog.at_level(logging.WARNING, logger="divoom_gui"):
        # No window: covers the `if self.window` false arm in the error handler.
        m_no_window = _Host()
        with patch("urllib.request.urlopen", side_effect=AssertionError("must not be called")):
            m_no_window.fetch_gallery(classify=1)
            _wait_for_fetch_thread()
        assert not (tmp_path / ".config" / "divoom-control" / "gallery_cache.json").exists()

        # With window: the error broadcast fires and reports is_expired=true.
        m_window = _Host()
        m_window.window = MagicMock()
        with patch("urllib.request.urlopen", side_effect=AssertionError("must not be called")):
            m_window.fetch_gallery(classify=1)
            _wait_for_fetch_thread()

    m_window.window.evaluate_js.assert_called_once()
    js_code = m_window.window.evaluate_js.call_args[0][0]
    assert "onGalleryFetchError" in js_code
    assert ", true," in js_code  # is_expired_val
    assert "Background gallery fetch failed permanently" in caplog.text


def test_fetch_gallery_token_expired_return_code_marks_expired(tmp_path, monkeypatch):
    """ReturnCode in [9, 10, 11] means the cloud rejected the token. Both
    retry attempts must be able to re-fetch credentials (config.ini present
    + get_credentials mocked) so the final error is really the ReturnCode
    failure, not an unrelated "credentials not configured"."""
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()
    m.window = MagicMock()
    m.cached_creds = MagicMock(token="tok", user_id=1)

    cfg_dir = tmp_path / ".config" / "divoom-control"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.ini").write_text("[divoom]\nemail = a@b.com\npassword = pw\n")

    with patch("urllib.request.urlopen", side_effect=_fake_urlopen_factory(rc=10)), \
         patch("divoom_gui.gallery_sync.divoom_auth.get_credentials",
               return_value=MagicMock(token="tok2", user_id=1)):
        m.fetch_gallery(classify=1)
        _wait_for_fetch_thread()

    js_code = m.window.evaluate_js.call_args[0][0]
    assert "onGalleryFetchError" in js_code
    assert ", true," in js_code
    assert "Token expired" in js_code


def test_fetch_gallery_api_error_return_code_not_expired(tmp_path, monkeypatch):
    """A non-auth ReturnCode error is reported but NOT flagged as expired."""
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()
    m.window = MagicMock()
    m.cached_creds = MagicMock(token="tok", user_id=1)

    cfg_dir = tmp_path / ".config" / "divoom-control"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.ini").write_text("[divoom]\nemail = a@b.com\npassword = pw\n")

    with patch("urllib.request.urlopen",
               side_effect=_fake_urlopen_factory(rc=5, return_message="server exploded")), \
         patch("divoom_gui.gallery_sync.divoom_auth.get_credentials",
               return_value=MagicMock(token="tok2", user_id=1)):
        m.fetch_gallery(classify=1)
        _wait_for_fetch_thread()

    js_code = m.window.evaluate_js.call_args[0][0]
    assert "onGalleryFetchError" in js_code
    assert ", false," in js_code
    assert "server exploded" in js_code


def test_fetch_gallery_download_failure_continues_pipeline(tmp_path, monkeypatch, caplog):
    """A per-item download failure is warned but does not abort the whole
    fetch — the item still appears in results with an empty preview_url."""
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()
    m.cached_creds = MagicMock(token="tok", user_id=1)

    file_list = [{"FileId": "flaky", "FileName": "Flaky", "LikeCnt": 0, "FileType": 5}]
    with caplog.at_level(logging.WARNING, logger="divoom_gui"):
        with patch("urllib.request.urlopen",
                   side_effect=_fake_urlopen_factory(file_list=file_list, dl_raises_for={"flaky"})):
            m.fetch_gallery(classify=1)
            _wait_for_fetch_thread()

    assert "Gallery download failed for flaky" in caplog.text
    cache_dir = tmp_path / ".config" / "divoom-control" / "cache_gallery"
    assert not (cache_dir / "flaky.bin").exists()

    cache_file = tmp_path / ".config" / "divoom-control" / "gallery_cache.json"
    saved = json.loads(cache_file.read_text())
    assert saved[0]["preview_url"] == ""


def test_fetch_gallery_decode_signature_branches(tmp_path, monkeypatch):
    """With magic-43 extraction returning nothing, raw bytes are classified
    by file signature (GIF/PNG/JPEG), falling back to decode_and_save_preview
    for anything unrecognized."""
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()
    m.cached_creds = MagicMock(token="tok", user_id=1)

    file_list = [
        {"FileId": "is_gif", "FileName": "G", "FileType": 5},
        {"FileId": "is_png", "FileName": "P", "FileType": 5},
        {"FileId": "is_jpg", "FileName": "J", "FileType": 5},
        {"FileId": "is_other", "FileName": "O", "FileType": 5},
    ]
    dl_bytes_map = {
        "is_gif": b"GIF89a" + b"\x00" * 10,
        "is_png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 10,
        "is_jpg": b"\xff\xd8" + b"\x00" * 10,
        "is_other": b"unrecognized bytes",
    }

    fallback_calls = []

    def fake_decode_and_save_preview(raw_bytes, out_path):
        fallback_calls.append((raw_bytes, out_path))
        out_path.write_bytes(b"fallback-png")
        return True

    with patch("urllib.request.urlopen",
               side_effect=_fake_urlopen_factory(file_list=file_list, dl_bytes_map=dl_bytes_map)), \
         patch("divoom_gui.gallery_download.media_decoder.extract_image_from_magic_43", return_value=None), \
         patch("divoom_gui.gallery_download.media_decoder.decode_and_save_preview",
               side_effect=fake_decode_and_save_preview):
        m.fetch_gallery(classify=1)
        _wait_for_fetch_thread()

    cache_dir = tmp_path / ".config" / "divoom-control" / "cache_gallery"
    assert (cache_dir / "is_gif.gif").exists()
    assert (cache_dir / "is_png.png").exists()
    assert (cache_dir / "is_jpg.jpg").exists()
    assert len(fallback_calls) == 1
    assert (cache_dir / "is_other.png").read_bytes() == b"fallback-png"


def test_fetch_gallery_corrupt_bin_is_deleted_so_next_fetch_redownloads(tmp_path, monkeypatch):
    """Regression (user report: 'most images don't render'): a truncated /
    undecodable download used to cache the bad `.bin` forever — every later
    fetch re-decoded the same corrupt bytes and failed again, permanently.
    Decode failure must now delete the `.bin` so the NEXT fetch re-downloads
    fresh bytes instead of retrying the same corrupt cache entry forever."""
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()
    m.cached_creds = MagicMock(token="tok", user_id=1)
    file_list = [{"FileId": "corrupt", "FileName": "C", "FileType": 5}]
    cache_dir = tmp_path / ".config" / "divoom-control" / "cache_gallery"

    # Round 1: download succeeds, decode fails (simulates a truncated
    # AES-CBC payload) — the .bin must NOT survive the run.
    with patch("urllib.request.urlopen",
               side_effect=_fake_urlopen_factory(file_list=file_list,
                                                  dl_bytes_map={"corrupt": b"not a real container"})), \
         patch("divoom_gui.gallery_download.media_decoder.extract_image_from_magic_43", return_value=None), \
         patch("divoom_gui.gallery_download.media_decoder.decode_and_save_preview", return_value=False):
        m.fetch_gallery(classify=1)
        _wait_for_fetch_thread()

    assert not (cache_dir / "corrupt.bin").exists()
    assert not (cache_dir / "corrupt.png").exists()
    cache_file = tmp_path / ".config" / "divoom-control" / "gallery_cache.json"
    assert json.loads(cache_file.read_text())[0]["preview_url"] == ""

    # Round 2: same file_id, decode now succeeds — because the bad .bin was
    # deleted, this fetch re-downloads (not re-decodes stale bytes) and the
    # item ends up with a real preview.
    def fake_decode_ok(raw_bytes, out_path):
        out_path.write_bytes(b"decoded-png")
        return True

    with patch("urllib.request.urlopen",
               side_effect=_fake_urlopen_factory(file_list=file_list,
                                                  dl_bytes_map={"corrupt": b"a real container this time"})), \
         patch("divoom_gui.gallery_download.media_decoder.extract_image_from_magic_43", return_value=None), \
         patch("divoom_gui.gallery_download.media_decoder.decode_and_save_preview",
               side_effect=fake_decode_ok):
        m.fetch_gallery(classify=1)
        _wait_for_fetch_thread()

    assert (cache_dir / "corrupt.png").read_bytes() == b"decoded-png"
    saved = json.loads(cache_file.read_text())
    assert saved[0]["preview_url"].startswith("data:image/png;base64,")


def test_fetch_gallery_progressive_and_error_broadcast_exceptions_are_caught(tmp_path, monkeypatch, caplog):
    """If window.evaluate_js itself always raises, the per-item progressive
    send is warned and skipped, the (un-guarded) final broadcast raising
    propagates into the outer handler, and THAT handler's own attempt to
    report the error also fails safely and is warned."""
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()
    m.cached_creds = MagicMock(token="tok", user_id=1)
    m.window = MagicMock()
    m.window.evaluate_js.side_effect = RuntimeError("js boom")

    file_list = [{"FileId": "x", "FileName": "X", "FileType": 5}]
    with caplog.at_level(logging.WARNING, logger="divoom_gui"):
        with patch("urllib.request.urlopen", side_effect=_fake_urlopen_factory(file_list=file_list)):
            m.fetch_gallery(classify=1)
            _wait_for_fetch_thread()

    assert "Failed to send progressive gallery item" in caplog.text
    assert "Background gallery fetch failed permanently" in caplog.text
    assert "Failed to send gallery fetch error" in caplog.text
    # The cache write happens before the final broadcast attempt, so it must
    # still have succeeded despite every evaluate_js call blowing up.
    cache_file = tmp_path / ".config" / "divoom-control" / "gallery_cache.json"
    assert json.loads(cache_file.read_text())[0]["name"] == "X"


def test_fetch_gallery_cache_save_failure_is_warned(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()
    m.cached_creds = MagicMock(token="tok", user_id=1)

    with caplog.at_level(logging.WARNING, logger="divoom_gui"):
        with patch("urllib.request.urlopen", side_effect=_fake_urlopen_factory(file_list=[])), \
             patch("divoom_gui.gallery_sync.atomic_write_text", side_effect=OSError("disk full")):
            m.fetch_gallery(classify=1)
            _wait_for_fetch_thread()

    assert "Failed to save gallery cache" in caplog.text
