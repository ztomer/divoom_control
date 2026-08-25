"""fetch_hot_manifest / download_hot_file HTTP-boundary coverage (split
from test_hot_update_coverage.py)."""
import json

import pytest

from divoom_lib.tools import hot_update as hu_mod
from divoom_lib.tools.hot_update import (
    HotFile,
    download_hot_file,
    fetch_hot_manifest,
)
from tests.support.hot_update_common import (  # noqa: F401
    _FakeResp,
    _clear_hot_cache,
    _file,
)


# ── fetch_hot_manifest / download_hot_file: the HTTP boundary ──────────────

def test_fetch_hot_manifest_parses_vendor_and_file_list(monkeypatch):
    payload = {
        "VendorList": [
            {"VendorId": 40005454, "FileList": [
                {"FileId": "group1/v1.bin", "Version": 1, "Sha1": "abc"},
                {"FileId": "group1/v2.bin", "Version": 2, "Sha1": ""},
            ]},
        ]
    }

    def fake_urlopen(req, timeout=None):
        assert req.full_url == hu_mod.HOT_API_URL
        return _FakeResp(json.dumps(payload).encode())

    monkeypatch.setattr(hu_mod.urllib.request, "urlopen", fake_urlopen)

    files = fetch_hot_manifest(0)
    assert len(files) == 2
    assert files[0].vendor_id == 40005454
    assert files[0].file_id == "group1/v1.bin"
    assert files[0].version == 1
    assert files[0].sha1 == "abc"
    assert files[1].sha1 == ""


def test_fetch_hot_manifest_handles_empty_response(monkeypatch):
    monkeypatch.setattr(hu_mod.urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResp(b"{}"))
    assert fetch_hot_manifest(1) == []


def test_download_hot_file_success_sets_body(monkeypatch):
    body = b"\x01\x02\x03"
    monkeypatch.setattr(hu_mod.urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResp(body))
    f = _file(body=None)
    assert download_hot_file(f) is True
    assert f.body == body


def test_download_hot_file_sha1_mismatch_fails(monkeypatch):
    import hashlib
    body = b"\xAA\xBB"
    monkeypatch.setattr(hu_mod.urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResp(body))
    f = HotFile(1, "bad.bin", 1, hashlib.sha1(b"other bytes").hexdigest())
    assert download_hot_file(f) is False
    assert f.body is None


def test_download_hot_file_sha1_match_succeeds(monkeypatch):
    import hashlib
    body = b"\xAA\xBB\xCC"
    monkeypatch.setattr(hu_mod.urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResp(body))
    f = HotFile(1, "good.bin", 1, hashlib.sha1(body).hexdigest().upper())
    assert download_hot_file(f) is True
    assert f.body == body
