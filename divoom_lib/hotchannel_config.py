"""Shared persistence for the Monthly Best "hot channel" feature.

Both the desktop GUI and the headless daemon read/write this single config so
that the user's schedule survives across sessions and drives automatic,
headless syncs.

Stored at ``~/.config/divoom-control/hotchannel.json``:

    {
      "enabled": false,   # whether the scheduled daemon should run
      "interval": 86400   # seconds between automatic sync cycles
    }

WHAT IS NOT HERE ANY MORE: the devices the loop pushes to. They used to be
here (``targets`` and ``device_galleries``), in a list nobody filled — so the
loop was enabled, scheduled, and pushing nothing at all. The devices are the
app's settings now (``config.ini``'s ``[gallery]`` table); see
``divoom_lib/settings_devices.py`` and the daemon's
``divoomd/src/settings_devices.rs``. One home for the fact, so there is no
second list to fill and no second list to drift.

A file written by an older build still carries the old keys. They are
REPORTED (a warning, so the owner learns the file is stale) and IGNORED, and
the next save drops them — the migration is the save, not a silent rewrite.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("divoom_gui")

CONFIG_DIR = Path.home() / ".config" / "divoom-control"
CONFIG_PATH = CONFIG_DIR / "hotchannel.json"

# The default cadence: a DAY.
#
# WHY: the "monthly best" content is refreshed almost daily — the owner says
# so, and the dates on the files themselves bear it out. The CATEGORY is
# called "monthly best" because that is the CLOUD's name for it, not because
# the content turns over monthly. A weekly push leaves the device up to a
# week behind, so the default is 86400 seconds. The owner can still choose
# another interval in the Routines card.
DEFAULT_INTERVAL = 86400

DEFAULTS = {
    "enabled": False,
    "interval": DEFAULT_INTERVAL,
}

# The keys an older build wrote here that no longer mean anything. They are
# read (an old file must not break anything), reported, and ignored.
LEGACY_KEYS = ("targets", "device_galleries", "classify")

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
                stale = [k for k in LEGACY_KEYS if k in data]
                if stale:
                    logger.warning(
                        "%s still carries %s — ignored. The hot channel's devices "
                        "are the app's settings (config.ini [gallery]); a stale list "
                        "must not override them. Saving the schedule drops them.",
                        path,
                        ", ".join(stale),
                    )
        except (OSError, ValueError):
            pass
    return _normalize(cfg)


def save_config(cfg: dict) -> bool:
    """Persist a (partial) config, merged over the current stored values.

    Only the loop's own keys are written, so saving MIGRATES a file that
    still carries the old device list: the stale keys go away because the
    file is rewritten, not because they were read.
    """
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


def _normalize(cfg: dict) -> dict:
    """Coerce/validate fields so callers and the daemon get safe values.

    Only the loop's own keys survive: a key this build does not know is
    dropped rather than written back, which is what migrates a stale file.
    """
    out = {
        "enabled": bool(cfg.get("enabled", DEFAULTS["enabled"])),
        "interval": DEFAULTS["interval"],
    }
    try:
        out["interval"] = max(MIN_INTERVAL, min(MAX_INTERVAL, int(cfg.get("interval", DEFAULT_INTERVAL))))
    except (TypeError, ValueError):
        out["interval"] = DEFAULTS["interval"]
    return out
