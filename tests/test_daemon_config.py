"""R24 — daemon config (daemon.ini next to the GUI config).

Verifies the named defaults, file-write-on-missing, override parsing (incl. the
0-limit edge that `or` would eat), missing-key fallback, and the
scan_read_timeout slack helper. No magic numbers should reach the call sites —
they read this config instead.
"""
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))

from divoom_client import daemon_config as dc


def test_defaults_match_named_constants():
    cfg = dc.DaemonConfig()
    assert cfg.scan_timeout == dc.DEFAULT_SCAN_TIMEOUT
    assert cfg.scan_limit == dc.DEFAULT_SCAN_LIMIT
    assert cfg.scan_read_slack == dc.DEFAULT_SCAN_READ_SLACK
    assert cfg.client_timeout == dc.DEFAULT_CLIENT_TIMEOUT
    assert cfg.reconnect_scan_timeout == dc.DEFAULT_RECONNECT_SCAN_TIMEOUT
    assert cfg.connect_timeout == dc.DEFAULT_CONNECT_TIMEOUT
    assert cfg.sync_read_timeout == dc.DEFAULT_SYNC_READ_TIMEOUT


def test_sync_read_timeout_covers_slow_ble_stream():
    # Artwork sync = download + full BLE stream; must far exceed quick timeout.
    cfg = dc.DaemonConfig()
    assert cfg.sync_read_timeout > cfg.connect_timeout


def test_connect_timeout_is_longer_than_quick_timeout():
    # BLE connect is slow — the connect read timeout must comfortably exceed the
    # quick-command timeout, else the GUI gives up mid-handshake ("timed out").
    cfg = dc.DaemonConfig()
    assert cfg.connect_timeout > cfg.client_timeout


def test_scan_read_timeout_adds_slack_to_per_scan_timeout():
    cfg = dc.DaemonConfig(scan_read_slack=10.0)
    # The user-chosen per-scan timeout drives it, not the default scan_timeout.
    assert cfg.scan_read_timeout(8) == 18.0
    assert cfg.scan_read_timeout(45) == 55.0


def test_writes_commented_default_when_missing(tmp_path):
    p = tmp_path / "daemon.ini"
    cfg = dc.load_daemon_config(p, force=True)
    assert cfg == dc.DaemonConfig()
    assert p.exists()
    text = p.read_text()
    assert "[daemon]" in text
    assert "scan_timeout" in text
    assert text.lstrip().startswith("#")  # has explanatory comments


def test_overrides_parsed_and_zero_limit_preserved(tmp_path):
    p = tmp_path / "daemon.ini"
    p.write_text(
        "[daemon]\n"
        "scan_timeout = 45\n"
        "scan_limit = 0\n"          # 0 = no cap, must survive
        "scan_read_slack = 5\n"
        "client_timeout = 1.5\n"
    )
    cfg = dc.load_daemon_config(p, force=True)
    assert cfg.scan_timeout == 45.0
    assert cfg.scan_limit == 0
    assert cfg.scan_read_slack == 5.0
    assert cfg.client_timeout == 1.5
    # absent key falls back to the named default
    assert cfg.reconnect_scan_timeout == dc.DEFAULT_RECONNECT_SCAN_TIMEOUT


def test_bad_value_falls_back_to_default(tmp_path):
    p = tmp_path / "daemon.ini"
    p.write_text("[daemon]\nscan_timeout = not-a-number\n")
    cfg = dc.load_daemon_config(p, force=True)
    assert cfg.scan_timeout == dc.DEFAULT_SCAN_TIMEOUT


def test_missing_section_uses_defaults(tmp_path):
    p = tmp_path / "daemon.ini"
    p.write_text("[other]\nfoo = bar\n")
    cfg = dc.load_daemon_config(p, force=True)
    assert cfg == dc.DaemonConfig()
