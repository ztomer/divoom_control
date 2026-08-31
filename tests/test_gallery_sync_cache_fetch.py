"""gallery_sync coverage: cached-gallery readers and the fetch_gallery
worker (split from test_gallery_sync_coverage.py)."""
import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.support.gallery_sync_common import (  # noqa: F401
    FakeDaemonClient,
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
#
# R70 P2.2. These used to drive a fake `urllib.request.urlopen` answering both
# the GetCategoryFileListV2 POST and the per-item CDN GET, because the GUI made
# both calls itself. It makes neither now: the seam is two named daemon
# commands, and the tests say so.
#
# The behaviours worth keeping were kept — an auth failure marks the banner
# expired, a per-item failure does not empty the gallery, broadcast and
# cache-write failures are warned not raised. What went with the implementation
# went deliberately: container-magic sniffing and `.bin` corruption recovery
# were the GUI decoder's problems, and the GUI has no decoder.


def _daemon_host(tmp_path, monkeypatch, client, window=True):
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _Host()
    m.window = MagicMock() if window else None
    m._daemon_client = client
    return m


def test_fetch_gallery_asks_the_daemon_and_streams_every_item(tmp_path, monkeypatch):
    """Happy path: the list comes from `fetch_gallery`, each preview from
    `get_animated_preview`, and every item is streamed progressively."""
    client = FakeDaemonClient(
        file_list=[
            {"FileId": "aaa", "FileName": "New", "LikeCnt": 3, "FileType": 5},
            {"FileId": "bbb", "FileName": "Old", "LikeCnt": 1, "FileType": 5},
            {"FileName": "NoFileId"},
        ],
        previews={"aaa": "data:image/gif;base64,R0lGODlhAQABAAAAACw=",
                  "bbb": "data:image/png;base64,iVBORw0KGgo="},
    )
    m = _daemon_host(tmp_path, monkeypatch, client)
    assert m.fetch_gallery(classify=18, target_size=16) == "[]"
    _wait_for_fetch_thread()

    assert client.fetch_calls == [
        {"classify": 18, "limit": 30, "file_sort": 1, "file_size": 1}]
    assert set(client.preview_calls) == {"aaa", "bbb"}

    saved = json.loads(
        (tmp_path / ".config" / "divoom-control" / "gallery_cache.json").read_text())
    assert {i["name"] for i in saved} == {"New", "Old", "NoFileId"}
    assert saved[0]["preview_url"].startswith("data:image/gif;base64,")
    assert m.window.evaluate_js.call_count >= 4  # 3 progressive + 1 final


def test_fetch_gallery_file_size_bitmask_explicit_vs_lookup(tmp_path, monkeypatch):
    """file_size>0 is passed through; 0 falls back to the size lookup."""
    client = FakeDaemonClient(file_list=[])
    m = _daemon_host(tmp_path, monkeypatch, client)
    m.fetch_gallery(classify=1, target_size=16, file_size=32)
    _wait_for_fetch_thread()
    assert client.fetch_calls[-1]["file_size"] == 32

    client.fetch_calls.clear()
    m.fetch_gallery(classify=1, target_size=64, file_size=0)
    _wait_for_fetch_thread()
    assert client.fetch_calls[-1]["file_size"] == 4  # FILE_SIZE_BITMASK[64]

    client.fetch_calls.clear()
    m.fetch_gallery(classify=1, target_size=999, file_size=0)
    _wait_for_fetch_thread()
    assert client.fetch_calls[-1]["file_size"] == 1  # unknown size -> default


def test_an_auth_failure_marks_the_banner_expired(tmp_path, monkeypatch):
    """The expired-credentials banner is driven by the daemon's `cause` flag.

    It used to be decided by searching the error TEXT for "expired"/"token"/
    "credentials not configured" — so an upstream rewording silently changed
    which banner the user saw.
    """
    from divoom_client.daemon_cloud import CloudUnavailable

    client = FakeDaemonClient(
        fetch_error=CloudUnavailable("UserNewGuest failed (RC=10)", "auth"))
    m = _daemon_host(tmp_path, monkeypatch, client)
    m.fetch_gallery(classify=1, target_size=16)
    _wait_for_fetch_thread()

    calls = [c.args[0] for c in m.window.evaluate_js.call_args_list]
    err = [c for c in calls if "onGalleryFetchError" in c]
    assert err and ", true," in err[0], err


def test_a_cloud_failure_is_reported_but_not_as_expired(tmp_path, monkeypatch):
    from divoom_client.daemon_cloud import CloudUnavailable

    client = FakeDaemonClient(
        fetch_error=CloudUnavailable("Divoom said no (RC=5)", "cloud"))
    m = _daemon_host(tmp_path, monkeypatch, client)
    m.fetch_gallery(classify=1, target_size=16)
    _wait_for_fetch_thread()

    calls = [c.args[0] for c in m.window.evaluate_js.call_args_list]
    err = [c for c in calls if "onGalleryFetchError" in c]
    assert err and ", false," in err[0], err
    assert "RC=5" in err[0]


def test_an_absent_daemon_reports_rather_than_hanging(tmp_path, monkeypatch):
    m = _daemon_host(tmp_path, monkeypatch, None)
    m.fetch_gallery(classify=1, target_size=16)
    _wait_for_fetch_thread()
    calls = [c.args[0] for c in m.window.evaluate_js.call_args_list]
    assert any("onGalleryFetchError" in c and "background service" in c for c in calls)


def test_one_undecodable_item_does_not_empty_the_gallery(tmp_path, monkeypatch, caplog):
    """A per-item failure is not a gallery failure.

    The distinction the whole round is about: "this one asset could not be
    decoded" and "the cloud could not be reached" are different states and must
    not collapse into one empty grid.
    """
    from divoom_client.daemon_cloud import CloudUnavailable

    client = FakeDaemonClient(
        file_list=[{"FileId": "good", "FileName": "Good"},
                   {"FileId": "bad", "FileName": "Bad"}],
        previews={"good": "data:image/gif;base64,R0lGODlhAQABAAAAACw="},
        preview_errors={"bad": CloudUnavailable("unrecognized container magic", "cloud")},
    )
    m = _daemon_host(tmp_path, monkeypatch, client)
    with caplog.at_level(logging.WARNING):
        m.fetch_gallery(classify=1, target_size=16)
        _wait_for_fetch_thread()

    saved = json.loads(
        (tmp_path / ".config" / "divoom-control" / "gallery_cache.json").read_text())
    assert len(saved) == 2
    by_name = {i["name"]: i for i in saved}
    assert by_name["Good"]["preview_url"].startswith("data:")
    assert by_name["Bad"]["preview_url"] == ""
    assert "unrecognized container magic" in caplog.text


def test_broadcast_failures_are_warned_not_raised(tmp_path, monkeypatch, caplog):
    client = FakeDaemonClient(
        file_list=[{"FileId": "aaa", "FileName": "A"}],
        previews={"aaa": "data:image/gif;base64,R0lGODlhAQABAAAAACw="})
    m = _daemon_host(tmp_path, monkeypatch, client)
    m.window.evaluate_js.side_effect = RuntimeError("webview gone")
    with caplog.at_level(logging.WARNING):
        m.fetch_gallery(classify=1, target_size=16)
        _wait_for_fetch_thread()
    assert "Failed to send progressive gallery item" in caplog.text


def test_cache_save_failure_is_warned(tmp_path, monkeypatch, caplog):
    client = FakeDaemonClient(file_list=[{"FileId": "aaa", "FileName": "A"}],
                              previews={"aaa": "data:image/png;base64,iVBORw0KGgo="})
    m = _daemon_host(tmp_path, monkeypatch, client)
    with patch("divoom_gui.gallery_sync.atomic_write_text",
               side_effect=OSError("disk full")):
        with caplog.at_level(logging.WARNING):
            m.fetch_gallery(classify=1, target_size=16)
            _wait_for_fetch_thread()
    assert "Failed to save gallery cache" in caplog.text
