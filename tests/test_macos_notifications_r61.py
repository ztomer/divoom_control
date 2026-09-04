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
    find_notification_db_path,
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












# ── `_run` loop branches ────────────────────────────────────────────────










# ── CLI helpers ──────────────────────────────────────────────────────────






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




