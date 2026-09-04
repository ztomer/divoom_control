#!/usr/bin/env python3
"""hw_smoke.py — drive a RUNNING daemon over its socket to exercise the BLE
stack on real hardware. Pure socket IPC (DaemonClient) — no BLE in THIS process,
so it can run from any context (incl. an unprivileged shell) without a TCC crash;
the daemon (a granted process) does all the Bluetooth.

Usage:
    divoom-control daemon            # in a BT-granted terminal (or the .app)
    python3 scripts/hw_smoke.py [--scan-timeout N] [--phase discover|connect|stress|all]

Style: Susan Kare icons + restrained Braun colours (matches ~/projects/scripts).
"""
from __future__ import annotations

import argparse
import json
import sys
import time

# ── kare style (TTY-aware) ──────────────────────────────────────────────
_TTY = sys.stdout.isatty()
_I_START, _I_OK, _I_ERR, _I_WARN, _I_STEP = ("→", "✓", "✗", "⚠", "·")
_RESET = "\033[0m" if _TTY else ""
_DIM = "\033[2m" if _TTY else ""
_BOLD = "\033[1m" if _TTY else ""
_GREEN = "\033[0;32m" if _TTY else ""
_RED = "\033[0;31m" if _TTY else ""
_YELLOW = "\033[0;33m" if _TTY else ""
_GRAY = "\033[0;90m" if _TTY else ""


def info(m): print(f"{_GRAY}{_I_START}{_RESET} {_DIM}{m}{_RESET}")
def step(m): print(f"{_GRAY}{_I_STEP}{_RESET} {m}")
def ok(m): print(f"{_GREEN}{_I_OK}{_RESET} {m}")
def err(m): print(f"{_RED}{_I_ERR}{_RESET} {m}")
def warn(m): print(f"{_YELLOW}{_I_WARN}{_RESET} {m}")
def hr(w=60): print(f"{_GRAY}{'─' * w}{_RESET}")
def section(t): print(); hr(); print(f"{_BOLD}  {t}{_RESET}"); hr()


def _client():
    from divoom_client.daemon_protocol import DaemonClient
    return DaemonClient()


def discover(c, scan_timeout: float) -> list:
    section("Discover")
    try:
        info(f"daemon-side scan ({scan_timeout:.0f}s)…")
        r = c.scan(timeout=scan_timeout)
        devs = r.get("devices") or r.get("results") or r.get("found") or []
        if devs:
            ok(f"{len(devs)} device(s):")
            for d in devs:
                name = d.get("name") if isinstance(d, dict) else d
                addr = d.get("address") if isinstance(d, dict) else ""
                step(f"{name}  {_GRAY}{addr}{_RESET}")
        else:
            warn(f"no devices advertising. raw={json.dumps(r)[:200]}")
        return devs
    except Exception as e:
        err(f"scan failed: {type(e).__name__}: {e}")
        return []


def _conn_state(c) -> dict:
    try:
        return c.get_connection_state() or {}
    except Exception:
        return {}


def _connect(c, mac: str, name: str) -> tuple[bool, float]:
    """Connect via the daemon; return (ok, seconds). R53: a real device connects
    fast; an asleep/held one fails CLEANLY within the bounded timeout (never hangs)."""
    t0 = time.monotonic()
    try:
        r = c.connect_device(mac=mac)
        dt = time.monotonic() - t0
        good = bool(r.get("success") and r.get("connected"))
        if good:
            ok(f"connected {name} in {dt:.1f}s  {_GRAY}{json.dumps(_conn_state(c))[:90]}{_RESET}")
        else:
            warn(f"{name} not connected in {dt:.1f}s — reason={r.get('reason') or r.get('error')}")
        return good, dt
    except Exception as e:
        dt = time.monotonic() - t0
        err(f"connect {name} raised in {dt:.1f}s: {type(e).__name__}: {e}")
        return False, dt


def cycles(c, devs: list) -> None:
    """Exercise the R53 connect/reconnect/eviction paths on real hardware."""
    section("Connect / reconnect / eviction cycles")
    targets = [(d.get("name"), d.get("address")) for d in devs if isinstance(d, dict) and d.get("address")]
    if not targets:
        warn("no connectable devices; skipping"); return
    a_name, a_mac = targets[0]
    info(f"primary: {a_name}")

    # 1. connect → disconnect → RECONNECT  (validates stop_notify-on-disconnect, C3:
    #    a leaked subscription would make the reconnect's start_notify fail)
    g1, _ = _connect(c, a_mac, a_name)
    if g1:
        try:
            c.disconnect_device(); step("disconnected")
        except Exception as e:
            err(f"disconnect raised: {e}")
        time.sleep(1.0)
        g2, _ = _connect(c, a_mac, a_name)
        ok("reconnect after clean disconnect OK (stop_notify path)") if g2 else err("RECONNECT FAILED — possible notify leak")

    # 2. switch to the OTHER device and back (validates single-owner eviction +
    #    transport-swap teardown — must NOT 16s-timeout on the re-grab)
    if len(targets) > 1:
        b_name, b_mac = targets[1]
        info(f"switching active → {b_name} (evicts {a_name})")
        gb, dtb = _connect(c, b_mac, b_name)
        if gb and dtb < 15:
            ok(f"eviction-switch to {b_name} clean ({dtb:.1f}s, no 16s stall)")
        elif gb:
            warn(f"switch worked but slow ({dtb:.1f}s)")
        info(f"switching back → {a_name}")
        _connect(c, a_mac, a_name)

    try:
        c.disconnect_device(); step("final disconnect")
    except Exception:
        pass


def _status(c) -> dict:
    try:
        return c.device_status() or {}
    except Exception as e:
        return {"_err": f"{type(e).__name__}: {e}"}


def stress(c, devs: list, iterations: int, scan_every: int, fleet: int,
           churn: bool = False) -> int:
    """Hammer discover/connect/disconnect/switch in a tight loop to surface BLE
    flakiness. Records anomalies (identity mismatch, degraded-but-connected lies,
    duration spikes, reconnect failures, fleet-count drops, raised exceptions).

    churn=True skips the clean disconnect so every connect EVICTS the previous
    device (the single-owner re-grab path where the 16s-stall / wrong-device bugs
    lived) — the harsher test.
    Returns the anomaly count (0 == clean run)."""
    section(f"Stress — {iterations} iterations")
    targets = [(d.get("name"), d.get("address")) for d in devs
               if isinstance(d, dict) and d.get("address")]
    if not targets:
        warn("no connectable devices; cannot stress"); return 0

    anomalies: list[str] = []
    # per-device tally: [attempts, oks, fails, dt_min, dt_max, dt_sum]
    tally: dict[str, list] = {a: [0, 0, 0, 9e9, 0.0, 0.0] for _, a in targets}
    SPIKE = 15.0   # connect slower than this = near-timeout/stall

    def note(msg):
        anomalies.append(msg); err(f"ANOMALY: {msg}")

    for i in range(1, iterations + 1):
        name, mac = targets[(i - 1) % len(targets)]
        step(f"[{i}/{iterations}] → {name}")

        # periodic scan to stress discovery + catch fleet-count drops
        if scan_every and i % scan_every == 0:
            t0 = time.monotonic()
            try:
                n = len((c.scan(timeout=8) or {}).get("devices") or [])
                dt = time.monotonic() - t0
                (ok if n >= fleet else warn)(f"scan #{i}: {n}/{fleet} in {dt:.1f}s")
                if n < fleet:
                    note(f"scan#{i} found {n} of {fleet} devices")
            except Exception as e:
                note(f"scan#{i} raised {type(e).__name__}: {e}")

        # connect
        t = tally[mac]; t[0] += 1
        t0 = time.monotonic()
        try:
            r = c.connect_device(mac=mac)
            dt = time.monotonic() - t0
            t[3] = min(t[3], dt); t[4] = max(t[4], dt); t[5] += dt
            good = bool(r.get("success") and r.get("connected"))
            if not good:
                t[2] += 1; note(f"connect {name} failed: {r.get('reason') or r.get('error')}")
                continue
            t[1] += 1
            if dt > SPIKE:
                note(f"connect {name} SLOW {dt:.1f}s (near timeout)")
            # identity + liveness truth-check via status
            s = _status(c)
            got = (s.get("mac") or "").upper()
            if got and got != mac.upper():
                note(f"identity: asked {name}({mac[:8]}) got mac {got[:8]}")
            if s.get("connected") and s.get("connection_state") == "degraded":
                note(f"{name} reports connected but DEGRADED (is_alive False)")
        except Exception as e:
            dt = time.monotonic() - t0
            t[2] += 1; note(f"connect {name} raised in {dt:.1f}s: {type(e).__name__}: {e}")
            continue

        time.sleep(0.3)   # brief dwell

        if churn:
            continue       # no disconnect — next connect must EVICT this device

        # disconnect, then verify the daemon really released it
        try:
            c.disconnect_device()
            s = _status(c)
            if s.get("connected"):
                note(f"{name} still 'connected' after disconnect (stale handle)")
        except Exception as e:
            note(f"disconnect {name} raised: {type(e).__name__}: {e}")

    # summary
    section("Stress summary")
    for nm, addr in targets:
        a, o, f, lo, hi, sm = tally[addr]
        if a == 0:
            continue
        avg = sm / a if a else 0
        line = f"{nm:<20} {o}/{a} ok"
        line += f"  {_GRAY}{lo:.1f}/{avg:.1f}/{hi:.1f}s (min/avg/max){_RESET}"
        (ok if f == 0 else warn)(line)
    if anomalies:
        err(f"{len(anomalies)} anomaly(ies):")
        for m in anomalies:
            step(f"{_RED}{m}{_RESET}")
    else:
        ok("no anomalies — clean stress run")
    return len(anomalies)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan-timeout", type=float, default=12.0)
    ap.add_argument("--phase", choices=["discover", "cycles", "stress", "all"], default="discover")
    ap.add_argument("--iterations", type=int, default=20)
    ap.add_argument("--scan-every", type=int, default=4, help="re-scan every N stress iters (0=off)")
    ap.add_argument("--fleet", type=int, default=4, help="expected device count for scan checks")
    ap.add_argument("--churn", action="store_true", help="evict instead of clean-disconnect (harsher)")
    args = ap.parse_args()

    section("Divoom HW smoke — daemon socket")
    try:
        c = _client()
    except Exception as e:
        err(f"cannot reach daemon: {e}"); return 2

    # status snapshot
    for name, call in (("connection_state", "get_connection_state"),
                       ("device_activity", "get_device_activity")):
        try:
            fn = getattr(c, call, None)
            if fn:
                step(f"{name}: {_DIM}{json.dumps(fn())[:200]}{_RESET}")
        except Exception as e:
            warn(f"{name} unavailable: {e}")

    devs = discover(c, args.scan_timeout)
    rc = 0
    if args.phase in ("cycles", "all"):
        cycles(c, devs)
    if args.phase in ("stress", "all"):
        rc = stress(c, devs, args.iterations, args.scan_every, args.fleet, args.churn)
    print()
    ok("done." if rc == 0 else f"done — {rc} anomaly(ies) flagged.")
    return 1 if rc else 0


if __name__ == "__main__":
    sys.exit(main())
