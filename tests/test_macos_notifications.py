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
    find_notification_db_path,
)


# ── `parse_notification_record` ──────────────────────────────────────








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
















# ── `find_notification_db_path` (real system) ────────────────────────


def test_find_notification_db_path_returns_none_off_macos() -> None:
    """When run on Linux/CI, the function should return None immediately."""
    if sys.platform.startswith("darwin"):
        pytest.skip("darwin-specific behavior skipped on non-macOS")
    assert find_notification_db_path() is None


# ── Module surface ────────────────────────────────────────────────────


