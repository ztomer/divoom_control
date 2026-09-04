"""R53 — per-device HOT-channel last-checked persistence.

The card shows a dated "Last checked <when>" instead of a blind "up to date".
These pin the store: record/get roundtrip, per-device keying, tolerant coercion,
and never-raise on a corrupt file.
"""
from __future__ import annotations

import json

import pytest

from divoom_lib import hot_update_state as st


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """Point the store at a temp file so tests never touch the real config."""
    monkeypatch.setenv("DIVOOM_HOT_STATE", str(tmp_path / "hot_update_state.json"))
    yield


def test_empty_when_absent():
    assert st.load_state() == {}
    assert st.get_check("AA:BB:CC:DD:EE:FF") == {}


def test_record_and_get_roundtrip():
    entry = st.record_check(
        "AA:BB:CC:DD:EE:FF",
        {"served": [{"file_id": "x"}], "manifest": 12, "downloaded": 10, "confirmed": 1},
        checked_at=1_720_000_000.0)
    assert entry == {"checked_at": 1_720_000_000.0, "served": 1,
                     "manifest": 12, "downloaded": 10, "confirmed": 1}
    assert st.get_check("AA:BB:CC:DD:EE:FF") == entry


def test_served_accepts_int_or_list():
    # Raw result carries served as a list; an already-counted summary as an int.
    e_list = st.record_check("dev1", {"served": [1, 2, 3], "manifest": 5, "downloaded": 5})
    assert e_list["served"] == 3
    e_int = st.record_check("dev2", {"served": 2, "manifest": 5, "downloaded": 5})
    assert e_int["served"] == 2


def test_per_device_keying():
    st.record_check("dev1", {"served": [1], "manifest": 3, "downloaded": 3}, checked_at=100.0)
    st.record_check("dev2", {"served": [], "manifest": 3, "downloaded": 3}, checked_at=200.0)
    assert st.get_check("dev1")["checked_at"] == 100.0
    assert st.get_check("dev2")["checked_at"] == 200.0
    assert st.get_check("dev1")["served"] == 1
    assert st.get_check("dev2")["served"] == 0
    # A later check for the same device overwrites, not appends.
    st.record_check("dev1", {"served": [], "manifest": 3, "downloaded": 3}, checked_at=300.0)
    assert st.get_check("dev1") == {"checked_at": 300.0, "served": 0,
                                    "manifest": 3, "downloaded": 3, "confirmed": 0}


def test_blank_address_is_noop():
    assert st.record_check("", {"manifest": 5}) == {}
    assert st.get_check("") == {}
    assert st.load_state() == {}


def test_corrupt_file_never_raises(tmp_path, monkeypatch):
    p = tmp_path / "corrupt.json"
    p.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("DIVOOM_HOT_STATE", str(p))
    assert st.load_state() == {}
    assert st.get_check("dev1") == {}


def test_missing_summary_fields_default_to_zero():
    e = st.record_check("dev1", {}, checked_at=1.0)
    assert e == {"checked_at": 1.0, "served": 0, "manifest": 0,
                 "downloaded": 0, "confirmed": 0}


def test_persisted_json_is_readable_map(tmp_path, monkeypatch):
    p = tmp_path / "state.json"
    monkeypatch.setenv("DIVOOM_HOT_STATE", str(p))
    st.record_check("AA:BB", {"served": [1], "manifest": 2, "downloaded": 2}, checked_at=5.0)
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["AA:BB"]["manifest"] == 2
