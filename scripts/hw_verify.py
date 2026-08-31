#!/usr/bin/env python3
"""Hardware verification packet — the checks only a human looking at a device can make.

Every automated test in this repo stops at the socket: it asserts the daemon's
REPLY and never the pixels. That is why sysmon, the album cover and
`pic_scan_ctrl` have all been "verified" and simultaneously unwatched for
rounds. This script is the other half — it drives the device and asks you what
you SEE, then writes down the answer.

    scripts/hw_verify.py --list            # what it will ask
    scripts/hw_verify.py                   # run the packet
    scripts/hw_verify.py --only sysmon     # one check
    scripts/hw_verify.py --self-test       # prove it can report FAILURE
    scripts/hw_verify.py --out report.json # where the verdicts land

**START THE DAEMON YOURSELF. This script will not do it, by design.**
macOS Bluetooth TCC is granted per RESPONSIBLE PROCESS, so a daemon spawned
from a shell has no grant and dies on its first BLE scan with SIGABRT and an
EMPTY stderr. It looks exactly like a product crash and is not one. Launch the
GUI (which owns the grant) or start the daemon from an app that has it, then
point this at its socket.

**It cannot pass by silence.** A LOOK check with nobody watching is recorded
UNKNOWN, never PASS — if stdin is not a terminal the packet refuses to invent
verdicts. `--self-test` exists so the instrument is calibrated before its
answers are trusted: it drives a check that MUST fail and reports whether the
packet noticed.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))
from _tui import err, hr, info, ok, section, warn  # noqa: E402

from divoom_client.daemon_protocol import DEFAULT_SOCKET_PATH, DaemonClient  # noqa: E402

PASS, FAIL, SKIP, UNKNOWN = "PASS", "FAIL", "SKIP", "UNKNOWN"


@dataclass
class Result:
    check: str
    verdict: str
    detail: str = ""
    note: str = ""


@dataclass
class Check:
    id: str
    title: str
    look: str                     # what the operator should SEE
    needs_device: bool = True
    tags: list[str] = field(default_factory=list)

    def drive(self, client: DaemonClient) -> tuple[bool, str]:
        raise NotImplementedError


@dataclass
class CallCheck(Check):
    """Fire one device_call, then ask what appeared on the panel."""
    method: str = ""
    args: list = field(default_factory=list)
    settle: float = 1.5

    def drive(self, client):
        reply = client.device_call(self.method, self.args)
        time.sleep(self.settle)
        if not isinstance(reply, dict):
            return False, f"non-dict reply: {reply!r}"
        if reply.get("success") is False:
            return False, str(reply.get("error") or reply)
        return True, json.dumps(reply)[:200]


@dataclass
class CommandCheck(Check):
    """Fire one socket command (not a device call)."""
    command: str = ""
    cargs: dict = field(default_factory=dict)
    needs_device: bool = False

    def drive(self, client):
        reply = client.send_command(self.command, self.cargs)
        if not isinstance(reply, dict):
            return False, f"non-dict reply: {reply!r}"
        if reply.get("success") is False:
            return False, str(reply.get("error") or reply)
        return True, json.dumps(reply)[:200]


def build_checks() -> list[Check]:
    """The packet. Each entry names what a person must SEE, not what returned 0."""
    return [
        CallCheck(
            id="sysmon", tags=["P2.2"],
            title="System-monitor gauges on a matrix",
            look="CPU / RAM bars on the device, and the values MOVING over ~10s "
                 "(a frozen plausible number looks identical to a working one)",
            method="live_jobs.start", args=["sysmon"], settle=10.0,
        ),
        CallCheck(
            id="album_art", tags=["P2.3", "R12"],
            title="Album cover on the device",
            look="the current track's cover art, NEAREST-scaled (blocky, not "
                 "smoothed) and matching the GUI preview pixel for pixel",
            method="media.push_album_art", args=[],
        ),
        CallCheck(
            id="custom_art", tags=["P2.3", "R12"],
            title="Custom art (local image) on the device",
            look="the image you picked, right way up, filling the panel",
            method="display.show_image", args=[],
        ),
        CallCheck(
            id="weather", tags=["P2.3", "R12"],
            title="Weather widget on the device",
            look="the weather face with a plausible temperature for your city",
            method="display.show_weather", args=[],
        ),
        CallCheck(
            id="pic_scan", tags=["P2.4"],
            title="pic_scan_ctrl 0x35 — UNVERIFIED since 2026-07-13",
            look="ANY change on the panel. The BLE stack has always accepted "
                 "this command without error and nobody has ever seen it do "
                 "something. If nothing happens, answer n — that is the finding, "
                 "and it gets marked unsupported rather than shipped as working",
            method="drawing.pic_scan_ctrl", args=[0],
        ),
        CallCheck(
            id="clock_rich", tags=["P2.5", "P1.3"],
            title="set_clock_rich — humidity + weather + date overlays",
            look="a clock face that ALSO shows humidity, weather and the date. "
                 "The wired set_clock cannot do this; if the device ignores the "
                 "extras, the method is worth deleting rather than wiring",
            method="display.set_clock_rich", args=[0, True, True, True, True, "#ffffff"],
        ),
        CallCheck(
            id="temp_channel", tags=["P2.5", "P1.3"],
            title="set_temperature_channel — a channel the UI never offers",
            look="the device switching to its temperature display, in Celsius",
            method="display.set_temperature_channel", args=[True, "#ffffff"],
        ),
        CallCheck(
            id="timeplan", tags=["P2.5", "P1.3"],
            title="set_timeplan — scheduled channel switch",
            look="nothing immediately. Set it a minute ahead and confirm the "
                 "device switches channel ON ITS OWN when that minute arrives",
            method="timeplan.set_time_manage_info", args=[1, 0, 0, 0, 0, 0, 0, 10, 0],
            settle=2.0,
        ),
        CommandCheck(
            id="weather_city", tags=["P2.6"],
            title="search_weather_city on the CONFIGURED account",
            look="a non-empty list of cities. The pre-release check ran under a "
                 "throwaway HOME and only ever proved the RC=10 guest-login "
                 "error path",
            command="search_weather_city", cargs={"keyword": "London"},
        ),
    ]


def ask(prompt: str, interactive: bool) -> tuple[str, str]:
    """PASS / FAIL / SKIP from a human, or UNKNOWN when nobody is watching."""
    if not interactive:
        return UNKNOWN, "no tty — nobody was looking"
    while True:
        raw = input(f"    {prompt} [y = saw it / n = did not / s = skip] ").strip().lower()
        if raw in ("y", "yes"):
            return PASS, input("    note (optional): ").strip()
        if raw in ("n", "no"):
            return FAIL, input("    what DID you see? ").strip()
        if raw in ("s", "skip", ""):
            return SKIP, input("    why skipped: ").strip()


def require_daemon(socket_path: str) -> DaemonClient:
    """Connect, or explain why this script will not start one itself."""
    client = DaemonClient(socket_path)
    # DaemonClient does NOT raise for an absent socket -- it returns
    # {"success": False, "unreachable": True, ...}. The first version of this
    # guard only caught exceptions, so it never fired and the packet would have
    # run every check against a dead socket without once printing the TCC
    # explanation below, which is the whole reason the guard exists.
    reason = ""
    try:
        st = client.device_status()
        if isinstance(st, dict) and (st.get("unreachable") or st.get("success") is False):
            reason = str(st.get("error") or st)
    except Exception as exc:
        reason = str(exc)
    if reason:
        err(f"no daemon on {socket_path} ({reason})")
        info("This script does NOT start a daemon, deliberately: macOS grants")
        info("Bluetooth per RESPONSIBLE PROCESS, so a shell-launched daemon has")
        info("no grant and dies on its first scan with SIGABRT and an EMPTY")
        info("stderr — which reads as a product crash and is not one.")
        info("Launch the GUI (it owns the grant), then re-run this.")
        raise SystemExit(2)
    return client


def device_connected(client: DaemonClient) -> tuple[bool, str]:
    try:
        st = client.device_status()
    except Exception as exc:
        return False, str(exc)
    if not isinstance(st, dict):
        return False, f"unexpected status: {st!r}"
    mac = st.get("mac")
    return bool(st.get("connected")), f"mac={mac} connected={st.get('connected')}"


def run_packet(client, checks, interactive, results):
    connected, detail = device_connected(client)
    if connected:
        ok(f"device connected — {detail}")
    else:
        warn(f"NO DEVICE CONNECTED — {detail}")
        warn("  device checks will be recorded FAIL, not skipped: a packet that")
        warn("  goes quiet when the hardware is absent is a form, not a check.")

    for c in checks:
        section(f"[{c.id}] {c.title}")
        if c.needs_device and not connected:
            err("no device connected")
            results.append(Result(c.id, FAIL, "no device connected"))
            continue
        try:
            fired, detail = c.drive(client)
        except Exception as exc:
            err(f"call raised: {exc}")
            results.append(Result(c.id, FAIL, f"raised: {exc}"))
            continue
        if not fired:
            err(f"command rejected: {detail}")
            results.append(Result(c.id, FAIL, detail))
            continue
        info(f"sent OK — {detail}")
        info("LOOK AT THE DEVICE:")
        for line in c.look.split(". "):
            info(f"  {line}")
        verdict, note = ask("did you see it?", interactive)
        results.append(Result(c.id, verdict, detail, note))
        (ok if verdict == PASS else warn if verdict in (SKIP, UNKNOWN) else err)(
            f"{c.id}: {verdict}")


def self_test(client) -> int:
    """P2.1 — prove the packet can say NO before trusting it when it says yes."""
    section("self-test: can this packet report FAILURE?")
    probe = CallCheck(id="_probe", title="deliberately invalid device call",
                      look="n/a", method="definitely.not.a.real.method", args=[])
    fired, detail = probe.drive(client)
    if fired:
        err("an invalid device_call was reported as SUCCESS")
        info(f"  reply: {detail}")
        info("  The packet cannot distinguish a working command from a bogus")
        info("  one, so none of its PASS verdicts mean anything. Fix this")
        info("  before trusting a single result.")
        return 1
    connected, cdetail = device_connected(client)
    # WHY it failed matters as much as THAT it failed. With no device attached
    # the daemon refuses at the precondition before it ever looks at the method
    # name -- so a green line here would be reporting the wrong property, which
    # is the exact mistake this self-test exists to catch.
    precondition_refusal = "no device" in detail.lower()
    if precondition_refusal:
        warn("call failed, but on the NO-DEVICE precondition, not the bogus name")
        info(f"  daemon said: {detail}")
        info("  So 'the packet rejects an invalid method' is still UNTESTED.")
        info("  Connect a device and re-run --self-test to exercise it.")
    else:
        ok("invalid method correctly reported as failure")
        info(f"  daemon said: {detail}")

    if connected:
        info(f"device IS connected ({cdetail}) — the no-device path is untested")
        info("  disconnect it and re-run --self-test to exercise that branch too")
    else:
        ok(f"no device connected ({cdetail}) — device checks would record FAIL")

    if precondition_refusal and not connected:
        warn("PARTIAL calibration: one branch proven, one still owed.")
        return 3
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--socket", default=DEFAULT_SOCKET_PATH)
    ap.add_argument("--only", action="append", default=[],
                    help="run only these check ids (repeatable)")
    ap.add_argument("--list", action="store_true", help="list checks and exit")
    ap.add_argument("--self-test", action="store_true",
                    help="prove the packet can report FAILURE, then exit")
    ap.add_argument("--out", default="", help="write a JSON report here")
    args = ap.parse_args()

    checks = build_checks()
    if args.list:
        for c in checks:
            print(f"  {c.id:<14} [{','.join(c.tags)}] {c.title}")
        return 0

    client = require_daemon(args.socket)
    if args.self_test:
        return self_test(client)

    if args.only:
        wanted = set(args.only)
        unknown = wanted - {c.id for c in checks}
        if unknown:
            err(f"unknown check id(s): {', '.join(sorted(unknown))}")
            return 2
        checks = [c for c in checks if c.id in wanted]

    interactive = sys.stdin.isatty()
    if not interactive:
        warn("stdin is not a terminal — every LOOK will be recorded UNKNOWN.")
        warn("  Nothing here can PASS without a person; that is the point.")

    results: list[Result] = []
    run_packet(client, checks, interactive, results)

    section("summary")
    tally: dict[str, int] = {}
    for r in results:
        tally[r.verdict] = tally.get(r.verdict, 0) + 1
        line = f"{r.verdict:<8} {r.check}"
        (ok if r.verdict == PASS else err if r.verdict == FAIL else warn)(line)
        if r.note:
            info(f"         {r.note}")
    hr()
    info("  ".join(f"{k}={v}" for k, v in sorted(tally.items())))

    if args.out:
        Path(args.out).write_text(json.dumps(
            [r.__dict__ for r in results], indent=2), encoding="utf-8")
        ok(f"report written to {args.out}")

    return 1 if tally.get(FAIL) else 0


if __name__ == "__main__":
    sys.exit(main())
