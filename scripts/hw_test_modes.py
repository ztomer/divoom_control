#!/usr/bin/env python3
"""hw_test_modes.py — DETERMINISTIC hardware mode test over the daemon socket.

Drives a RUNNING daemon (pure socket IPC — no BLE in THIS process, so it runs from
any shell without a TCC crash; the daemon does the Bluetooth). It walks every
device channel/mode + the core controls with FIXED arguments and, where a getter
exists, read-back assertions — recording per-step pass/fail to a JSON report.

Deterministic by design: a fixed step list, fixed values, fixed order, no
randomness. The only non-determinism (BLE advertising) is contained to discovery,
which retries on a fixed budget; pass --mac to skip discovery entirely. Idempotent
— it leaves the device on clock face 0 at brightness 60.

Usage:
    divoom-control daemon                 # in a BT-granted terminal (or ./run.sh)
    python3 scripts/hw_test_modes.py                 # connected / first device
    python3 scripts/hw_test_modes.py --mac <ADDR>    # target one device
    python3 scripts/hw_test_modes.py --all           # every discovered device
    python3 scripts/hw_test_modes.py --dwell 2.0 --quick

Exit code 0 iff every step passed.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from pathlib import Path

# ── kare style (TTY-aware), matching scripts/hw_smoke.py ───────────────────
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


DEFAULT_SOCKET = "/tmp/divoom.sock"


class Daemon:
    """One short-lived request/response per call over the NDJSON unix socket."""

    def __init__(self, path: str, timeout: float = 40.0):
        self.path = path
        self.timeout = timeout

    def call(self, command: str, args: dict | None = None) -> dict:
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(self.timeout)
        s.connect(self.path)
        try:
            s.sendall(json.dumps({"command": command, "args": args or {}}).encode() + b"\n")
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(8192)
                if not chunk:
                    break
                buf += chunk
        finally:
            s.close()
        return json.loads(buf.decode())

    def dc(self, method: str, args: list | None = None) -> dict:
        return self.call("device_call", {"method": method, "args": args or []})

    def dc_kw(self, method: str, kwargs: dict) -> dict:
        return self.call("device_call", {"method": method, "args": [], "kwargs": kwargs})


def _reply_ok(r: dict) -> bool:
    return isinstance(r, dict) and r.get("success") is True


# ── deterministic test frames ──────────────────────────────────────────────
def _solid(rgb: tuple[int, int, int]) -> list[int]:
    return list(rgb) * (16 * 16)


def _gradient() -> list[int]:
    out: list[int] = []
    for i in range(16 * 16):
        x, y = i % 16, i // 16
        out += [x * 16, y * 16, ((x + y) * 8) & 0xFF]
    return out


def discover(d: Daemon, timeout: int, retries: int) -> list[tuple[str, str]]:
    """Scan with a fixed retry budget (advertising is intermittent)."""
    for attempt in range(1, retries + 1):
        info(f"scan {attempt}/{retries} ({timeout}s)…")
        r = d.call("scan", {"timeout": timeout})
        devs = [(x.get("name") or "?", x.get("address") or x.get("mac"))
                for x in r.get("devices", []) if (x.get("address") or x.get("mac"))]
        if devs:
            return devs
    return []


def build_steps(quick: bool) -> list[dict]:
    """The fixed step list. Each: group, name, kind, payload, [expect]."""
    clock_faces = [0, 1, 2] if quick else [0, 1, 2, 3, 4, 5]
    viz = [0, 1] if quick else [0, 1, 2]
    steps: list[dict] = []

    # controls — with read-back assertions where a getter exists
    for b in ([20, 80] if quick else [20, 60, 100]):
        steps.append({"group": "controls", "name": f"brightness {b}",
                      "kind": "dc", "method": "device.set_brightness", "args": [b],
                      "expect": ("get_brightness", b)})
    steps.append({"group": "controls", "name": "volume 8",
                  "kind": "dc", "method": "music.set_volume", "args": [8],
                  "expect": ("get_volume", 8)})  # None on speaker-less devices → n/a

    # clock channel (multiple faces)
    for f in clock_faces:
        steps.append({"group": "clock", "name": f"clock face {f}",
                      "kind": "dc", "method": "display.show_clock", "args": [f], "dwell": True})
    steps.append({"group": "clock", "name": "clock_rich 24h green",
                  "kind": "dc_kw", "method": "display.set_clock_rich",
                  "kwargs": {"style": 0, "twentyfour": 1, "color": "#00cc66"}, "dwell": True})

    # visualizer / EQ
    for v in viz:
        steps.append({"group": "visualizer", "name": f"visualization {v}",
                      "kind": "dc", "method": "display.show_visualization", "args": [v], "dwell": True})
    # VJ effects
    for e in ([0] if quick else [0, 1]):
        steps.append({"group": "vj", "name": f"effects {e}",
                      "kind": "dc", "method": "display.show_effects", "args": [e], "dwell": True})
    # ambient light (colorHex, brightness)
    for hexc in (["#ff0000"] if quick else ["#ff0000", "#0000ff", "#00ff00"]):
        steps.append({"group": "ambient", "name": f"light {hexc}",
                      "kind": "dc", "method": "display.show_light", "args": [hexc, 80], "dwell": True})
    # scoreboard (on_off, red, blue)
    steps.append({"group": "scoreboard", "name": "scoreboard 3:5",
                  "kind": "dc", "method": "set_scoreboard", "args": [1, 3, 5], "dwell": True})
    # custom image push (w,h,time_ms,rgb)
    steps.append({"group": "image", "name": "image solid red",
                  "kind": "dc_kw", "method": "show_image",
                  "kwargs": {"w": 16, "h": 16, "time_ms": 1000, "rgb": _solid((220, 30, 30))}, "dwell": True})
    if not quick:
        steps.append({"group": "image", "name": "image gradient",
                      "kind": "dc_kw", "method": "show_image",
                      "kwargs": {"w": 16, "h": 16, "time_ms": 1000, "rgb": _gradient()}, "dwell": True})

    # leave the device in a known state
    steps.append({"group": "reset", "name": "clock face 0", "kind": "dc",
                  "method": "display.show_clock", "args": [0]})
    steps.append({"group": "reset", "name": "brightness 60", "kind": "dc",
                  "method": "device.set_brightness", "args": [60], "expect": ("get_brightness", 60)})
    return steps


def run_steps(d: Daemon, steps: list[dict], dwell: float) -> list[dict]:
    results: list[dict] = []
    group = None
    for s in steps:
        if s["group"] != group:
            group = s["group"]
            print(f"\n  {_BOLD}[{group}]{_RESET}")
        # send
        if s["kind"] == "dc":
            r = d.dc(s["method"], s.get("args"))
        else:
            r = d.dc_kw(s["method"], s["kwargs"])
        sent_ok = _reply_ok(r)
        passed = sent_ok
        detail = ""
        # optional read-back assertion
        if sent_ok and "expect" in s:
            getter, want = s["expect"]
            time.sleep(0.5)
            gr = d.dc(getter)
            got = gr.get("result") if isinstance(gr, dict) else None
            if got is None:
                detail = f"{getter}=n/a"  # e.g. volume on a speaker-less device
            elif got == want:
                detail = f"{getter}={got}"
            else:
                passed = False
                detail = f"{getter}={got} != {want}"
        line = s["name"] + (f"  ({detail})" if detail else "")
        (ok if passed else err)(line if passed else f"{line}  reply={r}")
        results.append({"group": s["group"], "name": s["name"], "method": s["method"],
                        "passed": passed, "detail": detail, "reply": r})
        if s.get("dwell"):
            time.sleep(dwell)
    return results


def test_device(d: Daemon, name: str, mac: str, dwell: float, quick: bool) -> dict:
    section(f"Device: {name}  ({mac})")
    cr = d.call("connect", {"mac": mac})
    if not _reply_ok(cr):
        err(f"connect failed: {cr}")
        return {"device": name, "mac": mac, "connected": False, "steps": []}
    time.sleep(1.0)
    nm = d.dc("get_device_name").get("result")
    info(f"connected — device reports name: {nm!r}")
    steps = run_steps(d, build_steps(quick), dwell)
    npass = sum(1 for s in steps if s["passed"])
    return {"device": name, "mac": mac, "connected": True,
            "passed": npass, "total": len(steps), "steps": steps}


def main() -> int:
    ap = argparse.ArgumentParser(description="Deterministic hardware mode test (daemon socket).")
    ap.add_argument("--socket", default=DEFAULT_SOCKET)
    ap.add_argument("--mac", help="target one device by address (skips discovery)")
    ap.add_argument("--all", action="store_true", help="test every discovered device")
    ap.add_argument("--dwell", type=float, default=1.5, help="seconds to hold each visual step")
    ap.add_argument("--scan-timeout", type=int, default=15)
    ap.add_argument("--scan-retries", type=int, default=3)
    ap.add_argument("--quick", action="store_true", help="shorter sweeps")
    ap.add_argument("--report", default="test_reports/hw_modes.json")
    args = ap.parse_args()

    d = Daemon(args.socket)
    section("Divoom hardware mode test — daemon socket")
    try:
        st = d.call("device_status")
    except (FileNotFoundError, ConnectionRefusedError, socket.error) as e:
        err(f"daemon not reachable at {args.socket}: {e}")
        err("start it first: ./run.sh  (or: divoom-control daemon)")
        return 2

    # Resolve target device(s) deterministically.
    targets: list[tuple[str, str]] = []
    if args.mac:
        targets = [("(by --mac)", args.mac)]
    elif args.all:
        targets = discover(d, args.scan_timeout, args.scan_retries)
    elif st.get("connected") and st.get("mac"):
        targets = [("(connected)", st["mac"])]
    else:
        targets = discover(d, args.scan_timeout, args.scan_retries)[:1]

    if not targets:
        err("no devices found (power one on / wake it, or pass --mac). Scan is "
            "best-effort; the test logic itself is deterministic given a connection.")
        return 2

    report = {"socket": args.socket, "quick": args.quick, "devices": []}
    all_pass = True
    for name, mac in targets:
        res = test_device(d, name, mac, args.dwell, args.quick)
        report["devices"].append(res)
        if not res.get("connected") or res.get("passed", 0) != res.get("total", -1):
            all_pass = False

    # summary + JSON report
    section("Summary")
    for res in report["devices"]:
        if not res.get("connected"):
            err(f"{res['device']} {res['mac']} — connect FAILED")
            continue
        p, t = res["passed"], res["total"]
        (ok if p == t else err)(f"{res['device']} {res['mac']} — {p}/{t} steps passed")
        for s in res["steps"]:
            if not s["passed"]:
                err(f"    {s['group']}/{s['name']}: {s['reply']}")
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    info(f"report → {out}")
    (ok if all_pass else err)("ALL PASSED" if all_pass else "FAILURES — see above")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
