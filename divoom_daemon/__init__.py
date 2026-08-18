"""CLIENT LIBRARY — the Rust `divoomd` binary is the sole shipping daemon.
This package no longer contains a Python daemon SERVER implementation (that
was archived on 2026-07-13 and removed from the tree in R66; recover from git history (archived in 046cdf8, removed in R66 2026-08-17), explicit user
sign-off — see `docs/ROADMAP.md`'s "Native Rust daemon" section for the
parity/soak history that gated it). What remains here is the shared CLIENT
infrastructure every consumer (GUI, menubar, CLI, MCP) uses to talk to
whichever daemon is running, regardless of implementation language:

- `daemon_client.py` — spawn/find/`ensure_daemon()` the Rust binary.
- `daemon_protocol.py` — the NDJSON wire client (`DaemonClient`), framing,
  and shared constants (`DEFAULT_SOCKET_PATH`, event type names).
- `daemon_config.py` — shared `daemon.ini` config loading (scan/connect
  timeouts) used by both the client and, historically, the server.
- `spp_bridge.py` — a Python subprocess bridge for Bluetooth Classic SPP,
  spawned by the Rust daemon (`divoomd/src/spp.rs`) — genuinely still a
  runtime dependency, not just reference code.
- `macos_notifications.py` / `notification_router.py` — notification DB
  path lookup + routing-table load/save, used directly by the GUI's
  Settings page (`divoom_gui/gui_api.py`) independent of which daemon is
  running. The live `MacNotificationMonitor` class in this file is now
  dormant (its only caller, the archived `notification_service.py`, is
  gone) but is left in place since the file is otherwise active.
"""
