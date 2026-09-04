"""Per-device HOT-channel last-checked state (R53).

Records when each device last ran a device HOT-channel update and the outcome,
so the UI can show "Last checked <when>" instead of an undated "up to date"
verdict. Stored at ``~/.config/divoom-control/hot_update_state.json``:

    {
      "AA:BB:CC:DD:EE:FF": {
        "checked_at": 1720000000.0,   # epoch seconds of the last check
        "served": 0,                  # files pushed this check
        "manifest": 12,               # files the manifest advertised
        "downloaded": 12,             # files successfully fetched from the CDN
        "confirmed": 0                # files the device positively confirmed
      }
    }

This is the manual "Update Hot Channel" button path
(:mod:`divoom_lib.tools.hot_update`) and is a DIFFERENT feature from
:mod:`divoom_lib.hotchannel_config` (the Monthly Best gallery scheduler).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "divoom-control"
STATE_PATH = CONFIG_DIR / "hot_update_state.json"


def _state_path() -> Path:
    # Honor an override (tests) without importing test code.
    override = os.environ.get("DIVOOM_HOT_STATE")
    return Path(override) if override else STATE_PATH


def load_state() -> dict:
    """Return the whole ``{address: entry}`` map (never raises)."""
    path = _state_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
    return {}


def get_check(address: str) -> dict:
    """Return the stored last-check entry for ``address`` (or ``{}``)."""
    if not address:
        return {}
    entry = load_state().get(str(address))
    return entry if isinstance(entry, dict) else {}


def record_check(address: str, summary: dict, *, checked_at: float | None = None) -> dict:
    """Persist the outcome of a hot-channel check for ``address`` and return the
    stored entry. ``summary`` is the :meth:`HotUpdate.update` result dict
    (``served``/``manifest``/``downloaded``/``confirmed``). ``served`` may arrive
    as a list (raw result) or an int (already counted)."""
    if not address:
        return {}
    address = str(address)
    summary = summary if isinstance(summary, dict) else {}
    served = summary.get("served")
    if isinstance(served, list):
        served_n = len(served)
    else:
        try:
            served_n = int(served or 0)
        except (TypeError, ValueError):
            served_n = 0

    def _int(key: str) -> int:
        try:
            return int(summary.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    entry = {
        "checked_at": float(checked_at if checked_at is not None else time.time()),
        "served": served_n,
        "manifest": _int("manifest"),
        "downloaded": _int("downloaded"),
        "confirmed": _int("confirmed"),
    }
    state = load_state()
    state[address] = entry
    try:
        from divoom_lib.utils.atomic_io import atomic_write_text
        _state_path().parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(_state_path(), json.dumps(state, indent=2))
    except OSError:
        pass
    return entry
