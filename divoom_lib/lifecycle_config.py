"""R40 §9 — shared "keep daemon (menu bar) alive when quitting the dashboard"
setting, plus the small decision helpers that make the lifecycle event-driven.

The flag lives in ``~/.config/divoom-control/config.ini`` under ``[gui]`` so the
GUI, the menubar agent, and tests all read the same source of truth. Default is
**False**: the dashboard, the menubar agent, and the daemon share one lifecycle
(quitting any of them brings the others down). When **True**, they're
independent.
"""
from __future__ import annotations

import configparser
import logging
from pathlib import Path

logger = logging.getLogger("divoom_lib.lifecycle")

CONFIG_FILE = Path.home() / ".config" / "divoom-control" / "config.ini"
SECTION = "gui"
KEY = "keep_daemon_alive"
DEFAULT = False

# Also terminate the native menu-bar agent when the dashboard quits (shared
# lifecycle only). Default True — a plain quit is spotless. The native agent is
# spawned detached and does NOT self-terminate on the daemon's shutdown
# broadcast, so without this it orphans to launchd (a stale tray icon).
KEY_QUIT_MENUBAR = "quit_menubar_on_exit"
DEFAULT_QUIT_MENUBAR = True


def get_keep_daemon_alive(path: Path = CONFIG_FILE) -> bool:
    """Read the flag (default False). Never raises."""
    try:
        if path.exists():
            cfg = configparser.ConfigParser()
            cfg.read(path)
            return cfg.getboolean(SECTION, KEY, fallback=DEFAULT)
    except (configparser.Error, OSError, ValueError) as e:
        logger.warning("keep_daemon_alive read failed (%s); default %s", e, DEFAULT)
    return DEFAULT


def set_keep_daemon_alive(value: bool, path: Path = CONFIG_FILE) -> bool:
    """Persist the flag. Returns True on success."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        cfg = configparser.ConfigParser()
        if path.exists():
            cfg.read(path)
        if not cfg.has_section(SECTION):
            cfg.add_section(SECTION)
        cfg.set(SECTION, KEY, "true" if value else "false")
        from divoom_lib.utils.atomic_io import atomic_write_config
        atomic_write_config(path, cfg)
        return True
    except (configparser.Error, OSError) as e:
        logger.warning("keep_daemon_alive write failed (%s)", e)
        return False


def get_quit_menubar_on_exit(path: Path = CONFIG_FILE) -> bool:
    """Read the 'quit the menu-bar agent when the dashboard exits' flag
    (default True). Never raises."""
    try:
        if path.exists():
            cfg = configparser.ConfigParser()
            cfg.read(path)
            return cfg.getboolean(SECTION, KEY_QUIT_MENUBAR, fallback=DEFAULT_QUIT_MENUBAR)
    except (configparser.Error, OSError, ValueError) as e:
        logger.warning("quit_menubar_on_exit read failed (%s); default %s", e, DEFAULT_QUIT_MENUBAR)
    return DEFAULT_QUIT_MENUBAR


def set_quit_menubar_on_exit(value: bool, path: Path = CONFIG_FILE) -> bool:
    """Persist the flag. Returns True on success."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        cfg = configparser.ConfigParser()
        if path.exists():
            cfg.read(path)
        if not cfg.has_section(SECTION):
            cfg.add_section(SECTION)
        cfg.set(SECTION, KEY_QUIT_MENUBAR, "true" if value else "false")
        from divoom_lib.utils.atomic_io import atomic_write_config
        atomic_write_config(path, cfg)
        return True
    except (configparser.Error, OSError) as e:
        logger.warning("quit_menubar_on_exit write failed (%s)", e)
        return False


# ── pure decision helpers (no I/O — trivially testable) ──────────────────────

def should_quit_menubar_on_exit(keep_alive: bool, quit_menubar: bool) -> bool:
    """When the dashboard exits: terminate the native menu-bar agent? Only when
    lifecycles are shared (keep-alive OFF) AND the user hasn't opted to keep the
    tray icon. Keep-alive ON means independent lifecycles → never kill it."""
    return (not keep_alive) and quit_menubar


def should_follow_daemon_shutdown(keep_alive: bool) -> bool:
    """A subscriber that received the daemon's ``shutdown`` event: should it
    terminate too? Only when lifecycles are shared (NOT keep-alive)."""
    return not keep_alive


def should_stop_daemon_on_dashboard_quit(keep_alive: bool) -> bool:
    """When the dashboard window closes: should it ask the daemon to shut down
    (which also brings the menubar down)? Only when lifecycles are shared."""
    return not keep_alive


def should_stop_daemon_on_menubar_quit(keep_alive: bool) -> bool:
    """Menubar 'Quit Divoom': stop the daemon (→ dashboard + menubar close) when
    shared; when keep-alive, just exit the menubar and leave the daemon running."""
    return not keep_alive
