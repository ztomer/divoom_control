"""The smoke script must be able to say NO — and must say it with an exit code.

`scripts/hw_smoke.py` printed its results with the house TUI's module-private
colour names (`_GRAY`, `_DIM`, `_RED`, `_RESET`), which do not exist outside
`tui/lib.py`. Every code path that PRINTED a result raised NameError — and the
raise was caught and reported as `warn(...)`, so the script exited 0. The
consequence was a run that said

    ✓ 4 device(s):
    ✗ scan failed: NameError: name '_GRAY' is not defined

and then exited 0: four panels found, reporting broken, verdict clean.

These tests pin the two properties that make the smoke an instrument:
  1. a branch that RAISES is a FAIL, and the run exits non-zero;
  2. a clean run exits 0 — so the non-zero above means something.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

hw_smoke = pytest.importorskip("hw_smoke")


class FakeClient:
    """Enough DaemonClient for the smoke's discover phase, with faults."""

    def __init__(self, devices=None, status_raises=False, scan_raises=False):
        self._devices = devices if devices is not None else [
            {"name": "Ditoo-light-2", "address": "AA:BB:CC:DD:EE:01"},
        ]
        self._status_raises = status_raises
        self._scan_raises = scan_raises

    def get_connection_state(self):
        if self._status_raises:
            raise RuntimeError("status blew up")
        return {"connected": False, "mac": None}

    def get_device_activity(self):
        return {}

    def scan(self, timeout=0):
        if self._scan_raises:
            raise RuntimeError("scan blew up")
        return {"devices": self._devices}


def _run(monkeypatch, client, phase="discover"):
    monkeypatch.setattr(hw_smoke, "_client", lambda: client)
    monkeypatch.setattr(sys, "argv", ["hw_smoke.py", "--phase", phase])
    return hw_smoke.main()


def test_a_clean_discover_exits_zero_and_names_the_devices(monkeypatch, capsys):
    client = FakeClient(devices=[
        {"name": "Ditoo-light-2", "address": "AA:BB:CC:DD:EE:01"},
        {"name": "Pixoo-1", "address": "AA:BB:CC:DD:EE:02"},
    ])
    assert _run(monkeypatch, client) == 0
    out = capsys.readouterr()
    assert "Ditoo-light-2" in out.out
    assert "Pixoo-1" in out.out
    assert "AA:BB:CC:DD:EE:01" in out.out


def test_a_raising_status_branch_is_a_failure_and_exits_nonzero(monkeypatch, capsys):
    """The branch that used to warn about a NameError. It must FAIL."""
    client = FakeClient(status_raises=True)
    rc = _run(monkeypatch, client)
    assert rc != 0, "a branch that raised was reported as a clean run"
    captured = capsys.readouterr()
    assert "status blew up" in captured.out + captured.err


def test_a_raising_scan_is_a_failure_and_exits_nonzero(monkeypatch, capsys):
    client = FakeClient(scan_raises=True)
    rc = _run(monkeypatch, client)
    assert rc != 0, "a scan that raised was reported as a clean run"
    captured = capsys.readouterr()
    assert "scan blew up" in captured.out + captured.err


def test_a_run_that_finds_devices_still_names_them_when_a_later_branch_raises(
        monkeypatch, capsys):
    """The original bug exactly: the scan WORKED, the reporting raised."""
    client = FakeClient(devices=[{"name": "Tivoo-Max-light-3",
                                  "address": "AA:BB:CC:DD:EE:03"}],
                        status_raises=True)
    rc = _run(monkeypatch, client)
    assert rc != 0
    captured = capsys.readouterr()
    assert "Tivoo-Max-light-3" in captured.out


def test_the_failures_helper_is_not_a_warning_in_disguise():
    """`Failures.fail` must PRINT as an error, on stderr, and count."""
    failures = hw_smoke.Failures()
    assert not failures
    failures.fail("something broke")
    assert failures
    assert len(failures) == 1
    assert "something broke" in failures.items[0]
