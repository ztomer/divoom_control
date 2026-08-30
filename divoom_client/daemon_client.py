"""Daemon client plumbing (R17 P5 / R28).

The BLE device can be held by only one process, so the **daemon is the sole
device owner** and every other process (GUI, MCP server, CLI helpers) is a thin
RPC client. This module lives in ``divoom_client`` so any layer can import it
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

from divoom_client.daemon_protocol import (
    DEFAULT_SOCKET_PATH,
    ENV_HOST,
    DaemonClient,
)

from divoom_client.socket_failure import explain_daemon_failure
from divoom_client.daemon_version import (  # noqa: F401  (re-exported)
    _stop_stale_daemon,
    expected_daemon_version,
    running_daemon_version,
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
        # daemon_client.py lives at <repo>/divoom_client/daemon_client.py, so the
        # repo root is parents[1].
        repo_root = Path(__file__).resolve().parents[1]
        for folder in ["release", "debug"]:
            p = repo_root / "target" / folder / "divoomd"
            if p.exists():
                rust_bin = str(p)
                break
    # The Rust daemon is the sole shipping daemon (the Python reference server was
    # archived 2026-07-13 — see divoom_client/__init__.py); there is no longer a
    # Python-daemon spawn fallback. Raise clearly rather than emitting a
    # `-m divoom_lib.cli daemon` command that no longer works.
    if rust_bin is None:
        raise RuntimeError(
            "divoomd (Rust daemon) binary not found — set DIVOOM_RUST_BINARY, "
            "build divoomd/, or run from a packaged .app. The Python daemon "
            "server was archived; see divoom_client/__init__.py."
        )
    cmd = [rust_bin, "--socket", socket_path]
    if mac:
        cmd += ["--mac", mac]
    log_path = os.environ.get("DIVOOM_DAEMON_LOG", "/tmp/divoom_client.log")
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
    check_version: bool = True,
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
        # R67: VERIFY THE VERSION, do not just check for a pulse. A daemon left
        # over from an older install answers `get_status` perfectly well and
        # then silently lacks whatever was added since — during R67 this cost
        # three debugging cycles, most memorably a `players` call that returned
        # an empty list because the running daemon predated the command, with
        # nothing in the reply to say so.
        #
        # Only ever restart on a KNOWN mismatch. If the expectation cannot be
        # determined, leave the daemon alone: killing something that might be
        # current is worse than tolerating something that might be stale.
        expected = expected_daemon_version()
        if expected and check_version:
            running = running_daemon_version(socket_path)
            if running != expected:
                if not _stop_stale_daemon(socket_path, running, expected):
                    return DaemonClient(socket_path)
                if not spawn:
                    return None
                spawn_daemon(socket_path, mac=mac, detach=detach)
                deadline = time.monotonic() + wait_timeout
                while time.monotonic() < deadline:
                    if daemon_alive(socket_path):
                        return DaemonClient(socket_path)
                    time.sleep(0.1)
                logger.error(
                    "replacement daemon did not start within %.1fs: %s",
                    wait_timeout,
                    explain_daemon_failure(
                        socket_path, "no reason reported by the daemon"),
                )
                return None
        return DaemonClient(socket_path)
    if not spawn:
        return None
    spawn_daemon(socket_path, mac=mac, detach=detach)
    deadline = time.monotonic() + wait_timeout
    while time.monotonic() < deadline:
        if daemon_alive(socket_path):
            return DaemonClient(socket_path)
        time.sleep(0.1)
    # R67: say WHY. The daemon is spawned detached with its stderr in a log
    # file, so without this the user got "no daemon" and the actual cause -- a
    # stale socket, a directory in the way, a permission problem -- was never
    # surfaced anywhere they would look.
    logger.error(
        "Daemon did not become ready within %.1fs: %s",
        wait_timeout,
        explain_daemon_failure(socket_path, "no reason reported by the daemon"),
    )
    return None

# The device proxy lives in daemon_proxy.py (500-line cap); re-exported so
# `from divoom_client.daemon_client import DaemonDeviceProxy` keeps working.
from divoom_client.daemon_proxy import (  # noqa: E402,F401
    DaemonDeviceProxy,
    _ConnView,
    _DeviceCallError,
    _LanView,
    _ProxyExclusiveCtx,
)
