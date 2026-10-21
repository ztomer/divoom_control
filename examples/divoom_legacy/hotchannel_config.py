"""The RETIRED monthly-best daemon's own hot-channel config reader.

The Python monthly-best daemon was retired on 2026-09-14: it lives in
``examples/divoom_legacy/monthly_best_daemon.py`` now, and the live path is
the Rust daemon's task (``divoomd/src/monthly_best.rs``).

The live config module moved on. ``hotchannel.json`` now carries only the
loop's OWN keys -- whether it runs and how often -- and the devices it pushes
to live in the app's settings (``config.ini``'s ``[gallery]`` table). So the
retired daemon reads the retired shape with a reader of its OWN, here: a
frozen artifact that depends on a module that has moved on is a broken
artifact, and this is what that breakage looked like.

Frozen with the artifact it serves. Nothing in the live path imports it.
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

# Guardrails (the retired file's own).
MIN_INTERVAL = 60
MAX_INTERVAL = 2592000


def _config_path() -> Path:
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


def get_device_classify(cfg: dict, address: str) -> int:
    """Return the per-device gallery style, falling back to global classify."""
    per_device = cfg.get("device_galleries") or {}
    if address in per_device:
        try:
            return int(per_device[address])
        except (TypeError, ValueError):
            pass
    return cfg.get("classify", DEFAULTS["classify"])


def _normalize(cfg: dict) -> dict:
    """Coerce/validate fields so callers get safe values."""
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
    seen, clean = set(), []
    for t in targets:
        t = str(t).strip()
        if t and t not in seen:
            seen.add(t)
            clean.append(t)
    out["targets"] = clean
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
