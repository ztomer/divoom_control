"""Shared helpers for the split hot-update test modules."""
import pytest

from divoom_lib.tools.hot_update import HotFile, clear_hot_manifest_cache


@pytest.fixture(autouse=True)
def _clear_hot_cache():
    clear_hot_manifest_cache()
    yield
    clear_hot_manifest_cache()


def _file(vendor=40005454, version=1099, body=b"\x07" * 522):
    f = HotFile(vendor, f"group1/v{version}.bin", version, "")
    f.body = body
    return f


class _FakeResp:
    """Minimal context-manager stand-in for urllib's HTTPResponse (matches the
    convention in tests/test_hot_preview_consistency.py)."""

    def __init__(self, data: bytes):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._data
