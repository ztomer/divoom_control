"""Shared helpers for the split macos-notifications test modules."""
import plistlib
import sqlite3
import threading
import time
from pathlib import Path

from divoom_client.macos_notifications import (
    MacAppRouter,
    MacNotificationMonitor,
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
