"""Shared persistence for the Monthly Best "hot channel" feature.

Both the desktop GUI and the headless daemon read/write this single config so
that the user's selected target devices and schedule survive across sessions and
drive automatic, headless syncs (request items 4.c / 4.d).

Stored at ``~/.config/divoom-control/hotchannel.json``:

    {
      "enabled": false,        # whether the scheduled daemon should run
      "interval": 3600,        # seconds between automatic sync cycles
      "classify": 18,          # Divoom gallery classification id (18 = Recommend)
      "targets": ["AA:BB:CC:DD:EE:FF", "LAN:192.168.1.50"],  # device addresses
      "device_galleries": {"AA:BB:CC:DD:EE:FF": 9, "LAN:192.168.1.50": 18}  # per-device gallery style
    }
"""

from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "divoom-control"
CONFIG_PATH = CONFIG_DIR / "hotchannel.json"

DEFAULTS = {
    "enabled": False,
    "interval": 3600,
    "classify": 18,
    "targets": [],
    "device_galleries": {},
}

# Guardrails.
MIN_INTERVAL = 60  # never hammer the cloud/device faster than once a minute
# R15 §4: cap the auto-sync interval at 30 days so a typo (e.g. an
# extra zero) doesn't disable syncing for years. The UI only offers
# values up to 30d; the clamp is a defensive belt for the JSON file
# (the user can still set anything manually in the file, but the
# daemon will read-back the clamped value).
MAX_INTERVAL = 2592000  # 30 days


def _config_path() -> Path:
    # Honor an override (used by tests) without importing test code.
    override = os.environ.get("DIVOOM_HOTCHANNEL_CONFIG")
    return Path(override) if override else CONFIG_PATH


def load_config() -> dict:
    """Return the stored config merged over defaults (never raises)."""
    cfg = dict(DEFAULTS)
    path = _config_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update({k: data[k] for k in DEFAULTS if k in data})
        except (OSError, ValueError):
            pass
    return _normalize(cfg)


def save_config(cfg: dict) -> bool:
    """Persist a (partial) config, merged over the current stored values."""
    merged = load_config()
    for k in DEFAULTS:
        if k in cfg:
            merged[k] = cfg[k]
    merged = _normalize(merged)
    try:
        from divoom_lib.utils.atomic_io import atomic_write_text
        atomic_write_text(_config_path(), json.dumps(merged, indent=2))
        return True
    except OSError:
        return False


def set_targets(targets: list[str]) -> bool:
    return save_config({"targets": targets})


def get_targets() -> list[str]:
    return load_config()["targets"]


def get_device_classify(cfg: dict, address: str) -> int:
    """Return the per-device gallery style, falling back to global classify."""
    per_device = cfg.get("device_galleries") or {}
    if address in per_device:
        try:
            return int(per_device[address])
        except (TypeError, ValueError):
            pass
    return cfg.get("classify", DEFAULTS["classify"])


def set_device_galleries(galleries: dict) -> bool:
    """Persist per-device gallery style overrides."""
    return save_config({"device_galleries": galleries})


def _normalize(cfg: dict) -> dict:
    """Coerce/validate fields so callers and the daemon get safe values."""
    out = dict(DEFAULTS)
    out.update(cfg)
    out["enabled"] = bool(out.get("enabled", False))
    try:
        out["interval"] = max(MIN_INTERVAL, min(MAX_INTERVAL, int(out.get("interval", 3600))))
    except (TypeError, ValueError):
        out["interval"] = DEFAULTS["interval"]
    try:
        out["classify"] = int(out.get("classify", 18))
    except (TypeError, ValueError):
        out["classify"] = DEFAULTS["classify"]
    targets = out.get("targets") or []
    if not isinstance(targets, list):
        targets = []
    # De-dupe, drop blanks, preserve order.
    seen, clean = set(), []
    for t in targets:
        t = str(t).strip()
        if t and t not in seen:
            seen.add(t)
            clean.append(t)
    out["targets"] = clean
    # Per-device gallery styles. Coerce defensively and DROP bad entries: a
    # non-numeric value (hand-edited JSON, or a blank style from the GUI) must
    # not raise here — load_config() calls _normalize() outside its try/except
    # and promises "never raises", and monthly_best_daemon.main() calls
    # load_config() unguarded at startup, so a bare int(v) would crash the
    # headless daemon. Mirrors get_device_classify()'s tolerant coercion.
    dg = out.get("device_galleries") or {}
    if not isinstance(dg, dict):
        dg = {}
    clean_dg: dict = {}
    for k, v in dg.items():
        if not (isinstance(k, str) and k.strip()):
            continue
        try:
            clean_dg[k] = int(v)
        except (TypeError, ValueError):
            continue
    out["device_galleries"] = clean_dg
    return out
