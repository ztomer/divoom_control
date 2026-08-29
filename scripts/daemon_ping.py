#!/usr/bin/env python3
"""daemon_ping.py — is a divoomd listening on this socket, and is it the ONLY one?

Pure socket IPC: no BLE is touched in this process, so it is safe to run from an
un-granted shell (a direct CoreBluetooth call there hard-crashes on macOS TCC).

R67: split out of the harness scripts because three of them needed the same two
questions answered — "is the daemon up?" and "is exactly one alive?" — and the
second one has no other home. A second, invisible daemon is not a hypothetical:
one ran for 34 hours on the dev machine while the GUI talked to a different one,
both able to hold the single-owner BLE central.

Usage:
    daemon_ping.py [--socket PATH] [--wait SECONDS]   # exit 0 when reachable
    daemon_ping.py --instances                        # exit 0 when exactly 1 alive
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.environ.get("GOH_DIR", os.path.expanduser("~/Projects/gates_of_heck")))
from tui.lib import err, info, ok, warn  # noqa: E402

DEFAULT_SOCKET = "/tmp/divoom.sock"


def ping(sock_path: str, timeout: float = 3.0) -> dict | None:
    """One NDJSON round-trip. Returns the reply dict, or None if unreachable."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(sock_path)
        s.sendall(b'{"command":"get_status"}\n')
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        s.close()
        return json.loads(buf.decode())
    except (OSError, ValueError):
        return None


def wait_for(sock_path: str, seconds: float) -> dict | None:
    """Poll until the daemon answers or the budget runs out."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        reply = ping(sock_path)
        if reply is not None:
            return reply
        time.sleep(0.25)
    return None


def live_daemons() -> list[tuple[int, str]]:
    """Every running divoomd, as (pid, command). Uses an absolute ps path: `ps`
    is alias-rewritten on this machine and mangles the flags."""
    try:
        out = subprocess.run(["/bin/ps", "-Ao", "pid,command"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in out.splitlines()[1:]:
        pid, _, cmd = line.strip().partition(" ")
        # Match the daemon BINARY only: the executable path's basename is
        # `divoomd`. Substring matching would also catch this script, a grep for
        # it, an editor with the source open, or `divoomd mcp` (which is a
        # client, not the daemon) — each a false alarm on a gate that must not
        # cry wolf.
        argv0 = cmd.split(" ", 1)[0]
        if os.path.basename(argv0) != "divoomd":
            continue
        if " mcp" in cmd:  # `divoomd mcp` is the stdio MCP client, not a daemon
            continue
        try:
            found.append((int(pid), cmd))
        except ValueError:
            pass
    return found


def check_instances() -> int:
    """Exactly one daemon must be alive. Zero is fine for a stopped system; two
    or more is the single-owner violation and always an error."""
    procs = live_daemons()
    if len(procs) > 1:
        err(f"{len(procs)} divoomd processes alive — the device has ONE owner")
        for pid, cmd in procs:
            info(f"pid {pid}: {cmd}")
        return 1
    if not procs:
        warn("no divoomd running")
        return 0
    ok(f"exactly one divoomd alive (pid {procs[0][0]})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--socket", default=DEFAULT_SOCKET)
    ap.add_argument("--wait", type=float, default=0.0,
                    help="poll up to N seconds for the daemon to come up")
    ap.add_argument("--instances", action="store_true",
                    help="instead: assert exactly one divoomd is alive")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if args.instances:
        return check_instances()

    reply = wait_for(args.socket, args.wait) if args.wait else ping(args.socket)
    if reply is None:
        if not args.quiet:
            err(f"no daemon answering on {args.socket}")
        return 1
    if not args.quiet:
        ok(f"daemon up on {args.socket} (uptime {reply.get('uptime_s', '?')}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
