"""
Tests for `gui/macos_notifications.py`.

Strategy:
- All DB I/O is intercepted by passing a temp SQLite file as the
  monitor's `db_path` kwarg. The monitor's `_fetch_new` reads from
  this file; we control it from the test thread.
- Time is injected via `_time_source` (a list of monotonic floats we
  pop) and `_sleep` is a no-op (so the loop returns control to the
  test immediately after one iteration).
- The monitor's `start()` spawns a daemon thread; we use a
  `threading.Event` sink to wait for the first delivery instead of
  using `time.sleep` from the test (which would flake).
"""
from __future__ import annotations

import plistlib
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

import pytest

from tests.support.macos_notifications_common import (  # noqa: F401
    _FakeClock,
    _create_db,
    _insert_record,
    _make_monitor,
    _make_record,
    _wait_for,
)
from divoom_client.macos_notifications import (
    DEFAULT_ROUTING,
    MacAppRouter,
    MacNotificationMonitor,
    find_notification_db_path,
    parse_notification_record,
)


# ── `parse_notification_record` ──────────────────────────────────────


def test_parse_notification_record_happy_path() -> None:
    raw = _make_record("com.apple.MobileSMS", "John", "Hi there", 1234.5)
    out = parse_notification_record(raw, delivered_date=1234.5)
    assert out is not None
    assert out["app"] == "com.apple.mobilesms"
    assert out["title"] == "John"
    assert out["body"] == "Hi there"
    assert out["delivered_date"] == 1234.5


def test_parse_notification_record_malformed_returns_none() -> None:
    out = parse_notification_record(b"\x00\x01\x02 not a plist")
    assert out is None


def test_parse_notification_record_missing_optional_keys() -> None:
    raw = plistlib.dumps({"app": "com.test.app"})  # no `req`
    out = parse_notification_record(raw)
    assert out is not None
    assert out["app"] == "com.test.app"
    assert out["title"] == ""
    assert out["body"] == ""


# ── `MacAppRouter` ────────────────────────────────────────────────────


def test_router_default_whatsapp_routes_correctly() -> None:
    r = MacAppRouter()
    assert r.route("com.whatsapp.whatsapp") == 6  # NOTIFICATION_APPS["WHATSAPP"]


def test_router_default_text_message_catches_sms_imessage_mail() -> None:
    r = MacAppRouter()
    assert r.route("com.apple.MobileSMS") == 7
    assert r.route("com.apple.Mail") == 7
    # "messages" substring catches iMessage without an exact match.
    assert r.route("com.apple.Messenger") == 13  # or 7; depends on order
    # Order matters; messenger is checked before messages:
    assert r.route("com.apple.Messenger") == 13  # MESSENGER


def test_router_unknown_app_returns_none() -> None:
    r = MacAppRouter()
    assert r.route("com.example.UnknownApp") is None


def test_router_empty_app_id_returns_none() -> None:
    r = MacAppRouter()
    assert r.route("") is None
    assert r.route(None or "") is None or r.route("") is None


def test_router_add_rule_takes_priority() -> None:
    r = MacAppRouter()
    r.add_rule("custom", 99)  # not a valid app_type, but routing logic doesn't care
    assert r.route("com.example.custom") == 99


def test_router_case_insensitive() -> None:
    r = MacAppRouter()
    assert r.route("com.WHATSAPP.WhatsApp") == 6


def test_default_routing_has_no_duplicate_keys() -> None:
    """Sanity: DEFAULT_ROUTING shouldn't have two rules with the same
    substring (the first one would always win anyway, but it's a
    maintenance smell)."""
    seen: set[str] = set()
    for substr, _ in DEFAULT_ROUTING:
        assert substr not in seen, f"duplicate substring in DEFAULT_ROUTING: {substr!r}"
        seen.add(substr)


def test_monitor_picks_up_new_notification(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite"
    _create_db(db)
    # Pre-seed a record at t=500 so the monitor's _last_seen seed ignores it.
    _insert_record(db, "com.whatsapp.WhatsApp", "Alice", "Hello!", 500.0)
    m, clock, sink_calls = _make_monitor(db, interval=0.05)
    def sink(app_type: int, title: str, body: str) -> None:
        sink_calls.append((app_type, title, body))
    m.start(sink=sink)
    try:
        # Insert a new record. The monitor is polling, so it should
        # pick it up on the next iteration.
        _insert_record(db, "com.whatsapp.WhatsApp", "Bob", "Hi back", 600.0)
        _wait_for(lambda: len(sink_calls) >= 1)
        assert sink_calls == [(6, "Bob", "Hi back")]
        assert m.records_seen >= 1
        assert m.records_routed == 1
        assert m.records_dropped == 0
    finally:
        m.stop()


def test_monitor_drops_unrouted_app(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite"
    _create_db(db)
    m, clock, sink_calls = _make_monitor(db, interval=0.05)
    m.start(sink=lambda *a: sink_calls.append(a))
    try:
        _insert_record(db, "com.example.UnknownApp", "x", "y", 600.0)
        _wait_for(lambda: m.records_dropped >= 1, timeout=2.0)
        assert sink_calls == []  # sink never called for unrouted apps
    finally:
        m.stop()


def test_monitor_does_not_replay_history_on_startup(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite"
    _create_db(db)
    _insert_record(db, "com.whatsapp.WhatsApp", "Old", "old", 100.0)
    m, clock, sink_calls = _make_monitor(db, interval=0.05)
    m.start(sink=lambda *a: sink_calls.append(a))
    try:
        # Give the monitor a few iterations; it should NOT see the old record.
        time.sleep(0.2)
        assert sink_calls == []
        assert m.records_seen == 0
    finally:
        m.stop()


def test_monitor_sink_exception_does_not_crash_loop(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite"
    _create_db(db)
    m, clock, sink_calls = _make_monitor(db, interval=0.05)
    def bad_sink(*a) -> None:
        raise RuntimeError("boom")
    m.start(sink=bad_sink)
    try:
        _insert_record(db, "com.whatsapp.WhatsApp", "x", "y", 600.0)
        _wait_for(lambda: m.records_dropped >= 1, timeout=2.0)
        # Monitor is still alive after the exception:
        assert m.is_running
    finally:
        m.stop()


def test_monitor_idempotent_start(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite"
    _create_db(db)
    m, _, _ = _make_monitor(db, interval=0.05)
    m.start(sink=lambda *a: None)
    try:
        first_thread = m._thread
        m.start(sink=lambda *a: None)  # should be a no-op
        assert m._thread is first_thread
    finally:
        m.stop()


def test_monitor_stop_when_not_running_is_noop(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite"
    _create_db(db)
    m, _, _ = _make_monitor(db, interval=0.05)
    m.stop()  # never started — must not raise


def test_monitor_missing_db_raises_filenotfound() -> None:
    m = MacNotificationMonitor(
        db_path=Path("/nonexistent/never/here.sqlite"),
    )
    with pytest.raises(FileNotFoundError):
        m.start(sink=lambda *a: None)


# ── `find_notification_db_path` (real system) ────────────────────────


def test_find_notification_db_path_returns_none_off_macos() -> None:
    """When run on Linux/CI, the function should return None immediately."""
    if sys.platform.startswith("darwin"):
        pytest.skip("darwin-specific behavior skipped on non-macOS")
    assert find_notification_db_path() is None


# ── Module surface ────────────────────────────────────────────────────


def test_module_exports_expected_symbols() -> None:
    import divoom_client.macos_notifications as m
    assert callable(m.MacNotificationMonitor)
    assert callable(m.MacAppRouter)
    assert callable(m.parse_notification_record)
    assert callable(m.find_notification_db_path)
    assert isinstance(m.DEFAULT_ROUTING, list)
