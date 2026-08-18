#!/usr/bin/env python3
"""Isolate WHY scan works directly but fails through the GUI->daemon path.

RUN FROM YOUR (granted) TERMINAL:

    python3 scripts/diagnose_daemon_scan.py

The direct scan already works (diagnose_ble.py found 4). The GUI runs the scan
(a) on a background asyncio thread (the daemon's `_device_loop`), and (b) inside
a spawned daemon subprocess. This tests both so we know which one returns empty.
"""
import asyncio
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from divoom_lib.utils import discovery
from divoom_client.daemon_protocol import DaemonClient


def test_background_thread() -> None:
    print("[1] scan on a BACKGROUND asyncio thread (like the daemon's _device_loop):")
    res = {}

    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            res["r"] = loop.run_until_complete(
                discovery.discover_all_divoom_devices(timeout=8.0))
        except Exception as e:
            res["err"] = repr(e)
        finally:
            loop.close()

    t = threading.Thread(target=run)
    t.start()
    t.join()
    if "err" in res:
        print("    ERROR:", res["err"])
    else:
        print(f"    -> {len(res['r'])} device(s): {[d['name'] for d in res['r']]}")


def test_daemon_subprocess() -> None:
    print("[2] FULL daemon path: spawn the daemon (as the GUI does), send `scan`:")
    sock = "/tmp/divoom_diag.sock"
    if os.path.exists(sock):
        os.remove(sock)
    # Exactly how the GUI spawns it: sys.executable, NON-detached.
    proc = subprocess.Popen(
        [sys.executable, "-m", "divoom_lib.cli", "daemon", "--socket", sock],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    print("    daemon python:", sys.executable)
    for _ in range(60):
        if os.path.exists(sock):
            break
        time.sleep(0.1)
    try:
        c = DaemonClient(sock, timeout=20)
        print("    device_status:", c.device_status())
        print("    scan ->", c.scan(timeout=8, limit=0))
        print("    daemon still alive:", proc.poll() is None)
        try:
            c.shutdown()
        except Exception:
            pass
    finally:
        time.sleep(0.4)
        if proc.poll() is None:
            proc.terminate()
        try:
            out, _ = proc.communicate(timeout=3)
            if out:
                print("    --- daemon output (tail) ---")
                for line in out.strip().splitlines()[-12:]:
                    print("    |", line)
        except Exception:
            pass


if __name__ == "__main__":
    test_background_thread()
    print("-" * 60)
    test_daemon_subprocess()
