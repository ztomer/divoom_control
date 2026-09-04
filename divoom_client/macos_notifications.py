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
import subprocess
import sys
from pathlib import Path
from typing import Optional


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


