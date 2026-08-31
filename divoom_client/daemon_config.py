"""Daemon configuration — user-tunable knobs in an INI alongside the GUI config.

Lives at ``~/.config/divoom-control/daemon.ini``, next to the GUI's
``config.ini``. On first load a commented default file is written so the knobs
are discoverable. Every default is a NAMED constant here, so there are no magic
numbers sprinkled through the daemon/client code — the call sites read this
config instead.

Divoom BLE discovery is genuinely slow (a full scan can take 30-60s), which is
why the scan defaults are large. The user can always pass a per-scan ``timeout``
from the GUI; these are the fallbacks + the slack the client adds when waiting
for a scan reply.
"""
from __future__ import annotations

import configparser
import logging
from dataclasses import dataclass, fields
from pathlib import Path

logger = logging.getLogger("divoom_client")

CONFIG_DIR = Path.home() / ".config" / "divoom-control"
CONFIG_FILE = CONFIG_DIR / "daemon.ini"
SECTION = "daemon"

# ── named defaults (no magic numbers at the call sites) ──────────────────────
DEFAULT_SCAN_TIMEOUT = 20.0          # seconds to scan when the GUI sends no timeout
DEFAULT_SCAN_LIMIT = 4               # stop after N devices (0 = no limit)
DEFAULT_SCAN_READ_SLACK = 10.0       # client waits scan_timeout + this for the reply
DEFAULT_CLIENT_TIMEOUT = 2.0         # socket read timeout for quick, non-scan commands
DEFAULT_RECONNECT_SCAN_TIMEOUT = 3.0  # short scan used during auto-reconnect
DEFAULT_CONNECT_TIMEOUT = 30.0       # client read timeout for connect/disconnect (BLE is slow)
DEFAULT_SYNC_READ_TIMEOUT = 120.0    # client read timeout for sync_artwork (download + BLE stream)
DEFAULT_HOT_UPDATE_TIMEOUT = 600.0   # client read timeout for hot_update (manifest of ~30 files)
DEFAULT_CLOUD_TIMEOUT = 40.0         # client read timeout for cloud browse (see the ini comment)


@dataclass(frozen=True)
class DaemonConfig:
    """Resolved daemon settings (see module docstring for the why of each)."""
    scan_timeout: float = DEFAULT_SCAN_TIMEOUT
    scan_limit: int = DEFAULT_SCAN_LIMIT
    scan_read_slack: float = DEFAULT_SCAN_READ_SLACK
    client_timeout: float = DEFAULT_CLIENT_TIMEOUT
    reconnect_scan_timeout: float = DEFAULT_RECONNECT_SCAN_TIMEOUT
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    sync_read_timeout: float = DEFAULT_SYNC_READ_TIMEOUT
    hot_update_timeout: float = DEFAULT_HOT_UPDATE_TIMEOUT
    cloud_timeout: float = DEFAULT_CLOUD_TIMEOUT

    def scan_read_timeout(self, scan_timeout: float) -> float:
        """How long a client should wait for a scan reply: the daemon only
        answers AFTER scanning for ``scan_timeout`` seconds, so the read must
        outlast the scan plus connect/serialize overhead."""
        return float(scan_timeout) + self.scan_read_slack


_DEFAULT_FILE = """\
# divoom-control daemon configuration
# Sits alongside the GUI config (config.ini) in this directory. The daemon reads
# it on startup — restart the daemon to apply changes.
#
# Divoom BLE discovery is slow: a full scan can take 30-60s, which is why the
# scan defaults are large. The GUI can still send a per-scan timeout; these are
# the fallbacks used when it doesn't.

[daemon]
# Seconds to scan for devices when the GUI doesn't specify a timeout.
scan_timeout = {scan_timeout}

# Stop scanning once this many devices are found (0 = no limit, full timeout).
scan_limit = {scan_limit}

# Extra seconds a client waits for a scan reply on top of the scan duration
# (the daemon only answers once the scan finishes). Covers connect + serialize.
scan_read_slack = {scan_read_slack}

# Socket read timeout for quick commands (status, brightness, etc.).
client_timeout = {client_timeout}

# Short scan used internally when auto-reconnecting to a known device.
reconnect_scan_timeout = {reconnect_scan_timeout}

# Client read timeout for connect/disconnect. BLE connection setup is slow, so
# this is much larger than client_timeout — otherwise the GUI gives up mid-handshake.
connect_timeout = {connect_timeout}

# Client read timeout for syncing artwork (hot channel / gallery push). The
# daemon downloads the asset and streams it to the device over BLE, which can
# take a minute or more per image — a short read here falsely reports failure.
sync_read_timeout = {sync_read_timeout}

# Client read timeout for the hot-channel update (downloads + serves the
# device's file requests for Divoom's full curated set — can take minutes).
hot_update_timeout = {hot_update_timeout}

# Client read timeout for cloud browse (clock faces, playlists, sleep sounds,
# photo albums, city search). The daemon's own HTTP timeout is 15s and an
# expired token makes it re-authenticate and retry the call, so the worst
# honest case is ~30s. Reading for the 2s client_timeout would abandon a reply
# that was on its way — reporting "nothing found" for a request that succeeded,
# which is the exact failure this whole workstream exists to end.
cloud_timeout = {cloud_timeout}
"""

_cache: DaemonConfig | None = None


def _coerce(field_type, raw, fallback):
    try:
        return field_type(raw)
    except (TypeError, ValueError):
        logger.warning("daemon config: bad value %r; using %r", raw, fallback)
        return fallback


def _write_default(path: Path, defaults: DaemonConfig) -> None:
    try:
        from divoom_lib.utils.atomic_io import atomic_write_text
        atomic_write_text(path, _DEFAULT_FILE.format(**defaults.__dict__))
        logger.info("Wrote default daemon config to %s", path)
    except OSError as e:
        logger.warning("Could not write default daemon config (%s)", e)


def load_daemon_config(path: Path = CONFIG_FILE, *, force: bool = False) -> DaemonConfig:
    """Load (and cache) the daemon config. Writes a commented default file the
    first time it's missing. Never raises — falls back to the named defaults."""
    global _cache
    if _cache is not None and not force:
        return _cache

    defaults = DaemonConfig()
    parser = configparser.ConfigParser()
    try:
        if path.exists():
            parser.read(path)
        else:
            _write_default(path, defaults)
    except (OSError, configparser.Error) as e:
        logger.warning("daemon config read failed (%s); using defaults", e)
        _cache = defaults
        return defaults

    sect = parser[SECTION] if parser.has_section(SECTION) else {}
    values = {}
    for f in fields(DaemonConfig):
        default = getattr(defaults, f.name)
        values[f.name] = _coerce(f.type if callable(f.type) else type(default),
                                 sect.get(f.name), default) if f.name in sect else default
    _cache = DaemonConfig(**values)
    return _cache
