"""`DaemonDeviceProxy` — device calls that look local and travel to the daemon.

Split out of `daemon_client.py` in R67 when that file crossed the house
500-line cap. An attribute chain like `target.display.show_light(color, b)`
builds a dotted method path and issues one `device_call` RPC, so existing
call-sites work unchanged once `target` is a proxy.
"""
from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

from divoom_client.daemon_protocol import DEFAULT_SOCKET_PATH, DaemonClient

logger = logging.getLogger("divoom_client.daemon_proxy")


class _DeviceCallError(RuntimeError):
    """Raised inside the proxy awaitable when the daemon reports failure.

    Carries the daemon's machine-readable ``cause`` when there is one (R71
    P3.1). Without it the proxy flattened every failure to a message string,
    so a GUI panel could only ever say "it failed" -- which is how a BLE-only
    user clicking Send Overlay got "Failed to send overlay" instead of "this
    device has no LAN API". The reason existed daemon-side and died here.
    """

    def __init__(self, message: str, cause: str = ""):
        super().__init__(message)
        self.cause = cause


class _LanView:
    """Minimal stand-in for ``divoom.lan`` so introspection reads still work."""
    def __init__(self, device_ip: str | None):
        self.device_ip = device_ip

    def __bool__(self):
        return bool(self.device_ip)


class _ConnView:
    """Minimal stand-in for ``divoom._conn`` (only ``.mac`` is read by the GUI)."""
    def __init__(self, mac: str | None):
        self.mac = mac


# Root-only synthetic attributes answered from `device_status` rather than a
# dotted method call.
_STATUS_ATTRS = ("is_connected", "lan", "_conn")


class _ProxyExclusiveCtx:
    """Async context manager returned by ``DaemonDeviceProxy.exclusive()``."""

    def __init__(self, proxy: "DaemonDeviceProxy", token: str) -> None:
        self._proxy = proxy
        self._token = token

    async def __aenter__(self) -> "DaemonDeviceProxy":
        client = self._proxy._client
        reply = client.exclusive_start(self._token)
        if not reply.get("success", False):
            raise _DeviceCallError(reply.get("error", "exclusive_start failed"))
        return self._proxy._with_token(self._token)

    async def __aexit__(self, *exc: object) -> None:
        # __aexit__ always runs (Python guarantees it once __aenter__ succeeded), so
        # the token is always *attempted* to be released. But exclusive_end() returns
        # a reply dict instead of raising; a non-success release (daemon mid-restart,
        # socket blip past the retry budget) was silently dropped — the daemon then
        # holds the exclusive token until the G3 idle auto-release (~30s), wedging
        # every other caller's queue items meanwhile. We can't raise here (would mask
        # a body exception), so log loudly for diagnosis.
        try:
            reply = self._proxy._client.exclusive_end(self._token)
        except Exception as e:
            logger.warning("exclusive_end raised for token %s: %s", self._token, e)
            return
        if not (reply or {}).get("success", False):
            logger.warning("exclusive_end did not confirm release of token %s: %s "
                           "(device wedged until the ~30s G3 auto-release)",
                           self._token, (reply or {}).get("error"))


class DaemonDeviceProxy:
    """Attribute/method stand-in for a ``Divoom`` (or ``DivoomWall``) that routes
    through a daemon.

    ``proxy.display.show_light(color, b)`` records the dotted path
    ``"display.show_light"`` and returns an awaitable that, when run, issues a
    ``device_call`` RPC and returns the daemon's ``result`` (raising on failure).
    Arbitrary nesting works: ``proxy.lan.set_brightness(v)`` →
    ``"lan.set_brightness"``.

    ``target`` is "device" (the single owned Divoom) or "wall" (the daemon-owned
    DivoomWall). Root-level introspection reads (``is_connected``/``lan``/
    ``_conn``) are answered synchronously from ``device_status``.
    """

    # Short-TTL cache for device_status() introspection. A single GUI operation
    # reads is_connected/lan/_conn back-to-back, each previously firing its OWN
    # blocking device_status() socket RPC; the cache collapses them to one. The TTL
    # is short enough that staleness is negligible (and the daemon's device_call
    # self-heals the connection regardless of a slightly-stale GUI read).
    _STATUS_TTL = 0.25

    def __init__(self, client: DaemonClient, _path: str = "", *,
                 target: str = "device", _token: str | None = None) -> None:
        object.__setattr__(self, "_client", client)
        object.__setattr__(self, "_path", _path)
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_token", _token)
        object.__setattr__(self, "_status_cache", None)
        object.__setattr__(self, "_status_cache_ts", 0.0)

    def _with_token(self, token: str) -> "DaemonDeviceProxy":
        return DaemonDeviceProxy(self._client, self._path,
                                 target=self._target, _token=token)

    async def push_animation(self, file_or_data: str | bytes,
                              *,
                              token: str | None = None) -> bool:
        """Push an animation (GIF/image) to the device inside an exclusive
        session.  ``file_or_data`` is either a local path *or* raw bytes
        (written to a temp file first).  Calls ``display.show_image()``
        which does the 0x8B 3-phase streaming internally.

        Returns ``True`` on success.
        """
        import os
        import tempfile
        own_tmp = None
        if isinstance(file_or_data, bytes):
            tmp = tempfile.NamedTemporaryFile(suffix=".gif", delete=False)
            try:
                tmp.write(file_or_data)
                tmp.close()
                path = tmp.name
                own_tmp = path
            except OSError:
                tmp.close()
                raise
        else:
            path = file_or_data

        effective_token = token or f"push-anim-{id(path)}"
        try:
            async with self.exclusive(effective_token) as p:
                return bool(await p.display.show_image(path))
        finally:
            # Delete the temp file WE created (bytes input) — on success AND on
            # error. Without this every byte-payload animation push leaked one
            # /tmp/*.gif for the process lifetime.
            if own_tmp is not None:
                try:
                    os.unlink(own_tmp)
                except OSError:
                    pass

    def exclusive(self, token: str) -> _ProxyExclusiveCtx:
        """Context manager for an exclusive-mode session on the daemon.

        Usage::

            async with proxy.exclusive("my-token") as p:
                await p.display.show_light(255, 0, 0)
                await p.lan.set_brightness(80)

        Between ``exclusive_start`` and ``exclusive_end`` only calls tagged
        with ``token`` are dispatched by the daemon's command queue — no
        other callers can interleave."""
        return _ProxyExclusiveCtx(self, token)

    def _status(self) -> dict:
        import time
        now = time.monotonic()
        if self._status_cache is not None and (now - self._status_cache_ts) < self._STATUS_TTL:
            return self._status_cache
        st = self._client.device_status()
        object.__setattr__(self, "_status_cache", st)
        object.__setattr__(self, "_status_cache_ts", now)
        return st

    def __getattr__(self, name: str) -> Any:
        # Root-level synthetic introspection reads (device only).
        if name in _STATUS_ATTRS and self._path == "":
            st = self._status()
            if name == "is_connected":
                key = "wall" if self._target == "wall" else "connected"
                return bool(st.get(key, False))
            if name == "lan":
                return _LanView(st.get("lan_ip"))
            if name == "_conn":
                return _ConnView(st.get("mac"))
        if name.startswith("_"):
            raise AttributeError(name)
        path = f"{self._path}.{name}" if self._path else name
        return DaemonDeviceProxy(self._client, path, target=self._target, _token=self._token)

    def __call__(self, *args: Any, **kwargs: Any):
        method = self._path
        client = self._client
        target = self._target
        token = self._token
        call_args = list(args)

        # Remote daemon (TCP): no shared filesystem, so any positional arg that
        # is a local file path must be shipped as a blob (the daemon writes it to
        # a temp file and substitutes the path back in). Local Unix clients pass
        # the path directly — the daemon reads the same disk.
        blobs: dict[int, bytes] | None = None
        if getattr(client, "is_remote", False):
            for i, a in enumerate(call_args):
                try:
                    if isinstance(a, str) and os.path.isfile(a):
                        with open(a, "rb") as f:
                            blobs = blobs or {}
                            blobs[i] = f.read()
                except OSError:
                    pass

        async def _invoke():
            reply = client.device_call(method, call_args, dict(kwargs),
                                       target=target, blobs=blobs, token=token)
            if not reply.get("success", False):
                raise _DeviceCallError(
                    reply.get("error", f"device_call {method} failed"),
                    str(reply.get("cause") or ""))
            return reply.get("result")

        return _invoke()
