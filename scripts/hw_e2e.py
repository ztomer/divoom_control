#!/usr/bin/env python3
"""hw_e2e.py — end-to-end scenarios against REAL hardware, driven over the
daemon socket.

Pure NDJSON IPC. No BLE is touched in this process, so it runs from any shell
without a macOS TCC crash; the daemon (a Bluetooth-granted process) owns the
radio. Start one with `open "dist/Divoom Dev Daemon.app"` (see
scripts/make_dev_daemon_app.sh) or let the GUI spawn it.

R67: written because the reported defects (ambient modes, clock overlays, hot
channel, weather) are all things a green unit suite cannot see — they are wire
payloads and device state. Every scenario ends with a RESTORE step so a failed
run does not leave the device parked somewhere odd.

Every run asserts, before and after, that exactly ONE divoomd is alive: two
daemons fighting for a single-owner device is the failure this repo just spent a
round diagnosing, and a harness that tolerates it measures the wrong machine.

Usage:
    hw_e2e.py --list                      # discover devices, exit
    hw_e2e.py --scenario ambient          # one scenario
    hw_e2e.py --scenario all --device Pixoo-1
    hw_e2e.py --preflight                 # just the environment assertions
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import time

sys.path.insert(0, os.environ.get("GOH_DIR", os.path.expanduser("~/Projects/gates_of_heck")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tui.lib import err, hr, info, ok, section, warn  # noqa: E402

from daemon_ping import live_daemons  # noqa: E402

DEFAULT_SOCKET = "/tmp/divoom.sock"
DEFAULT_TRACE = "/tmp/divoom_dev_daemon.log"
# Ambient lighting types, per divoom_lib/models/constants_scheduling.py.
AMBIENT_MODES = [(0, "Plain"), (1, "Love"), (2, "Plants"), (3, "Sleeping"), (4, "No-Mosquito")]

# `[ble] tx cmd=0x45 (10 args) 0100ffcc500001000000`
TX_RE = re.compile(r"\[ble\] tx cmd=0x([0-9a-f]{2}) \(\d+ args\)\s*([0-9a-f]*)")


class TxTrace:
    """Reads the daemon's `DIVOOMD_BLE_DEBUG` wire trace.

    This is the difference between a harness that can see the R67 defects and
    one that cannot. `device_call` returns success whenever the BLE write
    succeeds — which it does even when the payload has the wrong byte in it. The
    RPC result is therefore blind to exactly the class of bug this round is
    about, and only the outbound bytes settle it (trace-the-boundary).

    Absent trace file -> `available` is False and callers must DOWNGRADE their
    claim rather than silently pass.
    """

    def __init__(self, path: str = DEFAULT_TRACE):
        self.path = path
        self._pos = 0

    @property
    def available(self) -> bool:
        return os.path.exists(self.path)

    def mark(self) -> None:
        """Remember where the log ends, so the next read returns only new lines."""
        try:
            self._pos = os.path.getsize(self.path)
        except OSError:
            self._pos = 0

    def frames(self, cmd: int | None = None) -> list[tuple[int, str]]:
        """(command_id, payload_hex) written since the last mark()."""
        try:
            with open(self.path, encoding="utf-8", errors="replace") as f:
                f.seek(self._pos)
                text = f.read()
        except OSError:
            return []
        out = []
        for m in TX_RE.finditer(text):
            cid, hx = int(m.group(1), 16), m.group(2)
            if cmd is None or cid == cmd:
                out.append((cid, hx))
        return out


class DaemonError(RuntimeError):
    pass


class Daemon:
    """One NDJSON request per connection — the same shape every other client
    uses, so the harness exercises the real server path, not a private one."""

    def __init__(self, sock_path: str = DEFAULT_SOCKET, timeout: float = 60.0):
        self.sock_path = sock_path
        self.timeout = timeout

    def call(self, command: str, timeout: float | None = None, **args) -> dict:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout or self.timeout)
        try:
            s.connect(self.sock_path)
            s.sendall((json.dumps({"command": command, "args": args}) + "\n").encode())
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(1 << 16)
                if not chunk:
                    break
                buf += chunk
        except OSError as e:
            raise DaemonError(f"{command}: {e}") from e
        finally:
            s.close()
        if not buf:
            raise DaemonError(f"{command}: empty reply")
        return json.loads(buf.decode())

    def device_call(self, method: str, args: list | None = None,
                    kwargs: dict | None = None, timeout: float | None = None) -> dict:
        return self.call("device_call", timeout=timeout, method=method,
                         args=args or [], kwargs=kwargs or {})


# ── environment assertions ────────────────────────────────────────────────
def preflight(d: Daemon) -> bool:
    section("Preflight")
    procs = live_daemons()
    if len(procs) > 1:
        err(f"{len(procs)} divoomd alive — a single-owner device cannot have two owners")
        for pid, cmd in procs:
            info(f"pid {pid}: {cmd}")
        return False
    if not procs:
        err("no divoomd running — start one: open 'dist/Divoom Dev Daemon.app'")
        return False
    ok(f"exactly one divoomd (pid {procs[0][0]})")
    try:
        st = d.call("get_status", timeout=5)
    except DaemonError as e:
        err(f"daemon not answering on {d.sock_path}: {e}")
        return False
    ok(f"daemon reachable (uptime {st.get('uptime_s')}s)")
    return True


def pick_device(d: Daemon, want: str | None) -> dict | None:
    info("scanning...")
    reply = d.call("scan", timeout=45, duration=6)
    devices = reply.get("devices", [])
    if not devices:
        err("no devices found")
        return None
    for dev in devices:
        ok(f"{dev['name']}  {dev['address']}")
    if want:
        for dev in devices:
            if want.lower() in dev["name"].lower():
                return dev
        err(f"requested device not found: {want}")
        return None
    return devices[0]


def ensure_connected(d: Daemon, dev: dict) -> bool:
    st = d.call("device_status")
    if st.get("connected") and st.get("mac") == dev["address"]:
        ok(f"already connected to {dev['name']}")
        return True
    info(f"connecting to {dev['name']}...")
    t0 = time.monotonic()
    reply = d.call("connect", timeout=90, id=dev["address"])
    if not reply.get("success"):
        err(f"connect failed: {reply.get('error')}")
        return False
    ok(f"connected in {time.monotonic() - t0:.1f}s")
    return True


# ── scenarios ─────────────────────────────────────────────────────────────
# Each returns True on success. Each is DESTRUCTIVE to what is on screen and
# restores a neutral state at the end, so a failure mid-run is still tidy.

def scenario_ambient(d: Daemon, dwell: float, trace: TxTrace) -> bool:
    """Every ambient mode must reach the device as a DISTINCT 0x45 payload.

    R67/C1: the Rust handler hardcoded the lighting-type byte to 0x00, so all
    five modes sent identical Plain-Colour packets while every RPC returned
    success. The assertion that catches this is on the wire bytes, not the
    reply: five modes must produce five different payloads.
    """
    section("Ambient modes")
    if not trace.available:
        err(f"no wire trace at {trace.path} — cannot verify payloads")
        info("start the daemon via: scripts/make_dev_daemon_app.sh (sets DIVOOMD_BLE_DEBUG)")
        return False

    passed = True
    sent: dict[int, str] = {}
    for mode, name in AMBIENT_MODES:
        trace.mark()
        reply = d.device_call("display.show_light", args=["#00FFCC", 80, True, mode])
        if not reply.get("success"):
            err(f"mode {mode} ({name}): {reply.get('error')}")
            passed = False
            continue
        time.sleep(0.4)  # let the daemon flush its trace line
        frames = trace.frames(cmd=0x45)
        if not frames:
            err(f"mode {mode} ({name}): RPC succeeded but NO 0x45 frame was written")
            passed = False
            continue
        payload = frames[-1][1]
        sent[mode] = payload
        ok(f"mode {mode} ({name}): tx 0x45 {payload}")
        time.sleep(dwell)

    hr()
    distinct = set(sent.values())
    if len(sent) > 1 and len(distinct) == 1:
        err(f"all {len(sent)} modes sent the SAME payload {distinct.pop()}"
            " — the mode byte is being dropped")
        return False
    if len(distinct) != len(sent):
        err(f"{len(sent)} modes produced only {len(distinct)} distinct payloads")
        passed = False
    else:
        ok(f"{len(sent)} modes produced {len(distinct)} distinct payloads")
    info("LOOK AT THE PANEL: modes 1-4 must differ from mode 0 and from each other.")
    return passed


def scenario_clock(d: Daemon, dwell: float, trace: TxTrace) -> bool:
    """Clock overlays, one at a time, asserted against the canonical slot order.

    R67/C1: `display.show_clock` had humidity/weather/date in the wrong payload
    slots, so asking for weather turned on humidity. Toggling ONE overlay at a
    time is what makes a swapped pair visible; toggling them together does not.

    Canonical wire layout (divoom_lib/display/__init__.py, from the APK's C2()):
        [env, twentyfour, style, active, humidity, weather, date, R, G, B]
    so byte 4 is humidity, 5 is weather, 6 is date.
    """
    section("Clock overlays")
    if not trace.available:
        err(f"no wire trace at {trace.path} — cannot verify slot order")
        return False

    passed = True
    cases = [
        ({"humidity": False, "weather": False, "date": False}, "bare clock", None),
        ({"humidity": True, "weather": False, "date": False}, "humidity ONLY", 4),
        ({"humidity": False, "weather": True, "date": False}, "weather ONLY", 5),
        ({"humidity": False, "weather": False, "date": True}, "date ONLY", 6),
    ]
    for kwargs, label, hot_byte in cases:
        trace.mark()
        reply = d.device_call("display.show_clock",
                              kwargs={"clock": 0, "color": "#FFFFFF", **kwargs})
        if not reply.get("success"):
            err(f"{label}: {reply.get('error')}")
            passed = False
            continue
        time.sleep(0.4)
        frames = trace.frames(cmd=0x45)
        if not frames:
            err(f"{label}: RPC succeeded but no 0x45 frame written")
            passed = False
            continue
        payload = frames[-1][1]
        raw = bytes.fromhex(payload) if len(payload) % 2 == 0 else b""
        ok(f"{label}: tx 0x45 {payload}")
        if hot_byte is not None and len(raw) > 6:
            overlays = {4: raw[4], 5: raw[5], 6: raw[6]}
            wrong = [i for i, v in overlays.items() if (v != 0) != (i == hot_byte)]
            if wrong:
                err(f"  overlay bytes {overlays} — expected only byte {hot_byte} set")
                passed = False
            else:
                ok(f"  overlay byte {hot_byte} set, others clear")
        info(f"  panel must show EXACTLY: {label}")
        time.sleep(dwell)
    return passed


def scenario_clock_color(d: Daemon, dwell: float, trace: TxTrace) -> bool:
    """The clock colour must be honoured. `device.show_clock` hardcoded white."""
    section("Clock colour")
    passed = True
    for color, name in (("#FF0000", "red"), ("#00FF00", "green"), ("#0000FF", "blue")):
        reply = d.device_call("display.show_clock", kwargs={"clock": 0, "color": color})
        good = bool(reply.get("success"))
        (ok if good else err)(f"{name}: {'sent' if good else reply.get('error')}")
        passed &= good
        time.sleep(dwell)
    info("LOOK AT THE PANEL: the clock must have changed colour three times.")
    return passed


def scenario_hot(d: Daemon) -> bool:
    """Hot-channel update must report progress, not sit silent.

    R67/C6: the daemon stored progress and never broadcast it, so the UI hung on
    'Preparing...'. This subscribes to the event stream FIRST and fails if no
    hot_progress event arrives — the assertion the GUI could not make.
    """
    section("Hot channel update")
    events: list[dict] = []
    sub = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sub.settimeout(180)
    sub.connect(d.sock_path)
    sub.sendall(b'{"command":"subscribe","args":{}}\n')

    size = 16
    started = d.call("hot_update", timeout=30, device_size=size, show=True, address="")
    if not started.get("success"):
        err(f"hot_update did not start: {started.get('error')}")
        sub.close()
        return False
    ok("hot_update started")

    deadline = time.monotonic() + 180
    buf = b""
    terminal = None
    while time.monotonic() < deadline and terminal is None:
        try:
            chunk = sub.recv(1 << 16)
        except socket.timeout:
            break
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, _, buf = buf.partition(b"\n")
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") != "hot_progress":
                continue
            events.append(ev)
            info(f"  phase={ev.get('phase')} {ev.get('current', '')}/{ev.get('total', '')}")
            if ev.get("phase") in ("done", "error"):
                terminal = ev
    sub.close()

    if not events:
        err("NO hot_progress events arrived — the UI would hang on 'Preparing...'")
        return False
    ok(f"{len(events)} hot_progress events")
    if terminal is None:
        err("no terminal (done/error) event — the UI button would stay disabled")
        return False
    ok(f"terminal phase: {terminal.get('phase')}")
    return terminal.get("phase") == "done"


def scenario_reconnect(d: Daemon, dev: dict, iterations: int) -> bool:
    """Connect/disconnect soak. Asserts one daemon throughout — a second one
    appearing mid-soak is the reliability bug, not a flake."""
    section(f"Reconnect soak ({iterations}x)")
    passed = True
    for i in range(1, iterations + 1):
        d.call("disconnect", timeout=30)
        time.sleep(0.5)
        t0 = time.monotonic()
        reply = d.call("connect", timeout=90, id=dev["address"])
        dt = time.monotonic() - t0
        good = bool(reply.get("success"))
        (ok if good else err)(f"cycle {i}: {'reconnected' if good else reply.get('error')} in {dt:.1f}s")
        passed &= good
        if len(live_daemons()) != 1:
            err("daemon count changed mid-soak — single-owner violated")
            return False
    return passed


def restore(d: Daemon) -> None:
    """Leave the device on a neutral, obviously-alive state."""
    section("Restore")
    try:
        d.device_call("display.show_clock", kwargs={"clock": 0, "color": "#FFFFFF"})
        ok("device parked on the clock channel")
    except DaemonError as e:
        warn(f"restore failed: {e}")


SCENARIOS = {
    "ambient": lambda d, a, dev, t: scenario_ambient(d, a.dwell, t),
    "clock": lambda d, a, dev, t: scenario_clock(d, a.dwell, t),
    "clock-color": lambda d, a, dev, t: scenario_clock_color(d, a.dwell, t),
    "hot": lambda d, a, dev, t: scenario_hot(d),
    "reconnect": lambda d, a, dev, t: scenario_reconnect(d, dev, a.iterations),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--socket", default=DEFAULT_SOCKET)
    ap.add_argument("--trace", default=DEFAULT_TRACE,
                    help="daemon DIVOOMD_BLE_DEBUG log to assert wire bytes against")
    ap.add_argument("--device", default=None, help="substring of the device name")
    ap.add_argument("--scenario", default="all",
                    help="one of: " + ", ".join(SCENARIOS) + ", or 'all'")
    ap.add_argument("--dwell", type=float, default=3.0,
                    help="seconds to hold each visual state so it can be seen")
    ap.add_argument("--iterations", type=int, default=5, help="reconnect soak cycles")
    ap.add_argument("--list", action="store_true", help="discover devices and exit")
    ap.add_argument("--preflight", action="store_true", help="environment checks only")
    args = ap.parse_args()

    d = Daemon(args.socket)
    trace = TxTrace(args.trace)
    if not preflight(d):
        return 1
    if args.preflight:
        return 0

    if args.list:
        section("Devices")
        return 0 if pick_device(d, None) else 1

    section("Device")
    dev = pick_device(d, args.device)
    if not dev or not ensure_connected(d, dev):
        return 1

    names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    unknown = [n for n in names if n not in SCENARIOS]
    if unknown:
        err(f"unknown scenario(s): {', '.join(unknown)}")
        return 2

    results: dict[str, bool] = {}
    try:
        for name in names:
            try:
                results[name] = bool(SCENARIOS[name](d, args, dev, trace))
            except DaemonError as e:
                err(f"{name}: {e}")
                results[name] = False
    finally:
        restore(d)
        if len(live_daemons()) != 1:
            err("more than one divoomd alive at exit")
            results["single-owner"] = False

    section("Summary")
    for name, good in results.items():
        (ok if good else err)(name)
    hr()
    failed = [n for n, g in results.items() if not g]
    if failed:
        err(f"{len(failed)} failed: {', '.join(failed)}")
        return 1
    ok("all scenarios passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
