"""GUI → daemon bridge (R17 P5).

The implementation moved to :mod:`divoom_client.daemon_client` (R28) so the MCP
server and other non-GUI clients can reuse the proxy without a backwards
``divoom_lib`` → ``divoom_gui`` dependency. This module re-exports it unchanged
so existing GUI call-sites and tests (`from divoom_gui.daemon_bridge import ...`)
keep working.
"""
from __future__ import annotations

from divoom_client.daemon_client import (  # noqa: F401
    DaemonClient,
    DaemonDeviceProxy,
    daemon_alive,
    ensure_daemon,
    spawn_daemon,
    logger,
)

__all__ = [
    "DaemonClient",
    "DaemonDeviceProxy",
    "daemon_alive",
    "ensure_daemon",
    "spawn_daemon",
    "logger",
]
