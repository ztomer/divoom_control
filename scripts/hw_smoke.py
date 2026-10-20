#!/usr/bin/env python3
"""hw_smoke.py — drive a RUNNING daemon over its socket to exercise the BLE
stack on real hardware. Pure socket IPC (DaemonClient) — no BLE in THIS process,
so it can run from any context (incl. an unprivileged shell) without a TCC crash;
the daemon (a granted process) does all the Bluetooth.

Usage:
    ./run.sh                         # in a BT-granted terminal (or the .app)
    python3 scripts/hw_smoke.py [--scan-timeout N] [--phase discover|connect|stress|all]

Exit codes: 0 = clean, 1 = at least one branch FAILED (a raise, a refused
connect, a stress anomaly), 2 = the daemon is not there. A branch that raises
is a FAIL, never a warning: the first version of this script caught the
NameError raised while printing a device and exited 0, so a run that had just
found four panels was reported as a clean run whose reporting had failed.

Style: Susan Kare icons + restrained Braun colours (matches ~/projects/scripts).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tui.lib import info, step, ok, err, warn, hr, section

import time


class Failures:
    """What this run collected. A branch that RAISED is a FAILURE, not a warning.

    The first version of this script printed its results with the house
    TUI's module-private colour names (`_GRAY`, `_RESET`, ...), which do not
    exist outside `tui/lib.py` — so the first line that printed a device
    raised NameError. The raise was caught, reported as `warn(...)`, and the
    run exited 0: a scan that had just found four panels was reported as a
    clean run whose reporting had failed. An instrument that cannot say NO is
    a form, not a check.

    So: every branch that raises, or that fails, lands here, and this is what
    the exit code is made of.
    """

    def __init__(self) -> None:
        self.items: list[str] = []

    def fail(self, message: str) -> None:
        self.items.append(message)
        err(message)

    def __bool__(self) -> bool:
        return bool(self.items)

    def __len__(self) -> int:
        return len(self.items)


def _client():
    from divoom_client.daemon_protocol import DaemonClient
    return DaemonClient()


def discover(c, scan_timeout: float, failures: Failures) -> list:
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
                step(f"{name}  {addr}")
        else:
            warn(f"no devices advertising. raw={json.dumps(r)[:200]}")
        return devs
    except Exception as e:
        failures.fail(f"scan failed: {type(e).__name__}: {e}")
        return []


def _conn_state(c) -> dict:
    try:
        return c.get_connection_state() or {}
    except Exception:
        return {}


def _connect(c, mac: str, name: str, failures: Failures) -> tuple[bool, float]:
    """Connect via the daemon; return (ok, seconds). R53: a real device connects
    fast; an asleep/held one fails CLEANLY within the bounded timeout (never hangs)."""
    t0 = time.monotonic()
    try:
        r = c.connect_device(mac=mac)
        dt = time.monotonic() - t0
        good = bool(r.get("success") and r.get("connected"))
        if good:
            ok(f"connected {name} in {dt:.1f}s  {json.dumps(_conn_state(c))[:90]}")
        else:
            failures.fail(f"{name} not connected in {dt:.1f}s — "
                          f"reason={r.get('reason') or r.get('error')}")
        return good, dt
    except Exception as e:
        dt = time.monotonic() - t0
        failures.fail(f"connect {name} raised in {dt:.1f}s: {type(e).__name__}: {e}")
        return False, dt


def cycles(c, devs: list, failures: Failures) -> None:
    """Exercise the R53 connect/reconnect/eviction paths on real hardware."""
    section("Connect / reconnect / eviction cycles")
    targets = [(d.get("name"), d.get("address")) for d in devs if isinstance(d, dict) and d.get("address")]
    if not targets:
        warn("no connectable devices; skipping"); return
    a_name, a_mac = targets[0]
    info(f"primary: {a_name}")

    # 1. connect → disconnect → RECONNECT  (validates stop_notify-on-disconnect, C3:
    #    a leaked subscription would make the reconnect's start_notify fail)
    g1, _ = _connect(c, a_mac, a_name, failures)
    if g1:
        try:
            c.disconnect_device(); step("disconnected")
        except Exception as e:
            failures.fail(f"disconnect raised: {e}")
        time.sleep(1.0)
        g2, _ = _connect(c, a_mac, a_name, failures)
        if g2:
            ok("reconnect after clean disconnect OK (stop_notify path)")
        else:
            failures.fail("RECONNECT FAILED — possible notify leak")

    # 2. switch to the OTHER device and back (validates single-owner eviction +
    #    transport-swap teardown — must NOT 16s-timeout on the re-grab)
    if len(targets) > 1:
        b_name, b_mac = targets[1]
        info(f"switching active → {b_name} (evicts {a_name})")
        gb, dtb = _connect(c, b_mac, b_name, failures)
        if gb and dtb < 15:
            ok(f"eviction-switch to {b_name} clean ({dtb:.1f}s, no 16s stall)")
        elif gb:
            warn(f"switch worked but slow ({dtb:.1f}s)")
        info(f"switching back → {a_name}")
        _connect(c, a_mac, a_name, failures)

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
           churn: bool = False, failures: Failures | None = None) -> int:
    """Hammer discover/connect/disconnect/switch in a tight loop to surface BLE
    flakiness. Records anomalies (identity mismatch, degraded-but-connected lies,
    duration spikes, reconnect failures, fleet-count drops, raised exceptions).

    churn=True skips the clean disconnect so every connect EVICTS the previous
    device (the single-owner re-grab path where the 16s-stall / wrong-device bugs
    lived) — the harsher test.
    Returns the anomaly count (0 == clean run)."""
    failures = failures if failures is not None else Failures()
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
        anomalies.append(msg); failures.fail(f"ANOMALY: {msg}")

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
        line += f"  {lo:.1f}/{avg:.1f}/{hi:.1f}s (min/avg/max)"
        (ok if f == 0 else warn)(line)
    if anomalies:
        err(f"{len(anomalies)} anomaly(ies):")
        for m in anomalies:
            step(m)
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
    failures = Failures()
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
                step(f"{name}: {json.dumps(fn())[:200]}")
        except Exception as e:
            # A branch that RAISED is a FAILURE. It used to be a warning, and
            # the run still exited 0 — the NameError that came from printing
            # the snapshot was reported as a footnote on a successful run.
            failures.fail(f"{name} unavailable: {type(e).__name__}: {e}")

    devs = discover(c, args.scan_timeout, failures)
    if args.phase in ("cycles", "all"):
        cycles(c, devs, failures)
    if args.phase in ("stress", "all"):
        stress(c, devs, args.iterations, args.scan_every, args.fleet, args.churn,
               failures)
    print()
    if failures:
        err(f"done — {len(failures)} failure(s) above.")
    else:
        ok("done.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
