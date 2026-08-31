"""The ONE way the GUI obtains a widget frame.

R70 P1.3. Every widget preview in this app goes through :meth:`_widget_frame`,
and the only thing it does is ask the daemon. There is no second path, and that
is the entire design: the GUI's job is to encode bytes it was given, never to
produce them.

**Why a funnel rather than "each panel calls the daemon".** R67/C2 made exactly
that fix for sysmon — one panel, done properly — and the next two widgets were
written the old way regardless, because nothing structural said otherwise. The
stock tile drew itself with PIL beside the daemon's `render_stock`; the
album-art preview resized LANCZOS while the device got NEAREST. Per-panel
correctness is a habit, and habits do not survive the next contributor. A single
helper does: adding a widget means calling this, because getting pixels any
other way now means writing the fetch, the render and the encode yourself, and
`tools/check_gui_is_a_client.py` fails the commit if you try.

**Honest failures.** The daemon's reason is raised, never swallowed into a blank
tile. A preview that silently shows nothing is indistinguishable from a widget
with nothing to show, which is the confusion this whole round exists to end.
"""
from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

logger = logging.getLogger("divoom_gui")


class WidgetFrameError(RuntimeError):
    """A widget frame could not be obtained, with the daemon's own reason."""


class WidgetFrameMixin:
    """`_widget_frame` and its encode step. Mixed into the GUI API."""

    def _widget_frame(self, kind: str, size: int,
                      params: dict | None = None) -> tuple[dict, Path]:
        """Ask the daemon to render ``kind`` and write the bytes to a PNG.

        Returns ``(extras, frame_path)`` — ``extras`` being whatever that kind
        reports alongside its pixels (sysmon: cpu/mem/battery; stocks: symbol,
        price, change, pct_change), and ``frame_path`` a PNG written from the
        daemon's raw RGB rather than redrawn.

        The PNG is an ENCODING of bytes the daemon produced, not a rendering.
        That distinction is the one the gate enforces and the one that keeps the
        tile and the matrix identical: `Image.frombytes` cannot introduce a
        resample filter, a font, or a colour the device will not show.
        """
        client = self._frame_client()
        if client is None:
            raise WidgetFrameError(self._frame_unreachable_reason())
        try:
            reply = client.render_widget(kind, size=size, params=params or {})
        except OSError as exc:
            raise WidgetFrameError(
                self._frame_unreachable_reason(client, exc)) from exc

        if not isinstance(reply, dict) or not reply.get("success"):
            reply = reply if isinstance(reply, dict) else {}
            if reply.get("unreachable"):
                raise WidgetFrameError(self._frame_unreachable_reason(client))
            raise WidgetFrameError(
                str(reply.get("error") or f"{kind} is unavailable"))

        sz = int(reply.get("size", size))
        raw = base64.b64decode(reply.get("frame_rgb_b64", ""))
        expected = sz * sz * 3
        if len(raw) != expected:
            # Never render a partial buffer as if it were the device's frame: a
            # truncated draw looks like a design, not like an error.
            raise WidgetFrameError(
                f"{kind} frame is {len(raw)} bytes, expected {expected}")

        extras = {k: v for k, v in reply.items()
                  if k not in ("success", "frame_rgb_b64", "size", "kind")}
        return extras, self._write_frame_png(kind, sz, raw)

    @staticmethod
    def _write_frame_png(kind: str, size: int, raw: bytes) -> Path:
        """Encode raw daemon RGB to a PNG on disk.

        `Image.frombytes` only — the sole PIL call the R70 gate permits in this
        package, because it cannot alter a pixel. Anything that could (`new`,
        `open`, `resize`) would make this a second renderer again.
        """
        from PIL import Image
        scratch = Path(__file__).parent.parent / "scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        frame_path = scratch / f"{kind}_{size}.png"
        Image.frombytes("RGB", (size, size), raw).save(frame_path)
        return frame_path

    # ── plumbing the mixin needs from its host class ─────────────────────────

    def _frame_client(self):
        """The daemon client, however the host class exposes it.

        `sysmon_widget` reaches it through `self._client()`, the api layer
        through `self._client`. Accepting both keeps this usable from either
        without a refactor that is not part of this step.
        """
        client = getattr(self, "_client", None)
        if callable(client):
            return client()
        return client

    def _frame_unreachable_reason(self, client=None,
                                  exc: Exception | None = None) -> str:
        """Why the daemon could not be reached, in words a user can act on.

        Delegates to the host class's own explainer when it has one (sysmon's
        predates this mixin and reads the daemon's `<socket>.failure` sidecar),
        so there is one explanation, not two that drift.
        """
        own = getattr(self, "_daemon_unreachable_reason", None)
        if callable(own):
            try:
                return own(client, exc)
            except TypeError:
                return own()
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
