"""Wire protocol for the headless daemon (R16) — pure + testable, no AppKit/BLE.

The daemon owns the device + the macOS notification monitor and exposes a Unix
socket. Two interaction modes share one connection grammar:

  * request/response  — client sends one ``{"command","args"}`` line, reads one
    ``{"success",...}`` line, closes.
  * subscribe/stream  — client sends ``{"command":"subscribe"}``; the daemon then
    streams newline-delimited JSON *events* on the held-open connection until the
    client disconnects.

All messages are newline-delimited JSON ("NDJSON"): one compact JSON object per
line. This module has the framing, the message/event shapes, and a thin client.
The server lives in ``divoom_client/daemon.py``; clients are the menubar + the GUI.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import time
from typing import Any, Callable, Iterable

DEFAULT_SOCKET_PATH = "/tmp/divoom.sock"
DEFAULT_TCP_PORT = 9009

# BLE Hardening (daemon-socket): a transient connection refusal — the daemon is
# mid-(re)start, the socket isn't accepting yet, or its listen backlog briefly
# filled — should be retried, not surfaced as a hard "Connection refused" that
# aborts the user's action. Real device traffic retries the *connect* a few
# times over a fraction of a second; liveness probes opt out (retries=0) so
# ensure_daemon's readiness poll stays fast when no daemon is up.
DEFAULT_CONNECT_RETRIES = 4
CONNECT_RETRY_BASE_DELAY = 0.06   # grows 0.06, 0.12, 0.24, 0.48 (~0.9s worst case)
CONNECT_RETRY_MAX_DELAY = 0.5

# Cap the client's reply buffer too — a buggy/hostile daemon shouldn't be able
# to OOM the GUI by never sending a newline. Matches the server's frame cap.
MAX_REPLY_BYTES = 16 * 1024 * 1024

# Env overrides so any DaemonClient (incl. the GUI) can target a remote daemon
# instead of the local Unix socket.
ENV_HOST = "DIVOOM_DAEMON_HOST"
ENV_PORT = "DIVOOM_DAEMON_PORT"
ENV_TOKEN = "DIVOOM_DAEMON_TOKEN"

# Event types streamed to subscribers.
EVENT_STATUS = "status"
EVENT_NOTIFICATION = "notification"
EVENT_SHUTDOWN = "shutdown"   # R40 §9: daemon is stopping — subscribers may follow it down

SUBSCRIBE_COMMAND = "subscribe"


# ── framing ─────────────────────────────────────────────────────────────
def encode_message(obj: dict) -> bytes:
    """One NDJSON line (compact JSON + '\\n')."""
    return (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")


def iter_messages(buffer: bytes) -> tuple[list[dict], bytes]:
    """Split a byte buffer into complete JSON messages + the trailing remainder.

    Returns ``(messages, remainder)``. Blank lines are skipped; a malformed line
    is skipped (not raised) so one bad frame can't wedge the stream.
    """
    messages: list[dict] = []
    *lines, remainder = buffer.split(b"\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            messages.append(json.loads(line.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            continue
    return messages, remainder


# ── message/event constructors ──────────────────────────────────────────
def make_request(command: str, args: dict | None = None,
                 token: str | None = None) -> dict:
    req: dict = {"command": command, "args": args or {}}
    if token:
        req["token"] = token
    return req


def make_status_event(state: str, counters: dict | None = None, error: str | None = None) -> dict:
    ev = {"type": EVENT_STATUS, "state": state, "counters": counters or {}}
    if error:
        ev["error"] = error
    return ev


def make_notification_event(app_type: int, title: str, body: str, routed: bool) -> dict:
    return {
        "type": EVENT_NOTIFICATION,
        "app_type": int(app_type),
        "title": title,
        "body": body,
        "routed": bool(routed),
    }


# ── client ──────────────────────────────────────────────────────────────
class DaemonClient:
    """Thin Unix-socket client. Used by the menubar + GUI to talk to the daemon.

    Never raises on a missing/closed daemon — `send_command` returns an error
    dict and `subscribe` returns cleanly. The daemon being absent is a normal
    state (it may not be launched yet).
    """

    def __init__(self, socket_path: str = DEFAULT_SOCKET_PATH,
                 timeout: float | None = None,
                 *, host: str | None = None, port: int | None = None,
                 token: str | None = None):
        from divoom_client.daemon_config import load_daemon_config
        self.socket_path = socket_path
        # Default the quick-command read timeout from the daemon config so the
        # "2 seconds" lives in one place (daemon.ini) rather than here.
        self.timeout = timeout if timeout is not None else load_daemon_config().client_timeout
        self.host = host
        self.port = port
        self.token = token

    @classmethod
    def from_env(cls, socket_path: str = DEFAULT_SOCKET_PATH,
                 timeout: float | None = None) -> "DaemonClient":
        """Build a client from env: if DIVOOM_DAEMON_HOST is set, target that
        remote daemon over TCP (with DIVOOM_DAEMON_TOKEN); else the local Unix
        socket."""
        host = os.environ.get(ENV_HOST) or None
        port = int(os.environ.get(ENV_PORT, DEFAULT_TCP_PORT)) if host else None
        token = os.environ.get(ENV_TOKEN) or None
        return cls(socket_path, timeout, host=host, port=port, token=token)

    @property
    def is_remote(self) -> bool:
        """True when this client talks to a daemon over TCP (no shared
        filesystem — image args must be shipped as blobs, not paths)."""
        return bool(self.host and self.port)

    def _connect(self) -> socket.socket:
        """Open a connection to the daemon (TCP if host/port set, else Unix)."""
        if self.is_remote:
            s = socket.create_connection((self.host, self.port), timeout=self.timeout)
        else:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(self.timeout)
            s.connect(self.socket_path)
        return s

    def send_command(self, command: str, args: dict | None = None,
                     *, read_timeout: float | None = None,
                     connect_retries: int = DEFAULT_CONNECT_RETRIES) -> dict:
        """One-shot request/response. Returns the daemon's reply dict, or
        ``{"success": False, "error": ...}`` if the daemon isn't reachable.

        ``read_timeout`` overrides the socket read timeout for this call — needed
        for long-running commands (e.g. ``scan``, whose reply only arrives after
        the full BLE scan duration, which usually exceeds the default timeout).

        ``connect_retries`` — how many extra times to retry *establishing* the
        connection on a transient refusal (daemon mid-(re)start). Only the
        connect is retried; once connected, a read error/timeout is returned as
        is (it may be a legit slow op, not a connection problem). Liveness
        probes pass 0 to fast-fail."""
        last_err: Exception | None = None
        for attempt in range(connect_retries + 1):
            try:
                s = self._connect()
            except (ConnectionRefusedError, FileNotFoundError,
                    ConnectionResetError, ConnectionAbortedError, BlockingIOError) as e:
                # Transient: socket not accepting yet / daemon restarting. Retry.
                last_err = e
                if attempt < connect_retries:
                    delay = min(CONNECT_RETRY_MAX_DELAY,
                                CONNECT_RETRY_BASE_DELAY * (2 ** attempt))
                    time.sleep(delay)
                    continue
                return {"success": False, "error": str(e)}
            except (OSError, ValueError) as e:
                # Non-transient connect failure (bad address, perms, …) — no retry.
                return {"success": False, "error": str(e)}

            try:
                with s:
                    s.settimeout(read_timeout if read_timeout is not None else self.timeout)
                    s.sendall(encode_message(make_request(command, args, self.token)))
                    buf = b""
                    while b"\n" not in buf:
                        chunk = s.recv(4096)
                        if not chunk:
                            break
                        buf += chunk
                        if len(buf) > MAX_REPLY_BYTES:
                            return {"success": False, "error": "reply exceeds max size"}
                    msgs, _ = iter_messages(buf)
                    return msgs[0] if msgs else {"success": False, "error": "no reply"}
            except (OSError, ValueError) as e:
                return {"success": False, "error": str(e)}
        return {"success": False,
                "error": str(last_err) if last_err else "daemon unreachable"}

    def device_call(self, method: str, args: list | None = None,
                    kwargs: dict | None = None, *, target: str = "device",
                    blobs: dict[int, bytes] | None = None,
                    token: str | None = None) -> dict:
        """Proxy a device method through the daemon (R17 P5): the daemon owns the
        BLE connection and runs ``divoom.<method>(*args, **kwargs)``. ``target``
        selects the single device ("device") or the daemon-owned wall ("wall").

        ``blobs`` maps an arg index → raw bytes; the daemon materializes each to
        a temp file and substitutes that arg with the path. This is how a remote
        client ships an image over the wire (the GUI and daemon don't share a
        filesystem when the daemon is on another host).

        ``token`` — when set, the call runs in exclusive mode (only items with
        this token are dispatched until ``exclusive_end`` is called). Multiple
        calls with the same token form an atomic multi-phase sequence.

        Returns the daemon reply ``{"success", "result"|"error"}``."""
        payload: dict = {
            "method": method, "args": args or [], "kwargs": kwargs or {},
            "target": target,
        }
        if token:
            payload["token"] = token
        if blobs:
            payload["blobs"] = {
                str(i): base64.b64encode(b).decode("ascii") for i, b in blobs.items()
            }
        # R42 §6: device methods can be SLOW — a wall show_image streams 0x8B
        # to every wall device sequentially (10-30s+). The 2s quick-command
        # timeout abandoned those calls mid-stream ("images are not pushed").
        # A long read timeout is safe: it only applies while a live daemon is
        # processing; a dead daemon still fails fast at connect.
        from divoom_client.daemon_config import load_daemon_config
        return self.send_command("device_call", payload,
                                 read_timeout=load_daemon_config().sync_read_timeout)

    def exclusive_start(self, token: str) -> dict:
        """Begin an exclusive-mode session on the daemon. Only ``device_call``
        items whose ``token`` matches ``token`` will be dispatched until
        ``exclusive_end`` is called. Returns the daemon reply.

        Uses the long sync read timeout, not the 2s default: the daemon-side
        handler stops live jobs then ENQUEUES acquire behind any in-flight device
        op (a wall 0x8B push runs 10-30s+). At 2s the client timed out while the
        daemon went on to acquire → orphaned token + a spurious failure to the GUI,
        wedging the device until the 30s G3 idle release."""
        from divoom_client.daemon_config import load_daemon_config
        return self.send_command("exclusive_start", {"token": token},
                                 read_timeout=load_daemon_config().sync_read_timeout)

    def exclusive_end(self, token: str) -> dict:
        """End the exclusive-mode session for ``token``. Returns the daemon reply."""
        from divoom_client.daemon_config import load_daemon_config
        return self.send_command("exclusive_end", {"token": token},
                                 read_timeout=load_daemon_config().sync_read_timeout)

    # ── notifications (the daemon owns the single macOS monitor) ──────────
    def start_notifications(self) -> dict:
        """Start the daemon's macOS notification monitor. Returns
        ``{success, state, counters, error?, unsupported?}``. The daemon is the
        single owner of the monitor — the GUI must NOT poll the DB itself."""
        return self.send_command("start_notifications")

    def stop_notifications(self) -> dict:
        """Stop the daemon's notification monitor. Returns ``{success, state, ...}``."""
        return self.send_command("stop_notifications")

    def notification_status(self) -> dict:
        """Current monitor state + counters (``{state, counters, ...}``)."""
        return self.send_command("notification_status")

    def set_routing(self, rules) -> dict:
        """Persist + hot-reload the app routing table on the daemon. ``rules`` is
        an iterable of ``(substring, app_type)`` pairs."""
        return self.send_command("set_routing", {"rules": [list(r) for r in rules]})

    # ── device ownership / lifecycle (R17 P5 full cutover) ────────────────
    def connect_device(self, *, mac: str | None = None, lan_ip: str | None = None,
                       lan_token: int = 0, device_name: str | None = None,
                       use_ios_le_protocol: bool = True) -> dict:
        """Ask the daemon to own + connect a device (BLE via ``mac`` or LAN via
        ``lan_ip``). Returns status fields (connected/mac/lan_ip/wall).

        Uses the longer ``connect_timeout`` (BLE setup is slow — the 2s default
        read timeout would give up mid-handshake and surface as "timed out")."""
        from divoom_client.daemon_config import load_daemon_config
        return self.send_command("connect", {
            "mac": mac, "lan_ip": lan_ip, "lan_token": lan_token,
            "device_name": device_name, "use_ios_le_protocol": use_ios_le_protocol,
        }, read_timeout=load_daemon_config().connect_timeout)

    def disconnect_device(self) -> dict:
        from divoom_client.daemon_config import load_daemon_config
        return self.send_command("disconnect",
                                 read_timeout=load_daemon_config().connect_timeout)

    def shutdown(self) -> dict:
        """Ask the daemon to stop its process (clean kill switch). Best-effort:
        the daemon replies, then exits shortly after."""
        return self.send_command("shutdown")

    def device_status(self) -> dict:
        return self.send_command("device_status")

    def scan(self, timeout: float | None = None, limit: int | None = None) -> dict:
        # Divoom BLE discovery is slow (a full scan can take 30-60s). The daemon
        # only replies AFTER scanning for `timeout` seconds, so the client must
        # wait longer than that or the read times out before the (successful)
        # reply arrives. The fallbacks + the read slack live in daemon.ini.
        from divoom_client.daemon_config import load_daemon_config
        cfg = load_daemon_config()
        if timeout is None:
            timeout = cfg.scan_timeout
        if limit is None:
            limit = cfg.scan_limit
        return self.send_command(
            "scan", {"timeout": timeout, "limit": limit},
            read_timeout=cfg.scan_read_timeout(timeout),
        )

    def wall_configure(self, slots: dict, cell_size: int = 16) -> dict:
        # R42 §6: building the wall BLE-connects every slot device — far longer
        # than the quick-command timeout (the 2s read abandoned the reply, the
        # GUI never got its wall handle, and every wall push then failed with
        # "no wall configured" even though the daemon-side wall was healthy).
        from divoom_client.daemon_config import load_daemon_config
        return self.send_command("wall_configure",
                                 {"slots": slots, "cell_size": cell_size},
                                 read_timeout=load_daemon_config().connect_timeout)

    def probe_lan(self) -> dict:
        return self.send_command("probe_lan")

    def now_playing(self, include_artwork: bool = False) -> dict:
        """What is playing, from the daemon's single source of truth.

        R67/C2: the GUI used to answer this itself, in Python, by driving
        AppleScript at each player and then guessing a cover-art URL from the
        iTunes Search API — a second implementation of what the daemon already
        did, running in the GUI process, which is why the GUI was the thing
        asking for Apple Music access.

        ``include_artwork`` attaches the raw image bytes as base64. They are
        ~360KB, so a poller should watch ``identity`` (which excludes artwork)
        and only fetch the bytes when it changes.
        """
        return self.send_command("now_playing",
                                 {"include_artwork": bool(include_artwork)})

    def players(self) -> dict:
        """Every media player the daemon can see, and which is playing.

        R67: `now_playing` reports the ONE session macOS considers current, and
        macOS keeps that session on a PAUSED player — so a paused Kaset made a
        playing Feishin look silent. This separates registration from playback,
        and carries a `hint` when a player is running but unreachable for a
        reason the user can fix.
        """
        return self.send_command("players")

    def weather(self, location: str = "") -> dict:
        """One weather reading, from the source that feeds the device.

        R67/C2: the GUI used to fetch this itself while the daemon fetched it
        again for the device — two fetches of one fact, and potentially two
        different cities, because `location` was never passed through. Empty
        `location` lets the provider geolocate.
        """
        return self.send_command("weather", {"location": location or ""})

    def live_job_start(self, mac: str, kind: str, params: dict) -> dict:
        return self.send_command("live_job_start", {"mac": mac, "kind": kind, "params": params})

    def live_job_stop(self, mac: str, kind: str) -> dict:
        return self.send_command("live_job_stop", {"mac": mac, "kind": kind})

    def live_job_list(self, mac: str | None = None) -> dict:
        return self.send_command("live_job_list", {"mac": mac})

    def live_jobs_stop_for(self, mac: str | None = None) -> dict:
        """Stop all live jobs for a device (default: the daemon's active device).
        Called before a channel/display switch so a running widget doesn't
        clobber it on its next tick."""
        return self.send_command("live_jobs_stop_for", {"mac": mac})

    def set_device_activity(self, mac: str, kind: str, name: str | None = None,
                            preview: str | None = None) -> dict:
        """R46 #3 / R50: record what a device is showing (for the menubar tiles).
        ``preview`` is an optional rasterized PNG data URL for the tile thumbnail."""
        return self.send_command("set_device_activity",
                                 {"mac": mac, "kind": kind, "name": name,
                                  "preview": preview})

    def get_device_activity(self) -> dict:
        """R46 #3: {mac: {name, kind, at}} of what each device is showing."""
        return self.send_command("get_device_activity", {})

    def sync_artwork(self, file_id: str, *, default_size: int = 16,
                     target: str = "device") -> dict:
        """Ask the daemon to download a gallery asset and stream it to the owned
        device/wall (binary stays in the daemon process).

        Uses the long ``sync_read_timeout`` — the daemon only replies after the
        download + full BLE stream, which takes far longer than the quick-command
        timeout (a short read here falsely reported every upload as failed)."""
        from divoom_client.daemon_config import load_daemon_config
        return self.send_command("sync_artwork", {
            "file_id": file_id, "default_size": default_size, "target": target,
        }, read_timeout=load_daemon_config().sync_read_timeout)

    def custom_art_push(self, file_ids: list[str], page: int,
                        slot: int | None = None,
                        slots: dict | None = None) -> dict:
        """Push cloud files to a custom art page on the owned device.

        Args:
            file_ids: list of cloud file IDs (legacy sequential form)
            page: target page 0-2
            slot: optional starting slot for the legacy form
            slots: preferred full-page mapping {slot 0-11: file_id};
                   unmapped slots are cleared on the device
        """
        from divoom_client.daemon_config import load_daemon_config
        return self.send_command("custom_art_push", {
            "file_ids": file_ids, "page": page, "slot": slot, "slots": slots,
        }, read_timeout=load_daemon_config().sync_read_timeout)

    def custom_art_query_page(self, page: int = 0) -> dict:
        """Query device for filled slot IDs on a custom art page."""
        from divoom_client.daemon_config import load_daemon_config
        return self.send_command(
            "custom_art_query_page", {"page": page},
            read_timeout=load_daemon_config().sync_read_timeout)

    def hot_update(self, *, device_size: int = 16, show: bool = True,
                   address: str = "") -> dict:
        """Start a HOT channel update in the background on the daemon (returns
        immediately). Call ``hot_update_progress()`` to poll progress. ``address``
        is the caller's device key; the daemon stamps the last-checked state
        under it (R53)."""
        return self.send_command(
            "hot_update",
            {"device_size": device_size, "show": show, "address": address},
            read_timeout=30)

    def hot_update_progress(self) -> dict:
        """Query the current HOT channel update progress. Returns a phase dict:
        ``{"phase": "idle"|"starting"|"fetching_manifest"|"downloading"|"uploading"|"done"|"error",
        "current": int, "total": int, ...}``."""
        return self.send_command("hot_update_progress", {})

    def subscribe(
        self,
        on_event: Callable[[dict], None],
        *,
        should_stop: Callable[[], bool] | None = None,
    ) -> bool:
        """Open a streaming subscription, calling ``on_event(event)`` for each
        event until the connection closes or ``should_stop()`` returns True.
        Returns True if it connected, False if the daemon was unreachable.
        Blocking — callers run it on their own thread.
        """
        try:
            with self._connect() as s:
                s.settimeout(self.timeout)
                s.sendall(encode_message(make_request(SUBSCRIBE_COMMAND, token=self.token)))
                s.settimeout(1.0)  # short read timeout so should_stop() is responsive
                buf = b""
                while True:
                    if should_stop is not None and should_stop():
                        return True
                    try:
                        chunk = s.recv(4096)
                    except socket.timeout:
                        continue
                    if not chunk:
                        return True  # daemon closed the stream
                    buf += chunk
                    # Cap the unparsed buffer (the read path in send_command does the
                    # same). A malformed / never-newline-terminated broadcast frame
                    # would otherwise grow buf without bound → menubar OOM.
                    if len(buf) > MAX_REPLY_BYTES:
                        return False
                    events, buf = iter_messages(buf)
                    for ev in events:
                        on_event(ev)
        except (OSError, ValueError):
            return False
