#!/usr/bin/env python3
"""On-device validation harness for real Divoom hardware.

Run this from a terminal that has macOS Bluetooth permission (the agent's
sandboxed shell can't). It connects to each device and cycles the full command
matrix slowly so you can watch the screens, recording per-step success/error to
test_reports/device_validation.json.

Usage:
    # discover everything nearby and validate all:
    python3 scripts/validate_devices.py --scan

    # or target specific devices by BLE address / UUID:
    python3 scripts/validate_devices.py --addresses AA:BB:..,CC:DD:..

    # or by name substring (e.g. your four units):
    python3 scripts/validate_devices.py --names Timoo,Tivoo,Ditoo,Pixoo

Options:
    --dwell 2.5     seconds to hold each visual step (so you can look)
    --report PATH   output json (default test_reports/device_validation.json)
    --quick         shorter cycles (skip the full 0..15 sweeps)

While it runs, note for each device: do brightness/colors change, do the 6 clock
dials look distinct, do VJ effects animate, and — important for the UI — the
HIGHEST visualizer/EQ index (step "viz N") that shows a real pattern.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.append(str(ROOT))
sys.path.append(str(ROOT / "divoom_gui"))

from divoom_lib.divoom import Divoom              # noqa: E402
from divoom_lib.utils import discovery             # noqa: E402
from divoom_lib.utils import media_source          # noqa: E402


async def _run_step(results, label, coro, dwell):
    print(f"    → {label} ...", end=" ", flush=True)
    try:
        res = await coro
        ok = res is not False  # None/True/dict all count as "sent ok"
        results.append({"step": label, "ok": bool(ok), "error": None})
        print("ok" if ok else "returned False")
    except Exception as e:
        results.append({"step": label, "ok": False, "error": str(e)})
        print(f"ERROR: {e}")
    await asyncio.sleep(dwell)


async def validate_device(address, name, dwell, quick):
    print(f"\n=== {name or 'device'} ({address}) ===")
    entry = {"address": address, "name": name, "connected": False, "steps": []}
    dev = Divoom(mac=address, use_ios_le_protocol=None)
    try:
        await dev.connect()
        entry["connected"] = bool(dev.is_connected)
        print(f"  connected: {entry['connected']}")
    except Exception as e:
        entry["error"] = f"connect failed: {e}"
        print(f"  CONNECT FAILED: {e}")
        return entry

    steps = entry["steps"]

    # Brightness
    await _run_step(steps, "brightness 30", dev.device.set_brightness(30), dwell)
    await _run_step(steps, "brightness 100", dev.device.set_brightness(100), dwell)

    # Solid colors
    for cname, hexv in (("red", "FF0000"), ("green", "00FF00"), ("blue", "0000FF")):
        await _run_step(steps, f"light {cname}", dev.display.show_light(hexv, 100, True), dwell)

    # Clock dials (2.f) — 6 real built-in types
    for n in range(6):
        await _run_step(steps, f"clock dial {n}", dev.display.show_clock(clock=n), dwell)

    # VJ effects (2.d) — 16 named
    vj_range = range(0, 16, 4) if quick else range(16)
    for n in vj_range:
        await _run_step(steps, f"vj effect {n}", dev.display.show_effects(number=n), dwell)

    # Visualizer / EQ (2.c) — sweep to find the real count
    viz_range = range(0, 16, 2) if quick else range(16)
    for n in viz_range:
        await _run_step(steps, f"viz {n}", dev.display.show_visualization(number=n), dwell)

    # Image push (5.a/5.c/area 7) — the path the two recent bug fixes were on
    size = _guess_size(name)
    try:
        ticker = media_source.render_stock_ticker_frame(
            "BTC", {"price": 64000, "change": 1.0, "pct_change": 1.0}, size=size)
        await _run_step(steps, "image: ticker", dev.display.show_image(str(ticker)), dwell + 1)
    except Exception as e:
        steps.append({"step": "image: ticker", "ok": False, "error": str(e)})
    try:
        stats = media_source.get_system_stats()
        sysmon = media_source.render_system_stats_frame(stats, size=size)
        await _run_step(steps, "image: sysmon", dev.display.show_image(str(sysmon)), dwell + 1)
    except Exception as e:
        steps.append({"step": "image: sysmon", "ok": False, "error": str(e)})

    try:
        await dev.disconnect()
    except Exception:
        pass
    return entry


def _guess_size(name):
    n = (name or "").lower()
    if "pixoo" in n and "64" in n:
        return 64
    return 16


async def validate_device_rigorous(address, name, dwell):
    """Real device-CONFIRMED validation (not just "the BLE write returned").

    Uses set→read-back round-trips and query responses, so a pass means the
    device actually received, applied, and reported the state — proving genuine
    two-way communication, not a fire-and-forget ack.
    """
    print(f"\n=== {name or 'device'} ({address}) [RIGOROUS] ===")
    entry = {"address": address, "name": name, "connected": False, "steps": []}
    dev = Divoom(mac=address, use_ios_le_protocol=None)

    def record(label, ok, detail=None):
        entry["steps"].append({"step": label, "ok": bool(ok), "error": None if ok else detail})
        print(f"    {'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))

    try:
        await dev.connect()
        entry["connected"] = bool(dev.is_connected)
    except Exception as e:
        entry["error"] = f"connect failed: {e}"
        print(f"  CONNECT FAILED: {e}")
        return entry
    record("connect", entry["connected"])

    # 1. Device responds to a query (real two-way round-trip).
    try:
        nm = await dev.device.get_device_name()
        record("query device name (round-trip)", nm is not None, f"name={nm!r}")
    except Exception as e:
        record("query device name (round-trip)", False, str(e))

    # 2. DEFINITIVE: set brightness, read it back, compare.
    for target in (25, 90):
        try:
            await dev.device.set_brightness(target)
            await asyncio.sleep(0.6)
            readback = await dev.device.get_brightness()
            ok = readback is not None and abs(int(readback) - target) <= 2
            record(f"brightness set {target} → read {readback}", ok, f"read={readback}")
        except Exception as e:
            record(f"brightness round-trip {target}", False, str(e))
        await asyncio.sleep(dwell)

    # 3. Work-mode read-back after switching to VJ effects.
    try:
        await dev.display.show_effects(number=0)
        await asyncio.sleep(0.6)
        wm = await dev.device.get_work_mode()
        record("work mode after show_effects (read-back)", wm is not None, f"work_mode={wm}")
    except Exception as e:
        record("work mode read-back", False, str(e))

    # 3.b Clock dial round-trip (set dial, read back light settings and compare dial index)
    for target_dial in (1, 4):
        try:
            await dev.display.show_clock(clock=target_dial)
            await asyncio.sleep(0.6)
            light_mode = await dev.light.get_light_mode()
            readback = light_mode.get("time_display_mode") if light_mode else None
            ok = readback == target_dial
            record(f"clock dial set {target_dial} → read {readback}", ok, f"read={readback}")
        except Exception as e:
            record(f"clock dial round-trip {target_dial}", False, str(e))
        await asyncio.sleep(dwell)

    # 4. Visual commands: sent, then a liveness query proves the device didn't
    #    desync/choke (display correctness is the watcher's eyes).
    visual = []
    for n in range(6):
        try:
            await dev.display.show_clock(clock=n); visual.append(True)
        except Exception:
            visual.append(False)
        await asyncio.sleep(dwell * 0.5)
    record("clock dials 0-5 sent", all(visual), f"{sum(visual)}/6")

    try:
        size = _guess_size(name)
        frame = media_source.render_stock_ticker_frame(
            "BTC", {"price": 64000, "change": 1.0, "pct_change": 1.0}, size=size)
        await dev.display.show_image(str(frame))
        await asyncio.sleep(1.0)
        # Liveness: device still answers a query after the (chunked) image push.
        alive = await dev.device.get_brightness()
        record("image push + device still responsive", alive is not None, f"brightness={alive}")
    except Exception as e:
        record("image push + responsive", False, str(e))

    try:
        await dev.disconnect()
    except Exception:
        pass
    return entry


async def validate_via_server(address, name, dwell, quick, conn):
    """Drive the matrix through a *running* app's control server (REST or unix
    socket). The app process — which has Bluetooth permission — does the BLE;
    this just orchestrates and records. `conn` is a dict of call() kwargs."""
    import control_server as cs

    print(f"\n=== {name or 'device'} ({address}) via control server ===")
    entry = {"address": address, "name": name, "connected": False, "steps": []}

    def step(label, method, *args):
        print(f"    → {label} ...", end=" ", flush=True)
        try:
            res = cs.call(method, *args, **conn)
            ok = res is not False and not (isinstance(res, dict) and res.get("success") is False)
            entry["steps"].append({"step": label, "ok": bool(ok),
                                   "error": (res.get("error") if isinstance(res, dict) else None)})
            print("ok" if ok else f"failed ({res})")
            return ok
        except Exception as e:
            entry["steps"].append({"step": label, "ok": False, "error": str(e)})
            print(f"ERROR: {e}")
            return False

    if not step("connect", "connect_single_device", address):
        return entry
    entry["connected"] = True
    time.sleep(dwell)

    for cname, hexv in (("red", "FF0000"), ("green", "00FF00"), ("blue", "0000FF")):
        step(f"light {cname}", "set_solid_light", hexv, 100); time.sleep(dwell)
    for n in range(6):
        step(f"clock dial {n}", "set_clock", n); time.sleep(dwell)
    for n in (range(0, 16, 4) if quick else range(16)):
        step(f"vj effect {n}", "set_vj_effect", n); time.sleep(dwell)
    for n in (range(0, 16, 2) if quick else range(16)):
        step(f"viz {n}", "set_visualization", n); time.sleep(dwell)
    step("image: ticker", "apply_stock_ticker", "BTC-USD"); time.sleep(dwell + 1)
    # R71 deleted `apply_system_stats` -- the one-shot sysmon push lost its JS
    # caller in R40 and the live job superseded it. This script dispatches BY
    # NAME, so the call had become a guaranteed runtime failure that nothing
    # would catch until someone ran it against real hardware. Toggle the live
    # job on, let it draw, toggle it off.
    step("image: sysmon (live, on)", "toggle_sysmon_sync", True)
    time.sleep(dwell + 1)
    step("image: sysmon (live, off)", "toggle_sysmon_sync", False)
    return entry


async def _resolve_targets(args):
    if args.addresses:
        return [(a.strip(), None) for a in args.addresses.split(",") if a.strip()]
    found = await discovery.discover_all_divoom_devices(timeout=float(args.scan_timeout))
    targets = []
    names = [s.strip().lower() for s in args.names.split(",")] if args.names else None
    for d in found:
        nm = d.get("name", "")
        if names and not any(s in (nm or "").lower() for s in names):
            continue
        targets.append((d.get("address"), nm))
    return targets


async def main_async(args):
    targets = await _resolve_targets(args)
    if not targets:
        print("No target devices found. Try --addresses or check the device names.")
        return 1
    print(f"Validating {len(targets)} device(s): "
          + ", ".join(f"{n or '?'}({a})" for a, n in targets))

    use_socket = args.socket or os.environ.get("DIVOOM_CONTROL_SOCKET")
    use_server = args.server or os.environ.get("DIVOOM_CONTROL_SERVER_URL")
    
    report = {"devices": [], "summary": {}}
    for address, name in targets:
        if use_socket or use_server:
            conn = {}
            if use_socket:
                conn["socket_path"] = use_socket
            if use_server:
                conn["base_url"] = use_server
            if args.token or os.environ.get("DIVOOM_CONTROL_TOKEN"):
                conn["token"] = args.token or os.environ.get("DIVOOM_CONTROL_TOKEN")
            report["devices"].append(await validate_via_server(address, name, args.dwell, args.quick, conn))
        elif args.rigorous:
            report["devices"].append(await validate_device_rigorous(address, name, args.dwell))
        else:
            report["devices"].append(await validate_device(address, name, args.dwell, args.quick))

    total_steps = sum(len(d["steps"]) for d in report["devices"])
    ok_steps = sum(1 for d in report["devices"] for s in d["steps"] if s["ok"])
    report["summary"] = {
        "devices": len(report["devices"]),
        "connected": sum(1 for d in report["devices"] if d["connected"]),
        "steps": total_steps,
        "ok": ok_steps,
        "failed": total_steps - ok_steps,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport written to {out}")
    print(f"Summary: {report['summary']}")
    # Surface any failures prominently.
    for d in report["devices"]:
        fails = [s for s in d["steps"] if not s["ok"]]
        if fails or not d["connected"]:
            print(f"  → {d['name'] or d['address']}: "
                  + ("not connected" if not d["connected"] else f"{len(fails)} step(s) failed"))
            for s in fails:
                print(f"      - {s['step']}: {s['error']}")
    return 0


def main():
    p = argparse.ArgumentParser(description="Validate Divoom commands on real hardware")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--addresses", help="comma-separated BLE addresses/UUIDs")
    g.add_argument("--scan", action="store_true", help="discover devices nearby")
    p.add_argument("--names", help="comma-separated name substrings to filter a scan")
    p.add_argument("--scan-timeout", type=float, default=10.0)
    p.add_argument("--dwell", type=float, default=2.5, help="seconds per visual step")
    p.add_argument("--quick", action="store_true", help="shorter 0..15 sweeps")
    p.add_argument("--rigorous", action="store_true",
                   help="device-CONFIRMED checks (brightness read-back, query round-trips)")
    p.add_argument("--report", default=str(ROOT / "test_reports" / "device_validation.json"))
    p.add_argument("--socket", help="path to UNIX domain socket for validation via running app")
    p.add_argument("--server", help="URL to HTTP control server for validation via running app")
    p.add_argument("--token", help="optional auth token for control server")
    args = p.parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
