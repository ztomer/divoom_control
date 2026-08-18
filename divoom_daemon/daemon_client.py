"""Daemon client plumbing (R17 P5 / R28).

The BLE device can be held by only one process, so the **daemon is the sole
device owner** and every other process (GUI, MCP server, CLI helpers) is a thin
RPC client. This module lives in ``divoom_daemon`` so any layer can import it
without a backwards ``divoom_lib`` → ``divoom_gui`` dependency;
``divoom_gui.daemon_bridge`` re-exports everything here for backward compat.

It gives clients:

  * ``ensure_daemon()`` — make sure a daemon is running (auto-spawn one if not),
    returning a connected :class:`DaemonClient`. Idempotent + safe to call on
    every device action.
  * ``DaemonDeviceProxy`` — a stand-in for a ``Divoom`` whose attribute access
    builds a dotted method path and whose calls issue a ``device_call`` RPC, so
    existing call-sites like ``target.display.show_light(color, b)`` work
    unchanged once ``target`` is a proxy. Calls return awaitables, so the GUI's
    ``_run_async(...)`` scheduling still applies.

Nothing here imports BLE or pywebview — it's pure client plumbing and unit-tested
against a fake daemon in ``tests/test_daemon_bridge.py``.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from divoom_daemon.daemon_protocol import (
    DEFAULT_SOCKET_PATH,
    ENV_HOST,
    DaemonClient,
)

logger = logging.getLogger("divoom_gui")


def bundle_python() -> str | None:
    """In a py2app ``.app``, the path to the bundled interpreter that can run
    ``-m divoom_lib.cli`` — ``sys.executable`` there is the GUI app stub
    (``Contents/MacOS/Divoom``), not a python. Returns None when running from
    source. The sibling ``Contents/MacOS/python`` is a real interpreter with the
    bundle's modules on its path (verified: it imports divoom_lib and runs the
    daemon/menubar entry points)."""
    if getattr(sys, "frozen", None) != "macosx_app":
        return None
    cand = Path(sys.executable).resolve().parent / "python"
    return str(cand) if cand.exists() else None


def _client_alive(client: DaemonClient) -> bool:
    # Liveness probe: fast-fail (connect_retries=0). Probe get_status (cheap,
    # LOCK-FREE) NOT device_status, which needs the device mutex — a device op
    # holding it makes a live daemon look dead (false "not running" banner).
    reply = client.send_command("get_status", connect_retries=0)
    return bool(reply.get("success", False))


def daemon_alive(socket_path: str = DEFAULT_SOCKET_PATH, timeout: float = 0.5) -> bool:
    """True if a daemon answers ``get_status`` on ``socket_path``."""
    return _client_alive(DaemonClient(socket_path, timeout=timeout))


def _spawn_disclaimed_macos(cmd: list[str], log_path: str,
                            env: dict[str, str] | None = None) -> int:
    """Spawn ``cmd`` with macOS TCC responsibility DISCLAIMED, returning the pid.

    This is the crux of making BLE work from the GUI without user intervention.
    A normal child inherits the parent's "responsible process" for TCC — for the
    GUI that's pywebview's `Python.app` (which has no Bluetooth grant), so every
    scan comes back empty/denied. Disclaiming makes the daemon its OWN responsible
    process: a Python daemon is attributed to the granted python binary
    (`python3.14` in Privacy > Bluetooth), the native ``divoomd`` to its OWN
    embedded Info.plist (`com.divoom.divoomd`, build.rs `__TEXT,__info_plist`).
    Either way the grant no longer depends on whoever launched the .app — an
    *inherited* responsibility with no usage description (Terminal, Claude
    Desktop) SIGABRTs the daemon the instant CoreBluetooth starts.

    ``env`` overrides the spawned process environment (defaults to ``os.environ``);
    the native daemon needs ``DIVOOMD_ENCODER_LIB`` propagated this way.

    Uses posix_spawn (libc) with `responsibility_spawnattrs_setdisclaim` +
    POSIX_SPAWN_SETSID, redirecting stdout/stderr to ``log_path``.
    """
    import ctypes
    import ctypes.util

    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    attr_t = ctypes.c_void_p   # posix_spawnattr_t (opaque pointer on macOS)
    fa_t = ctypes.c_void_p     # posix_spawn_file_actions_t
    libc.posix_spawnattr_init.argtypes = [ctypes.POINTER(attr_t)]
    libc.posix_spawnattr_setflags.argtypes = [ctypes.POINTER(attr_t), ctypes.c_short]
    libc.posix_spawnattr_destroy.argtypes = [ctypes.POINTER(attr_t)]
    libc.responsibility_spawnattrs_setdisclaim.argtypes = [ctypes.POINTER(attr_t), ctypes.c_int]
    libc.posix_spawn_file_actions_init.argtypes = [ctypes.POINTER(fa_t)]
    libc.posix_spawn_file_actions_destroy.argtypes = [ctypes.POINTER(fa_t)]
    libc.posix_spawn_file_actions_addopen.argtypes = [
        ctypes.POINTER(fa_t), ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_uint]
    libc.posix_spawn_file_actions_adddup2.argtypes = [ctypes.POINTER(fa_t), ctypes.c_int, ctypes.c_int]
    libc.posix_spawn.argtypes = [
        ctypes.POINTER(ctypes.c_int), ctypes.c_char_p,
        ctypes.POINTER(fa_t), ctypes.POINTER(attr_t),
        ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(ctypes.c_char_p)]

    POSIX_SPAWN_SETSID = 0x0400
    attr = attr_t()
    if libc.posix_spawnattr_init(ctypes.byref(attr)) != 0:
        raise OSError("posix_spawnattr_init failed")
    try:
        libc.posix_spawnattr_setflags(ctypes.byref(attr), POSIX_SPAWN_SETSID)
        if libc.responsibility_spawnattrs_setdisclaim(ctypes.byref(attr), 1) != 0:
            raise OSError("responsibility_spawnattrs_setdisclaim failed")

        fa = fa_t()
        libc.posix_spawn_file_actions_init(ctypes.byref(fa))
        try:
            libc.posix_spawn_file_actions_addopen(ctypes.byref(fa), 0, b"/dev/null", os.O_RDONLY, 0)
            libc.posix_spawn_file_actions_addopen(
                ctypes.byref(fa), 1, log_path.encode(),
                os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            libc.posix_spawn_file_actions_adddup2(ctypes.byref(fa), 1, 2)

            argv = (ctypes.c_char_p * (len(cmd) + 1))(*[a.encode() for a in cmd], None)
            env_items = (env if env is not None else os.environ)
            env_pairs = [f"{k}={v}" for k, v in env_items.items()]
            envp = (ctypes.c_char_p * (len(env_pairs) + 1))(*[e.encode() for e in env_pairs], None)
            pid = ctypes.c_int()
            rc = libc.posix_spawn(ctypes.byref(pid), cmd[0].encode(),
                                  ctypes.byref(fa), ctypes.byref(attr), argv, envp)
            if rc != 0:
                raise OSError(f"posix_spawn failed rc={rc}")
            return pid.value
        finally:
            libc.posix_spawn_file_actions_destroy(ctypes.byref(fa))
    finally:
        libc.posix_spawnattr_destroy(ctypes.byref(attr))


def spawn_daemon(
    socket_path: str = DEFAULT_SOCKET_PATH,
    *,
    mac: str | None = None,
    detach: bool = False,
):
    """Launch the ``divoomd`` (Rust) daemon process.

    On macOS, spawn it with TCC responsibility DISCLAIMED so it's its own
    responsible process rather than inheriting the launcher's (unset) Bluetooth
    usage description — this is what makes BLE work from the GUI with no user
    intervention (see :func:`_spawn_disclaimed_macos`). Falls back to
    ``subprocess.Popen`` on other platforms or if the disclaim spawn fails.

    Caller waits until the socket is live (see :func:`ensure_daemon`).
    """
    # Resolve the native Rust daemon binary: env override, then the py2app .app
    # bundle (Contents/Resources via RESOURCEPATH), then the dev build tree.
    rust_bin = os.environ.get("DIVOOM_RUST_BINARY")
    if rust_bin and not Path(rust_bin).exists():
        rust_bin = None
    rust_env_extra: dict[str, str] = {}
    # PyInstaller bundle: divoomd is collected under <_MEIPASS>/bin and the encoder
    # dylib under <_MEIPASS>/divoom_lib (data lands in Resources for a .app).
    _mei = getattr(sys, "_MEIPASS", None)
    if not rust_bin and _mei:
        for _bin in (Path(_mei) / "bin" / "divoomd",
                     Path(_mei).parent / "Resources" / "bin" / "divoomd"):
            if _bin.exists():
                rust_bin = str(_bin)
                for _dy in (Path(_mei) / "divoom_lib" / "libdivoom_compact.dylib",
                            Path(_mei).parent / "Resources" / "divoom_lib" / "libdivoom_compact.dylib"):
                    if _dy.exists():
                        rust_env_extra["DIVOOMD_ENCODER_LIB"] = str(_dy)
                        break
                break
    _rp = os.environ.get("RESOURCEPATH")  # set by py2app inside the .app bundle
    if not rust_bin and _rp:
        cand = Path(_rp) / "divoomd"
        if cand.exists():
            rust_bin = str(cand)
            # The bundled daemon can't find the encoder dylib by relative path —
            # point it at the copy shipped alongside it in Resources.
            dylib = Path(_rp) / "libdivoom_compact.dylib"
            if dylib.exists():
                rust_env_extra["DIVOOMD_ENCODER_LIB"] = str(dylib)
    if not rust_bin:
        # daemon_client.py lives at <repo>/divoom_daemon/daemon_client.py, so the
        # repo root is parents[1].
        repo_root = Path(__file__).resolve().parents[1]
        for folder in ["release", "debug"]:
            p = repo_root / "target" / folder / "divoomd"
            if p.exists():
                rust_bin = str(p)
                break
    # The Rust daemon is the sole shipping daemon (the Python reference server was
    # archived 2026-07-13 — see divoom_daemon/__init__.py); there is no longer a
    # Python-daemon spawn fallback. Raise clearly rather than emitting a
    # `-m divoom_lib.cli daemon` command that no longer works.
    if rust_bin is None:
        raise RuntimeError(
            "divoomd (Rust daemon) binary not found — set DIVOOM_RUST_BINARY, "
            "build divoomd/, or run from a packaged .app. The Python daemon "
            "server was archived; see divoom_daemon/__init__.py."
        )
    cmd = [rust_bin, "--socket", socket_path]
    if mac:
        cmd += ["--mac", mac]
    log_path = os.environ.get("DIVOOM_DAEMON_LOG", "/tmp/divoom_daemon.log")
    try:
        with open(log_path, "a", buffering=1) as fh:
            fh.write(f"\n==== daemon spawn from pid {os.getpid()} ====\n")
    except OSError:
        pass

    # macOS TCC: an undisclaimed child inherits its launcher's responsible
    # process; if that launcher lacks a Bluetooth usage description (e.g. the .app
    # was started under Terminal / Claude Desktop), CoreBluetooth SIGABRTs the
    # daemon the instant it scans. Disclaim so divoomd is its OWN responsible
    # process, via its embedded com.divoom.divoomd Info.plist (build.rs
    # __TEXT,__info_plist).
    if sys.platform == "darwin":
        try:
            disclaim_env = {**os.environ, **rust_env_extra}
            pid = _spawn_disclaimed_macos(cmd, log_path, env=disclaim_env)
            logger.info("Spawned daemon (TCC-disclaimed) pid=%s", pid)
            return pid
        except Exception as e:
            logger.warning("Disclaimed spawn failed (%s); falling back to Popen.", e)

    try:
        log_fh = open(log_path, "a", buffering=1)
        _out = _err = log_fh
    except OSError:
        _out = _err = subprocess.DEVNULL
    logger.info("Spawning daemon (Popen, detach=%s): %s", detach, " ".join(cmd))
    spawn_env = os.environ.copy()
    spawn_env.update(rust_env_extra)  # e.g. DIVOOMD_ENCODER_LIB for the bundled daemon
    return subprocess.Popen(
        cmd, stdout=_out, stderr=_err, stdin=subprocess.DEVNULL,
        start_new_session=detach, env=spawn_env,
    )


def ensure_daemon(
    socket_path: str = DEFAULT_SOCKET_PATH,
    *,
    mac: str | None = None,
    spawn: bool = True,
    wait_timeout: float = 8.0,
    detach: bool = False,
) -> DaemonClient | None:
    """Return a :class:`DaemonClient` for a *live* daemon, auto-spawning one if
    needed. Returns ``None`` if no daemon could be reached/started.

    If ``DIVOOM_DAEMON_HOST`` is set, target that *remote* daemon over TCP and
    never spawn (it's on another host). Otherwise use the local Unix socket and
    auto-spawn. Idempotent: a live daemon returns immediately.
    """
    if os.environ.get(ENV_HOST):
        remote = DaemonClient.from_env(socket_path)
        if _client_alive(remote):
            return remote
        logger.error("Remote daemon at %s:%s not reachable", remote.host, remote.port)
        return None
    if daemon_alive(socket_path):
        return DaemonClient(socket_path)
    if not spawn:
        return None
    spawn_daemon(socket_path, mac=mac, detach=detach)
    deadline = time.monotonic() + wait_timeout
    while time.monotonic() < deadline:
        if daemon_alive(socket_path):
            return DaemonClient(socket_path)
        time.sleep(0.1)
    logger.error("Daemon did not become ready within %.1fs", wait_timeout)
    return None


class _DeviceCallError(RuntimeError):
    """Raised inside the proxy awaitable when the daemon reports failure."""


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
                raise _DeviceCallError(reply.get("error", f"device_call {method} failed"))
            return reply.get("result")

        return _invoke()
