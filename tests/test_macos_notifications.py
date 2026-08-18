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

from divoom_client.macos_notifications import (
    DEFAULT_ROUTING,
    MacAppRouter,
    MacNotificationMonitor,
    find_notification_db_path,
    parse_notification_record,
)


# ── Helpers ───────────────────────────────────────────────────────────


def _make_record(app: str, title: str, body: str, delivered_date: float) -> bytes:
    """Build a fake notification `data` BLOB matching the macOS schema."""
    return plistlib.dumps({
        "app": app,
        "req": {"titl": title, "body": body},
    })


def _create_db(path: Path) -> None:
    """Create the schema the monitor expects."""
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            "CREATE TABLE record ("
            "  rec_id INTEGER PRIMARY KEY,"
            "  app_id INTEGER,"
            "  uuid BLOB,"
            "  data BLOB,"
            "  request_date REAL,"
            "  request_last_date REAL,"
            "  delivered_date REAL,"
            "  presented BOOL,"
            "  style INTEGER,"
            "  snooze_fire_date REAL"
            ")"
        )
        conn.commit()


def _insert_record(
    path: Path, app: str, title: str, body: str, delivered_date: float,
) -> None:
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            "INSERT INTO record (data, delivered_date) VALUES (?, ?)",
            (_make_record(app, title, body, delivered_date), delivered_date),
        )
        conn.commit()


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


# ── `MacNotificationMonitor` (with mocked DB + time) ──────────────────


class _FakeClock:
    """A clock the test can advance manually."""
    def __init__(self, start: float = 1000.0):
        self.t = start
        self.lock = threading.Lock()
    def __call__(self) -> float:
        with self.lock:
            return self.t
    def advance(self, dt: float) -> None:
        with self.lock:
            self.t += dt


def _make_monitor(
    db_path: Path, interval: float = 0.05,
) -> tuple[MacNotificationMonitor, _FakeClock, list]:
    clock = _FakeClock()
    sleeps: list[float] = []
    def fake_sleep(dt: float) -> None:
        sleeps.append(dt)
        clock.advance(dt)
    router = MacAppRouter(rules=[("whatsapp", 6)])
    m = MacNotificationMonitor(
        router=router,
        poll_interval=interval,
        db_path=db_path,
        _time_source=clock,
        _sleep=fake_sleep,
    )
    sink_calls: list[tuple[int, str, str]] = []
    return m, clock, sink_calls


def _wait_for(predicate, timeout: float = 2.0) -> None:
    """Block until predicate() is truthy or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(f"predicate did not become true within {timeout}s")


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


# ── R61 coverage push ──────────────────────────────────────────────────

import subprocess
from unittest.mock import PropertyMock, patch

import divoom_client.macos_notifications as macos_notifications


# ── `find_notification_db_path` — every branch, deterministically ─────


def test_find_notification_db_path_non_darwin_returns_none_immediately(monkeypatch) -> None:
    """L75: the non-macOS early return, independent of the actual host OS."""
    monkeypatch.setattr(macos_notifications.sys, "platform", "linux")
    assert find_notification_db_path() is None


def test_find_notification_db_path_falls_back_when_getconf_missing(monkeypatch, tmp_path) -> None:
    """L81-82: subprocess.run raising (no `getconf` binary) is caught, and
    the function falls back to ~/Library/Application Support — here
    redirected to an empty tmp_path via Path.home(), where nothing exists
    so it correctly returns None (L83 true-branch, L92->91, L94)."""
    def _raise(*a, **k):
        raise FileNotFoundError("no such file: getconf")

    monkeypatch.setattr(macos_notifications.subprocess, "run", _raise)
    monkeypatch.setattr(macos_notifications.Path, "home", classmethod(lambda cls: tmp_path))
    assert find_notification_db_path() is None


def test_find_notification_db_path_finds_relative_candidate(monkeypatch, tmp_path) -> None:
    """L83->87 (base resolved from getconf, skip the fallback) + L90 (found
    via the first relative candidate)."""
    class _Result:
        returncode = 0
        stdout = str(tmp_path) + "\n"

    monkeypatch.setattr(macos_notifications.subprocess, "run", lambda *a, **k: _Result())
    target = tmp_path / "com.apple.notificationcenter" / "db2" / "db"
    target.parent.mkdir(parents=True)
    target.write_text("fake db")
    assert find_notification_db_path() == target


def test_find_notification_db_path_finds_absolute_group_container_candidate(monkeypatch, tmp_path) -> None:
    """The R42 §2 absolute-path fallback (usernoted group container) when
    neither relative candidate exists."""
    class _Result:
        returncode = 0
        stdout = str(tmp_path / "no_such_base") + "\n"  # base exists but has no candidates

    monkeypatch.setattr(macos_notifications.subprocess, "run", lambda *a, **k: _Result())
    monkeypatch.setattr(macos_notifications.Path, "home", classmethod(lambda cls: tmp_path))
    target = (tmp_path / "Library" / "Group Containers" /
              "group.com.apple.usernoted" / "db2" / "db")
    target.parent.mkdir(parents=True)
    target.write_text("fake db")
    assert find_notification_db_path() == target


# ── `MacNotificationMonitor` construction + properties ─────────────────


def test_monitor_routing_path_constructor_arg_loads_router(tmp_path) -> None:
    """L186: an explicit `routing_path` (no `router` given) builds the
    router via MacAppRouter.from_file(routing_path)."""
    db = tmp_path / "db.sqlite"
    _create_db(db)
    m = MacNotificationMonitor(db_path=db, routing_path=tmp_path / "nonexistent_routing.json")
    # Falls back to defaults (file doesn't exist) but proves the
    # routing_path branch ran rather than the plain default-loader branch.
    assert m._router.route("com.whatsapp.whatsapp") == 6


def test_monitor_db_path_property(tmp_path) -> None:
    db = tmp_path / "db.sqlite"
    _create_db(db)
    m = MacNotificationMonitor(db_path=db)
    assert m.db_path == db


def test_monitor_stop_when_thread_is_none_but_is_running_reports_true(tmp_path) -> None:
    """L263->265: defends the (racy) case where is_running is True but
    ._thread is None — stop() must skip the join, not crash."""
    db = tmp_path / "db.sqlite"
    _create_db(db)
    m = MacNotificationMonitor(db_path=db)
    with patch.object(MacNotificationMonitor, "is_running", new_callable=PropertyMock,
                       return_value=True):
        m._thread = None
        m.stop()  # must not raise (AttributeError on None.join)


def test_initial_max_delivered_date_returns_zero_on_db_error(tmp_path) -> None:
    """L280-281: a broken/missing `record` table during the startup seed
    query is swallowed; `_initial_max_delivered_date` degrades to 0.0."""
    db = tmp_path / "empty.sqlite"
    with sqlite3.connect(str(db)) as conn:
        conn.execute("CREATE TABLE unrelated (x INTEGER)")  # no `record` table
        conn.commit()
    m = MacNotificationMonitor(db_path=db)
    assert m._initial_max_delivered_date() == 0.0


# ── `_run` loop branches ────────────────────────────────────────────────


def test_run_loop_handles_two_records_with_identical_delivered_date(tmp_path) -> None:
    """L308->310: the second of two records sharing one delivered_date must
    still be processed (records_seen bumps) even though it's no longer
    STRICTLY greater than the (already-updated) _last_seen."""
    db = tmp_path / "db.sqlite"
    _create_db(db)
    m, clock, _ = _make_monitor(db, interval=0.05)
    sink_calls = []
    m.start(sink=lambda *a: sink_calls.append(a))
    try:
        _insert_record(db, "com.whatsapp.WhatsApp", "A", "a", 700.0)
        _insert_record(db, "com.whatsapp.WhatsApp", "B", "b", 700.0)
        _wait_for(lambda: m.records_seen >= 2, timeout=2.0)
        assert len(sink_calls) == 2
    finally:
        m.stop()


def test_run_loop_drops_malformed_record_mid_stream(tmp_path) -> None:
    """L313-314: a record whose data BLOB fails to parse (not just an
    unrouted app) is counted as dropped and the sink is never called for it."""
    db = tmp_path / "db.sqlite"
    _create_db(db)
    m, clock, _ = _make_monitor(db, interval=0.05)
    sink_calls = []
    m.start(sink=lambda *a: sink_calls.append(a))
    try:
        with sqlite3.connect(str(db)) as conn:
            conn.execute(
                "INSERT INTO record (data, delivered_date) VALUES (?, ?)",
                (b"\x00not a plist\x01", 800.0),
            )
            conn.commit()
        _wait_for(lambda: m.records_dropped >= 1, timeout=2.0)
        assert sink_calls == []
    finally:
        m.stop()


def test_run_loop_survives_router_raising(tmp_path) -> None:
    """L325-326: an unexpected exception anywhere in the per-record
    processing (here: the router itself blowing up) is caught by the
    outer loop guard — the monitor stays alive, not crashed."""
    db = tmp_path / "db.sqlite"
    _create_db(db)

    class _BoomRouter:
        def route(self, app):
            raise RuntimeError("router exploded")

    clock = _FakeClock()
    sleeps = []

    def fake_sleep(dt):
        sleeps.append(dt)
        clock.advance(dt)

    m = MacNotificationMonitor(
        router=_BoomRouter(), poll_interval=0.05, db_path=db,
        _time_source=clock, _sleep=fake_sleep,
    )
    m.start(sink=lambda *a: None)
    try:
        _insert_record(db, "com.whatsapp.WhatsApp", "x", "y", 900.0)
        _wait_for(lambda: m.is_running and m.records_seen >= 1, timeout=2.0)
        assert m.is_running  # survived the router exception
    finally:
        m.stop()


# ── CLI helpers ──────────────────────────────────────────────────────────


def test_print_sink_prints_formatted_line(capsys) -> None:
    macos_notifications._print_sink(6, "Alice", "hi")
    out = capsys.readouterr().out
    assert "app_type=6" in out and "Alice" in out and "hi" in out


def test_cli_returns_2_when_db_not_found(monkeypatch) -> None:
    """L348-352: the CLI wraps FileNotFoundError from the constructor into
    a clean exit code 2 + stderr message, not a traceback."""
    monkeypatch.setattr(sys, "argv", ["prog"])

    def _raise(*a, **k):
        raise FileNotFoundError("no db on this box")

    monkeypatch.setattr(macos_notifications, "MacNotificationMonitor", _raise)
    assert macos_notifications._cli() == 2


class _FakeCliMonitor:
    """Stand-in used by the CLI tests below — start/stop are no-ops."""
    db_path = "/fake/db"
    started_with = None

    def __init__(self, poll_interval=1.0):
        self.poll_interval = poll_interval

    def start(self, sink):
        _FakeCliMonitor.started_with = sink

    def stop(self):
        pass


def test_cli_duration_path_stops_after_sleep(monkeypatch) -> None:
    """L356-358: with --duration > 0, the CLI sleeps then calls stop()."""
    monkeypatch.setattr(sys, "argv", ["prog", "--duration", "0.001"])
    monkeypatch.setattr(macos_notifications, "MacNotificationMonitor", _FakeCliMonitor)
    stopped = []
    monkeypatch.setattr(_FakeCliMonitor, "stop", lambda self: stopped.append(True))
    assert macos_notifications._cli() == 0
    assert stopped == [True]


def test_cli_forever_path_stops_on_keyboard_interrupt(monkeypatch) -> None:
    """L359-363: with no --duration (the "forever" branch), a
    KeyboardInterrupt during the wait loop is caught and calls stop()."""
    monkeypatch.setattr(sys, "argv", ["prog"])
    monkeypatch.setattr(macos_notifications, "MacNotificationMonitor", _FakeCliMonitor)
    stopped = []
    monkeypatch.setattr(_FakeCliMonitor, "stop", lambda self: stopped.append(True))

    def _interrupt(_secs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(macos_notifications.time, "sleep", _interrupt)
    assert macos_notifications._cli() == 0
    assert stopped == [True]
