"""The GUI's reader of each panel's hot-channel verdict (U.5).

The daemon writes ``hotchannel_state.json`` ``panels`` (divoomd/src/hot_verdict.rs);
the GUI only reads it. A missing or corrupt file, or one from before U.5, is
"no verdict" -- the line then says "Never checked", never an invented success.
"""
import json

from divoom_lib import hot_verdict


def _state(tmp_path, monkeypatch, value):
    path = tmp_path / "hotchannel_state.json"
    path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
    monkeypatch.setenv("DIVOOM_HOT_VERDICTS", str(path))


def test_reads_the_panel_it_names_whatever_its_case(tmp_path, monkeypatch):
    _state(tmp_path, monkeypatch, {
        "last_outcome": "failed", "last_run_utc": 1793468518,
        "panels": {"F90D2CC9-420E": {"at": 1793468518, "by": "schedule", "outcome": "failed",
                                     "error": "connect already in progress"}}})
    assert hot_verdict.get("f90d2cc9-420e")["outcome"] == "failed"
    assert hot_verdict.get("other") == {}
    assert set(hot_verdict.all_verdicts()) == {"F90D2CC9-420E"}


def test_no_file_a_corrupt_file_or_a_pre_u5_file_is_no_verdict(tmp_path, monkeypatch):
    monkeypatch.setenv("DIVOOM_HOT_VERDICTS", str(tmp_path / "absent.json"))
    assert hot_verdict.get("P") == {}
    _state(tmp_path, monkeypatch, "{not json")
    assert hot_verdict.all_verdicts() == {}
    _state(tmp_path, monkeypatch, {"last_outcome": "ok", "devices": [{"address": "P"}]})
    assert hot_verdict.get("P") == {}
