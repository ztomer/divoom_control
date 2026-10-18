"""P2.7: a daemon the GUI respawns is asked for the GUI's panels back.

Traced 2026-10-18 (Pixoo-1, v0.41.2): with the GUI running, each SIGTERM of the
daemon had ``reconnect_daemon`` spawn a new one and nothing else -- no
``connect`` for 60 s, ``device_status`` ``devices: []`` -- because a daemon
starts with an empty fleet and the only thing that knew which panels to link,
the GUI, never asked. The GUI owns the answer (it linked them), so its respawn
path asks.

"Respawned" is judged by the daemon's IDENTITY, not by whether the socket
answered a moment ago: ``ensure_daemon`` also replaces a live daemon whose
version is stale, and the watchdog (P2.6) exits a wedged one, so the GUI
cannot know from its own call which happened. A daemon's start time
(now - ``get_status.uptime_s``) names the instance; a different one means
every panel the old one held is gone.

Only panels the NEW daemon does not already hold are linked, one at a time
(BLE refuses a second concurrent connect), on a background thread so the
banner's reconnect returns at once; the daemon's own status events repaint
each dot as its link comes back.
"""
from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger("divoom_gui")

# get_status reports whole seconds; two readings of one instance can differ by
# up to ~1 s of rounding plus the call's own latency.
SAME_INSTANCE_TOLERANCE_S = 2.0


def remember(host, address: str) -> None:
    """Record a panel this GUI linked, in link order, once."""
    held = host.__dict__.setdefault("_held_panels", [])
    if address not in held:
        held.append(address)


def _daemon_started_at(client) -> float | None:
    try:
        reply = client.send_command("get_status")
    except Exception as e:  # a daemon that cannot say is not a new one
        logger.debug("relink: get_status failed: %s", e)
        return None
    uptime = reply.get("uptime_s") if isinstance(reply, dict) else None
    if not isinstance(uptime, (int, float)):
        return None
    return time.time() - float(uptime)


def after_ensure(host, client) -> bool:
    """Called with the client ``reconnect_daemon`` just ensured. Starts the
    relink when this is a different daemon from the last one seen and the GUI
    holds panels; returns whether it did."""
    started = _daemon_started_at(client)
    previous = host.__dict__.get("_daemon_started_at")
    if started is not None:
        host._daemon_started_at = started
    held = list(host.__dict__.get("_held_panels", []))
    if started is None or previous is None or not held:
        return False
    if abs(started - previous) <= SAME_INSTANCE_TOLERANCE_S:
        return False
    logger.info("Daemon was respawned; relinking %d panel(s): %s",
                len(held), ", ".join(held))
    t = threading.Thread(target=_relink, args=(host, client, held),
                         name="divoom-relink", daemon=True)
    host._relink_thread = t
    t.start()
    return True


def _relink(host, client, held: list[str]) -> None:
    try:
        status = client.device_status()
        have = {d.get("mac") for d in (status.get("devices") or [])
                if isinstance(d, dict) and d.get("connected")}
    except Exception as e:
        logger.warning("relink: device_status failed (%s); linking every held panel", e)
        have = set()
    for address in held:
        if address in have:
            continue
        ok = host._link(client, address)
        logger.info("relink %s: %s", address, "linked" if ok else
                    f"failed ({getattr(host, '_last_connect_error', '')})")
