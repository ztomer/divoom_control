"""
R15 §5 — MCP subprocess controller for the GUI.

The GUI doesn't run the MCP server inline (that would tie the
pywebview event loop to a long-running stdio server). Instead it
spawns ``divoom-control mcp-server --mac <MAC>`` as a subprocess
and tracks the PID.

Why subprocess, not in-process:
  - pywebview's event loop and the MCP server's stdin/stdout loop
    would fight over the same file descriptors.
  - The MCP spec requires a *clean* stdio stream (one JSON-RPC
    message per line on stdout). The GUI's logger writes to
    stderr only, so spawning keeps the streams clean.
  - Crashes in the MCP server don't take the GUI down with them.

Usage::

    from divoom_gui.mcp_control import MCPController
    ctl = MCPController()
    if not ctl.is_running():
        ctl.start(mac="11:75:58:3f:fd:aa")
    status = ctl.status()
    # ...later...
    ctl.stop()
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


# Default log file for the subprocess. The GUI tails this for the
# status display.
DEFAULT_LOG_PATH = Path.home() / ".config" / "divoom-control" / "mcp-server.log"


@dataclass
class MCPStatus:
    """Snapshot of the subprocess state for the JS side."""
    running: bool
    pid: Optional[int] = None
    started_at: Optional[float] = None
    mac: Optional[str] = None
    log_path: Optional[str] = None
    last_log_lines: list[str] = field(default_factory=list)
    error: Optional[str] = None


class MCPController:
    """Spawn / stop / status for the MCP stdio server subprocess.

    The controller is intentionally simple — it does not parse the
    JSON-RPC stream (that would require intercepting the subprocess's
    stdio, which the parent process owns for its own stdio transport).
    For richer status, the subprocess writes to a log file which the
    controller tails on demand.
    """

    # How many lines from the end of the log file to return in
    # ``status()`` for the GUI's status display.
    LOG_TAIL_LINES = 20
    # How many bytes from the end of the log file to read for the
    # tail — bounded so we don't OOM on a runaway log.
    LOG_TAIL_BYTES = 16 * 1024

    def __init__(self, log_path: Optional[Path] = None) -> None:
        self._log_path = Path(log_path) if log_path else DEFAULT_LOG_PATH
        self._proc: Optional[subprocess.Popen] = None
        self._started_at: Optional[float] = None
        self._mac: Optional[str] = None
        # True once we've spawned a server in *this* GUI session. Gates whether
        # ``status()`` surfaces the log file: on a fresh launch (toggle never
        # touched) we must NOT tail a log left over from a previous session, or
        # the card shows an archaeological traceback the user can't act on.
        self._started_this_session: bool = False

    # ── Subprocess spawn / stop ────────────────────────────────────

    def is_running(self) -> bool:
        """True if our tracked subprocess is alive (PID + poll)."""
        if self._proc is None:
            return False
        if self._proc.poll() is not None:
            # Process exited — drop the reference.
            self._proc = None
            self._started_at = None
            self._mac = None
            return False
        return True

    def start(self, mac: Optional[str] = None, *, python: Optional[str] = None) -> MCPStatus:
        """Start the MCP server subprocess: `divoomd mcp`.

        ``mac`` is optional: since R28 the MCP server routes through the daemon
        (the sole device owner), so it does not need a MAC. Returns a status
        dict. If a server is already running, the call is a no-op and the
        existing status is returned.

        **R70 P4.2. This used to spawn `[sys.executable, "-m",
        "divoom_lib.cli", "mcp-server"]`, and inside the packaged app
        `sys.executable` is the GUI binary.** Reproduced on the shipped v0.28.3
        (P4.1): the spawned process did not fail — `gui_main.main()` reads its
        arguments with `parse_known_args()`, ignored them, and launched a whole
        SECOND Divoom window, another daemon and another menubar agent, while
        answering no JSON-RPC at all. Worse, `is_running()` then reported the
        MCP server as UP, because a process was genuinely alive.

        `divoomd mcp` is the same server, ported (`divoomd/src/mcp.rs`), and it
        ships in the bundle two directories from where the old command looked.
        Resolution goes through `divoom_client.binary_resolver`, never a second
        path-walk of its own: picking a binary by location instead of by version
        is the R69 defect, and a second resolver is how it would come back.

        ``python`` is still accepted so a caller can force an interpreter, but
        it now names the DAEMON binary to run.
        """
        if self.is_running():
            return self.status()

        from divoom_client import binary_resolver

        exe = python or binary_resolver.resolve("divoomd")
        if not exe:
            return MCPStatus(
                running=False,
                error="no usable divoomd found — rebuild it (scripts/build.sh) "
                      "or reinstall the app")
        cmd = [str(exe), "mcp"]
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        # Truncate ("wb"), not append: each start gets a self-contained log so
        # the GUI card never mixes a fresh run with a stale crash from a prior
        # session. Combined with ``_started_this_session`` gating in status().
        log_fp = open(self._log_path, "wb", buffering=0)
        env = dict(os.environ)
        env.setdefault("PYTHONUNBUFFERED", "1")
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,  # we don't feed it JSON-RPC
                stdout=log_fp,
                stderr=log_fp,
                env=env,
                # New process group so ``stop()`` can kill the whole tree.
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            return MCPStatus(running=False, error=f"divoomd not found: {exc}")
        except OSError as exc:
            return MCPStatus(running=False, error=f"failed to spawn MCP server: {exc}")
        self._started_at = time.time()
        self._mac = mac
        self._started_this_session = True
        logger.info("MCP server started: pid=%s mac=%s", self._proc.pid, mac)
        # Reap the log file handle — the subprocess owns the FD now.
        try:
            log_fp.close()
        except OSError:
            pass
        return self.status()

    def stop(self, *, timeout_s: float = 3.0) -> MCPStatus:
        """Stop the subprocess (SIGTERM, then SIGKILL after a grace
        period). No-op if not running."""
        if not self.is_running() or self._proc is None:
            return self.status()
        pid = self._proc.pid
        try:
            # Send SIGTERM to the whole process group (set in start()).
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            self._proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                self._proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
        logger.info("MCP server stopped: pid=%s", pid)
        self._proc = None
        self._started_at = None
        self._mac = None
        self._started_this_session = False
        return self.status()

    # ── Status ─────────────────────────────────────────────────────

    def status(self) -> MCPStatus:
        running = self.is_running()
        last_lines: list[str] = []
        # Only surface the log for a server we started this session. On a fresh
        # GUI launch (toggle never touched) the log on disk is from an older run
        # and must not be shown — that was the "traceback shown when the toggle
        # is off" bug. ``is_running()`` may have flipped the flag's companion
        # process reference to None after a crash-exit, but we keep showing the
        # (now clean) log until the user explicitly stops via stop().
        try:
            if self._started_this_session and self._log_path.exists():
                with open(self._log_path, "rb") as f:
                    f.seek(0, os.SEEK_END)
                    size = f.tell()
                    f.seek(max(0, size - self.LOG_TAIL_BYTES))
                    data = f.read().decode("utf-8", errors="replace")
                last_lines = data.splitlines()[-self.LOG_TAIL_LINES :]
        except OSError as exc:
            return MCPStatus(
                running=running,
                pid=self._proc.pid if self._proc else None,
                started_at=self._started_at,
                mac=self._mac,
                log_path=str(self._log_path),
                error=f"failed to read log: {exc}",
            )
        return MCPStatus(
            running=running,
            pid=self._proc.pid if self._proc else None,
            started_at=self._started_at,
            mac=self._mac,
            log_path=str(self._log_path),
            last_log_lines=last_lines,
        )

    # ── Singleton (one controller per GUI process) ────────────────

    _instance: Optional["MCPController"] = None

    @classmethod
    def instance(cls) -> "MCPController":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


# ── JSON serialization for the JS bridge ────────────────────────────


def status_to_dict(status: MCPStatus) -> dict:
    """Convert an MCPStatus to a JSON-friendly dict (for the JS bridge)."""
    return {
        "running": bool(status.running),
        "pid": int(status.pid) if status.pid is not None else None,
        "started_at": float(status.started_at) if status.started_at is not None else None,
        "mac": status.mac,
        "log_path": status.log_path,
        "last_log_lines": list(status.last_log_lines),
        "error": status.error,
    }
