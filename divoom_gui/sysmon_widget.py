"""The System Monitor widget, as a DAEMON CLIENT.

Split from `media_sync.py` for the 500-line rule, but it earns its own file: it
is the last widget the GUI used to render itself. It sampled psutil and drew a
PIL frame in this process while the device was drawn by
`divoomd/src/live_jobs/render.rs` — two renderers for one widget, agreeing only
for as long as nobody edited either.

Now the daemon answers with the stats AND the exact frame it would push, and
this module only encodes those bytes to a PNG. The tile and the matrix have one
origin (R67/C2).
"""
from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("divoom_gui")


class SysmonWidgetMixin:
    """System-monitor preview and one-shot push. Mixed into the GUI API."""

    def _sysmon_frame(self, size: int):
        """Ask the daemon for the host stats AND the exact frame it would push.

        R67/C2 applied to the last widget still breaking it. This used to call
        `media_source.get_system_stats()` (psutil) and
        `media_source.render_system_stats_frame()` (PIL) inside the GUI process,
        while the device was drawn by `divoomd/src/live_jobs/render.rs`. Two
        renderers for one widget: the tile and the device agreed only for as
        long as nobody edited either, and a preview that merely resembles the
        device is the dishonest kind this project keeps finding.

        Returns `(stats, frame_path)`, or raises. The PNG is written from the
        daemon's raw RGB rather than redrawn, so the bytes on screen and the
        bytes on the matrix have one origin.
        """
        client = self._client()
        if client is None:
            raise RuntimeError(self._daemon_unreachable_reason())
        try:
            reply = client.sysmon(size=size)
        except OSError as exc:
            # A bare "[Errno 2] No such file or directory" tells a user nothing.
            # The daemon writes WHY it could not take the socket to a sidecar
            # file precisely so a client can say something actionable here.
            raise RuntimeError(self._daemon_unreachable_reason(client, exc)) from exc
        if not isinstance(reply, dict) or not reply.get("success"):
            # `unreachable` is the transport saying nothing was listening. That
            # needs a human sentence, not the errno the socket raised.
            if (reply or {}).get("unreachable"):
                raise RuntimeError(self._daemon_unreachable_reason(client))
            raise RuntimeError((reply or {}).get("error", "sysmon unavailable"))

        stats = {"cpu": reply.get("cpu", 0), "mem": reply.get("mem", 0),
                 "battery": reply.get("battery")}
        sz = int(reply.get("size", size))
        raw = base64.b64decode(reply.get("frame_rgb_b64", ""))
        expected = sz * sz * 3
        if len(raw) != expected:
            # Never render a partial buffer as if it were the device's frame.
            raise RuntimeError(f"sysmon frame is {len(raw)} bytes, expected {expected}")

        from PIL import Image
        scratch = Path(__file__).parent.parent / "scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        frame_path = scratch / f"sysmon_{sz}.png"
        Image.frombytes("RGB", (sz, sz), raw).save(frame_path)
        return stats, frame_path

    def _daemon_unreachable_reason(self, client=None, exc: Exception | None = None) -> str:
        """Why the daemon cannot be reached, in words a user can act on.

        Prefers the daemon's own `<socket>.failure` report — the reason it
        recorded when it could not take the socket (a stale file, a missing
        parent directory, another program already on the path). Falls back to a
        plain sentence rather than an errno, because "[Errno 2] No such file or
        directory" in a System Monitor card names neither the file nor the fix.

        The path comes from the CLIENT, not from the environment. The sidecar
        lives next to whichever socket this GUI is actually talking to, and a
        session started with `--socket` would otherwise have its explanation
        read from a path nobody involved is using — which silently degrades to
        the generic message exactly when the specific one would help most.
        """
        fallback = "the background service is not running"
        if exc is not None:
            fallback = f"{fallback} ({exc})"
        try:
            from divoom_client.daemon_protocol import DEFAULT_SOCKET_PATH
            from divoom_client.socket_failure import explain_daemon_failure

            path = getattr(client, "socket_path", None) or os.environ.get(
                "DIVOOM_SOCKET", DEFAULT_SOCKET_PATH)
            return explain_daemon_failure(path, fallback)
        except Exception:
            return fallback

    def get_system_stats_preview(self, size: int = 0) -> str:
        try:
            sz = int(size) if size and int(size) > 0 else self._active_device_size()
            stats, frame_path = self._sysmon_frame(sz)
            return json.dumps({
                "ok": True, "size": sz, "stats": stats,
                "preview": self._frame_to_data_url(frame_path),
            })
        except Exception as e:
            logger.error(f"get_system_stats_preview failed: {e}")
            return json.dumps({"ok": False, "error": str(e)})

    def apply_system_stats(self) -> str:
        try:
            size = self._active_device_size()
            stats, frame_path = self._sysmon_frame(size)
            if not self._has_push_target():
                return json.dumps({"success": False, "error": "No device connected",
                                   "stats": stats})
            res = self._push_frame(frame_path, size)
            return json.dumps({
                "success": res, "stats": stats,
                "preview": self._frame_to_data_url(frame_path),
            })
        except Exception as e:
            logger.error(f"apply_system_stats failed: {e}")
            return json.dumps({"success": False, "error": str(e)})
