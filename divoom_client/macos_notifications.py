#!/usr/bin/env python3
"""
R13 §3 — mirror macOS notifications onto a connected Divoom device.

**Approach:** poll the macOS Notification Center SQLite database (private
API; not gated by TCC). The same approach used by
`mac-notification-forwarder` and similar open-source projects.

**Why not the public UNUserNotificationCenter / NSUserNotificationCenter?**
The public API only fires for *our own* app's notifications — Apple does
not let a third-party app subscribe to *all* system notifications. The
legitimate "catch-all" path is a notification service extension in a
properly bundled, code-signed .app — a much larger lift. The DB-poll
approach is what works today for any open-source notification monitor.

**Tradeoffs (be honest):**
- Polling, not push (1 Hz by default; ~1s latency on the conservative side).
- Reads a private-format DB; Apple could move/change it in a future macOS.
- Reads the `data` BLOB column which is a binary plist.
- Schema may differ between macOS versions — we handle the well-known
  columns (data, delivered_date, app) and ignore unknown ones.

**Usage:**

    monitor = MacNotificationMonitor(router=MacAppRouter(), poll_interval=1.0)
    monitor.start(sink=lambda app_type, title, body: print(app_type, title, body))

**Tests:** See ``tests/test_macos_notifications.py``. The DB layer is
fully mocked — tests don't require macOS or notifications enabled.
"""
from __future__ import annotations

import logging
import plistlib
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from divoom_lib.models import NOTIFICATION_APPS


logger = logging.getLogger(__name__)


# ── DB-path discovery ─────────────────────────────────────────────────


# Known paths in priority order. macOS has changed this several times
# (Sonoma, Sequoia, and the Tahoe/26 line). We probe each; the first that
# exists wins. If none exist, the monitor can't run —
# `find_notification_db_path()` returns None.
_CANDIDATE_RELATIVE_PATHS = (
    "com.apple.notificationcenter/db2/db",          # Sonoma + earlier
    "com.apple.usernotifications/db2/db",           # some Sequoia builds
)


def _candidate_absolute_paths(home: Path) -> tuple[Path, ...]:
    """Candidates that are NOT under DARWIN_USER_DIR. macOS 26 moved the
    store into usernoted's group container (R42 §2 — verified on 26.5)."""
    return (
        home / "Library" / "Group Containers" / "group.com.apple.usernoted" / "db2" / "db",
    )


def find_notification_db_path() -> Optional[Path]:
    """Return the path to the macOS Notification Center SQLite DB, or
    None if it can't be found. Non-macOS systems return None immediately."""
    if not sys.platform.startswith("darwin"):
        return None
    try:
        r = subprocess.run(
            ["getconf", "DARWIN_USER_DIR"], capture_output=True, text=True, timeout=2,
        )
        base = Path(r.stdout.strip()) if r.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        base = None
    if base is None:
        # Fallback to ~/Library/Application Support (matches the typical
        # layout for getconf DARWIN_USER_DIR on macOS).
        base = Path.home() / "Library" / "Application Support"
    for rel in _CANDIDATE_RELATIVE_PATHS:
        p = base / rel
        if p.exists():
            return p
    for p in _candidate_absolute_paths(Path.home()):
        if p.exists():
            return p
    return None


# ── DB record parsing ─────────────────────────────────────────────────


def parse_notification_record(
    raw_data: bytes,
    delivered_date: float | None = None,
) -> dict | None:
    """Parse the `data` BLOB (a binary plist) into a friendly dict.

    Returns ``None`` if the plist is malformed. Recognized keys (the
    ones we care about for routing + display):
      - ``app``: app ID (e.g. "com.apple.MobileSMS"). Used for routing.
      - ``req.titl``: title.
      - ``req.body``: body.
    """
    try:
        data: dict[str, Any] = plistlib.loads(raw_data)
    except Exception as e:
        logger.debug(f"parse_notification_record: plistlib error: {e}")
        return None
    req = data.get("req", {}) or {}
    return {
        "app": str(data.get("app", "")).lower(),
        "title": str(req.get("titl", "") or ""),
        "body": str(req.get("body", "") or ""),
        "delivered_date": delivered_date,
    }


# ── Per-app routing table ──────────────────────────────────────────────


# Default mapping: macOS bundle-ID / app-name substrings → Divoom app
# type. Substring match is case-insensitive. The first match wins.
# Users can override by writing a JSON file at
# ``~/.config/divoom-control/notification_routing.json`` (the format
# mirrors DEFAULT_ROUTING: a list of [substring, app_type] pairs).

# Routing (app→type rules + MacAppRouter) lives in notification_router.py to
# keep this file under the 500-LOC cap; re-exported here so existing
# `from divoom_client.macos_notifications import MacAppRouter/...` imports work.
from divoom_client.notification_router import (  # noqa: F401,E402
    DEFAULT_ROUTING,
    ROUTING_PATH,
    MacAppRouter,
    load_routing_table,
    save_routing_table,
    _validate_rules,
    _VALID_APP_TYPES,
)


# ── Monitor ───────────────────────────────────────────────────────────


# A Sink is anything that takes (app_type, title, body) — the GUI's
# notification bridge, a printer, a logger, a test spy, …
Sink = Callable[[int, str, str], None]


class MacNotificationMonitor:
    """Poll the macOS Notification Center DB and forward new records
    to a ``Sink`` after routing.

    Lifecycle:
        monitor = MacNotificationMonitor(...)
        monitor.start(sink=my_sink)   # spawns daemon thread
        ...
        monitor.stop()                # joins thread

    Thread-safety: only the polling thread reads the DB. The sink is
    called on the polling thread; the GUI bridge inside the sink is
    responsible for its own thread-safety (``gui_api.send_notification``
    already uses an asyncio lock).
    """

    def __init__(
        self,
        router: Optional[MacAppRouter] = None,
        poll_interval: float = 1.0,
        db_path: Optional[Path] = None,
        routing_path: Optional[Path] = None,
        _time_source: Callable[[], float] = time.time,
        _sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if router is not None:
            self._router = router
        elif routing_path is not None:
            # Explicit path → load it (even if it's a default-equal file).
            self._router = MacAppRouter.from_file(routing_path)
        else:
            # Default: load from the user-customized table; if it's
            # missing or corrupt, fall back to the built-in defaults.
            self._router = MacAppRouter.from_file()
        self._interval = float(poll_interval)
        self._db_path = Path(db_path) if db_path is not None else find_notification_db_path()
        self._time = _time_source
        self._sleep = _sleep
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_seen: float = 0.0
        # Counters useful for tests + observability.
        self.records_seen: int = 0
        self.records_routed: int = 0
        self.records_dropped: int = 0
        # Health: a SUSTAINED DB-read failure (FDA revoked, DB relocated by an OS
        # update, file rotated out from under us) used to be swallowed as "no new
        # rows" — the thread stayed alive so status kept reporting ACTIVE while the
        # feature was silently deaf. Track a failure streak so the service can
        # surface STATE_ERROR instead of lying.
        self._db_error_streak: int = 0
        self._last_db_error: Optional[str] = None

    _DB_ERROR_HEALTH_THRESHOLD = 5  # consecutive failed polls (~5s at 1s interval)

    @property
    def health_error(self) -> Optional[str]:
        """The last DB-read error once it has persisted past the threshold (i.e.
        the monitor is alive but not actually reading); None while healthy."""
        if self._db_error_streak >= self._DB_ERROR_HEALTH_THRESHOLD:
            return self._last_db_error
        return None

    @property
    def db_path(self) -> Optional[Path]:
        return self._db_path

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, sink: Sink) -> None:
        """Spawn the polling thread. Idempotent — calling twice is a no-op."""
        if self.is_running:
            return
        if self._db_path is None or not self._db_path.exists():
            raise FileNotFoundError(
                "macOS Notification Center DB not found; "
                "notifications are unavailable on this system."
            )
        # R42 §2: on modern macOS the store sits behind TCC — the path exists
        # but opening it requires Full Disk Access. Probe now so the error is
        # actionable instead of a generic poll failure later.
        try:
            with sqlite3.connect(str(self._db_path), timeout=0.5) as conn:
                conn.execute("SELECT 1")
        except sqlite3.OperationalError as e:
            raise PermissionError(
                "macOS Notification Center DB exists but can't be opened "
                f"({e}). Grant FULL DISK ACCESS to the Python runtime "
                "(System Settings → Privacy & Security → Full Disk Access → "
                "add python3 / the Divoom app) and restart the daemon."
            ) from e
        self._stop.clear()
        self._last_seen = self._initial_max_delivered_date()
        self._thread = threading.Thread(
            target=self._run, args=(sink,), daemon=True, name="MacNotificationMonitor"
        )
        self._thread.start()
        logger.info(f"MacNotificationMonitor started; db={self._db_path}")

    def stop(self) -> None:
        """Stop the polling thread. Joins within ~poll_interval seconds."""
        if not self.is_running:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval * 2 + 1.0)
        self._thread = None
        logger.info("MacNotificationMonitor stopped")

    # ── Internals ──────────────────────────────────────────────────────

    def _initial_max_delivered_date(self) -> float:
        """Look at the DB once at startup to seed ``_last_seen`` with
        the latest ``delivered_date`` so we don't replay history."""
        try:
            with sqlite3.connect(str(self._db_path), timeout=0.5) as conn:
                row = conn.execute(
                    "SELECT MAX(delivered_date) FROM record"
                ).fetchone()
            if row and row[0] is not None:
                return float(row[0])
        except sqlite3.Error as e:
            logger.debug(f"_initial_max_delivered_date: {e}")
        return 0.0

    def _fetch_new(self) -> list[tuple[bytes, float]]:
        try:
            with sqlite3.connect(str(self._db_path), timeout=0.5) as conn:
                rows = conn.execute(
                    "SELECT data, delivered_date FROM record "
                    "WHERE delivered_date > ? ORDER BY delivered_date ASC",
                    (self._last_seen,),
                ).fetchall()
        except sqlite3.Error as e:
            self._db_error_streak += 1
            self._last_db_error = str(e)
            # First failure of a streak is worth a warning (a transient lock is
            # fine; a sustained failure flips health_error → STATE_ERROR).
            logger.log(logging.WARNING if self._db_error_streak == 1 else logging.DEBUG,
                       "_fetch_new: sqlite error (streak %d): %s", self._db_error_streak, e)
            return []
        self._db_error_streak = 0
        self._last_db_error = None
        return [(bytes(r[0]), float(r[1])) for r in rows]

    def _run(self, sink: Sink) -> None:
        while not self._stop.is_set():
            try:
                for raw, delivered in self._fetch_new():
                    if delivered > self._last_seen:
                        self._last_seen = delivered
                    self.records_seen += 1
                    parsed = parse_notification_record(raw, delivered)
                    if parsed is None:
                        self.records_dropped += 1
                        continue
                    app_type = self._router.route(parsed["app"])
                    if app_type is None:
                        self.records_dropped += 1
                        continue
                    try:
                        sink(app_type, parsed["title"], parsed["body"])
                        self.records_routed += 1
                    except Exception as e:
                        logger.exception(f"sink raised: {e}")
                        self.records_dropped += 1
            except Exception as e:
                logger.exception(f"monitor loop error: {e}")
            # Sleep in small chunks so stop() returns quickly.
            slept = 0.0
            while slept < self._interval and not self._stop.is_set():
                self._sleep(min(0.1, self._interval - slept))
                slept += 0.1


# ── CLI integration (for manual testing) ───────────────────────────────


def _print_sink(app_type: int, title: str, body: str) -> None:
    print(f"  → app_type={app_type}  title={title!r}  body={body!r}")


def _cli() -> int:
    import argparse
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    p.add_argument("--interval", type=float, default=1.0)
    p.add_argument("--duration", type=float, default=0.0,
                   help="Stop after N seconds (0 = forever).")
    args = p.parse_args()
    try:
        m = MacNotificationMonitor(poll_interval=args.interval)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"Watching {m.db_path} every {args.interval}s. Ctrl-C to stop.")
    m.start(sink=_print_sink)
    try:
        if args.duration > 0:
            time.sleep(args.duration)
            m.stop()
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        m.stop()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_cli())
