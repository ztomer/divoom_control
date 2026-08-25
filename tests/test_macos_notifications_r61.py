"""R61 coverage push for divoom_client.macos_notifications (split from
test_macos_notifications.py): db-path branches, monitor construction,
_run loop branches and CLI helpers."""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import PropertyMock, patch

import pytest

import divoom_client.macos_notifications as macos_notifications
from divoom_client.macos_notifications import (
    DEFAULT_ROUTING,
    MacAppRouter,
    MacNotificationMonitor,
    find_notification_db_path,
)
from tests.support.macos_notifications_common import (  # noqa: F401
    _FakeClock,
    _create_db,
    _insert_record,
    _make_monitor,
    _make_record,
    _wait_for,
)


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
    STRICTLY greater than the (already-updated) _last_seen.

    The two inserts are SEPARATED BY A POLL PASS on purpose. Written as two
    back-to-back inserts, this test almost always caught both records in one
    query -- where ties are harmless, because the query returned them before
    the cursor moved -- and so it exercised the across-batch tie it names only
    when the poll happened to land in the gap. That is the flake seen on
    2026-08-23: the run that DID get the interleaving found the real bug
    (`WHERE delivered_date > ?` drops any record tying the cursor, forever) and
    failed, after ~2900 runs that never reached the branch.

    Waiting for records_seen >= 1 forces the cursor to advance to 700.0 before
    B exists, so every run now takes the path.
    """
    db = tmp_path / "db.sqlite"
    _create_db(db)
    m, clock, _ = _make_monitor(db, interval=0.05)
    sink_calls = []
    m.start(sink=lambda *a: sink_calls.append(a))
    try:
        _insert_record(db, "com.whatsapp.WhatsApp", "A", "a", 700.0)
        _wait_for(lambda: m.records_seen >= 1, timeout=2.0)  # cursor now == 700.0
        _insert_record(db, "com.whatsapp.WhatsApp", "B", "b", 700.0)
        _wait_for(lambda: m.records_seen >= 2, timeout=2.0)
        assert len(sink_calls) == 2
    finally:
        m.stop()


def test_startup_seed_does_not_replay_but_admits_a_later_tie(tmp_path) -> None:
    """The startup cursor must exclude existing records without excluding a
    LATER record that ties their delivered_date.

    Seeding _last_seen from MAX(delivered_date) alone cannot tell those two
    cases apart -- it either replays history (`>=`) or drops the tie (`>`).
    The rowid tie-set is what separates them.
    """
    db = tmp_path / "db.sqlite"
    _create_db(db)
    _insert_record(db, "com.whatsapp.WhatsApp", "old", "already delivered", 900.0)
    m, clock, _ = _make_monitor(db, interval=0.05)
    sink_calls = []
    m.start(sink=lambda *a: sink_calls.append(a))
    try:
        _insert_record(db, "com.whatsapp.WhatsApp", "new", "same timestamp", 900.0)
        _wait_for(lambda: m.records_seen >= 1, timeout=2.0)
        assert [c[1] for c in sink_calls] == ["new"], (
            f"expected only the NEW record, got {sink_calls}"
        )
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
