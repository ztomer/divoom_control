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

**The expectation is the daemon's own frame, not a sentence this file wrote.**
The packet used to describe what the panel should look like, in prose, and the
prose went stale: it still said the `weather` widget "cycles" after the daemon
started drawing ONE combined frame, so a working widget was graded FAIL. Now
every panel check shows you the frame the DAEMON painted (saved next to the
report, and printed as text) and asks you to compare the panel with it. There
is nothing left here that can go stale — see `scripts/hw_expect.py`.

**Exit codes are the verdict.** 0 = every check that ran was answered (or the
self-test is calibrated), 1 = FAIL (a check failed, or the self-test could not
report a failure), 2 = the daemon is not there or the arguments are wrong,
3 = PARTIAL (a verdict was UNKNOWN or SKIP, or the self-test has one branch
proven and one still owed). A branch that RAISES is a FAIL with a non-zero
exit, never a warning: the neighbours of this file reported a NameError as
`⚠` and exited 0, so a run that had found four panels was announced as a
clean run whose reporting had failed.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "scripts"))
from _tui import err, hr, info, ok, section, warn  # noqa: E402

from divoom_client.daemon_protocol import DEFAULT_SOCKET_PATH, DaemonClient  # noqa: E402

# The packet's checks live in their own module; the runner lives here.
from hw_packet import (  # noqa: E402  (re-exported for the gates and tests)
    CallCheck,
    Check,
    CommandCheck,
    Expectation,
    ImageCheck,
    LiveJobCheck,
    PANEL_LOOK,
    build_checks,
)

PASS, FAIL, SKIP, UNKNOWN = "PASS", "FAIL", "SKIP", "UNKNOWN"
# A check that is EXPECTED to fail. XFAIL is the expected outcome and carries no
# news; XPASS means the world changed under us and is the loud one. Without this
# distinction the weather_city canary would redden every future run, and a gate
# that is always red is a gate people stop reading -- the same argument that
# makes a randomly-failing e2e suite dangerous.
XFAIL, XPASS = "XFAIL", "XPASS"

# Deliberately a big asset: the check is that the daemon's downscale lands a
# real image on a 16x16 panel intact, which a pre-shrunk 16x16 fixture would
# not exercise at all.
DEFAULT_IMAGE = REPO / "divoom_gui" / "web_ui" / "assets" / "app_icon.png"


@dataclass
class Result:
    check: str
    verdict: str
    detail: str = ""
    note: str = ""


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
        info("To drive a LOCALLY BUILT daemon, install it into the bundle:")
        info("  cp target/debug/divoomd \\")
        info("     dist/Divoom.app/Contents/Resources/bin/divoomd")
        info("  codesign --force --deep --sign - dist/Divoom.app")
        info("  open dist/Divoom.app")
        info("The grant follows com.divoom.control, not the binary (R73).")
        raise SystemExit(2)
    return client


def device_connected(client: DaemonClient) -> tuple[bool, str, dict]:
    """Connected? plus the status line, plus what the checks need FROM it.

    The third value exists because the live-widget jobs are addressed by `mac`.
    A packet that only knew "connected: true" could not start one, which is how
    the old device_call-shaped checks avoided ever learning the real API.
    """
    try:
        st = client.device_status()
    except Exception as exc:
        return False, str(exc), {}
    if not isinstance(st, dict):
        return False, f"unexpected status: {st!r}", {}
    mac = st.get("mac")
    return (bool(st.get("connected")),
            f"mac={mac} connected={st.get('connected')}",
            {"mac": mac, "size": st.get("size")})


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


def show_expectation(exp: Expectation) -> None:
    """Print the daemon's own frame for the operator to compare against."""
    for line in (exp.text or "").splitlines():
        info(f"  {line}")


def run_packet(client, checks, interactive, results, ctx=None):
    connected, detail, dev = device_connected(client)
    ctx = {**(ctx or {}), **{k: v for k, v in dev.items() if v is not None}}
    ctx.setdefault("size", 16)
    ctx.setdefault("frames_dir", tempfile.gettempdir())
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
            fired, detail = c.drive(client, ctx)
        except Exception as exc:
            err(f"call raised: {exc}")
            results.append(Result(c.id, FAIL, f"raised: {exc}"))
            continue
        if not fired:
            if c.expect_fail:
                warn(f"failed as expected — {detail}")
                info(f"  {c.expect_fail}")
                results.append(Result(c.id, XFAIL, detail, c.expect_fail))
            else:
                err(f"command rejected: {detail}")
                results.append(Result(c.id, FAIL, detail))
            continue
        if c.expect_fail:
            # The canary sang. This is the only result in the packet that is
            # more interesting when it SUCCEEDS.
            ok(f"UNEXPECTED SUCCESS — {detail}")
            info(f"  Expected to fail because: {c.expect_fail}")
            info("  That premise no longer holds. Re-check the feature.")
            results.append(Result(c.id, XPASS, detail, c.expect_fail))
            continue
        info(f"sent OK — {detail}")
        try:
            exp = c.expectation(client, ctx)
        except Exception as exc:
            err(f"expectation raised: {exc}")
            results.append(Result(c.id, FAIL, f"expectation raised: {exc}"))
            continue
        if exp.verdict:
            # The machine's own verdict. A widget that painted NOTHING cannot
            # be graded by a human looking at the panel, and a check whose
            # precondition is unmet is a SKIP, not a FAIL.
            (err if exp.verdict == FAIL else warn)(f"{c.id}: {exp.verdict} — {exp.detail}")
            results.append(Result(c.id, exp.verdict, exp.detail))
            continue
        show_expectation(exp)
        if c.setup:
            info("BEFORE YOU LOOK:")
            for line in c.setup.split(". "):
                info(f"  {line}")
        info("LOOK AT THE DEVICE:")
        for line in c.look.split(". "):
            info(f"  {line}")
        verdict, note = ask("did you see it?", interactive)
        results.append(Result(c.id, verdict, detail, note))
        (ok if verdict == PASS else warn if verdict in (SKIP, UNKNOWN) else err)(
            f"{c.id}: {verdict}")


def self_test(client) -> int:
    """P2.1 — prove the packet can say NO before trusting it when it says yes.

    The exit code IS the verdict: 0 = CALIBRATED (the packet rejects a bogus
    call AND records it as FAIL, so it would exit non-zero because of it),
    1 = FAIL (it cannot report a failure: a bogus call came back successful,
    a branch raised, or the failure was not recorded — nothing it says can be
    trusted), 3 = PARTIAL (one branch proven, one still owed: with no device
    the daemon refuses at the no-device precondition, so "the packet rejects
    an invalid method" is still untested). 3 is what the roadmap documents:
    PARTIAL until a device is connected, 0 once it is.
    """
    section("self-test: can this packet report FAILURE?")
    probe = CallCheck(id="_probe", title="deliberately invalid device call",
                      look="n/a", method="definitely.not.a.real.method", args=[],
                      needs_device=False)
    try:
        fired, detail = probe.drive(client, {})
    except Exception as exc:
        # A branch that RAISES is a FAILURE, never a warning and never an
        # unhandled crash: the packet cannot report a failure it did not
        # survive.
        err(f"the probe itself raised: {type(exc).__name__}: {exc}")
        info("  A branch that raises is a FAIL. The packet is not calibrated,")
        info("  and nothing it reports can be trusted until this is fixed.")
        return 1
    if fired:
        err("an invalid device_call was reported as SUCCESS")
        info(f"  reply: {detail}")
        info("  The packet cannot distinguish a working command from a bogus")
        info("  one, so none of its PASS verdicts mean anything. Fix this")
        info("  before trusting a single result.")
        return 1

    # The daemon's refusal is not the whole property. The property is that
    # the PACKET records the refusal as a FAIL and would exit non-zero
    # because of it — so drive the probe through the packet's own machinery
    # and read the verdict it produces, not the daemon's answer.
    results: list[Result] = []
    run_packet(client, [probe], False, results)
    recorded = [r for r in results if r.verdict == FAIL]
    if not recorded:
        err("the packet did not record the bogus call as a FAIL")
        info(f"  verdicts: {[r.verdict for r in results]}")
        info("  A packet that swallows a failure reports success it never")
        info("  earned. Fix that before trusting a single result.")
        return 1
    ok("the packet records a failed call as FAIL, and its exit code is non-zero")
    info(f"  recorded: {recorded[0].check} → {recorded[0].verdict}")

    connected, cdetail, _dev = device_connected(client)
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

    if precondition_refusal:
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
    ap.add_argument("--out", default="",
                    help="write a JSON report here (gitignored: a verdict file "
                         "is evidence about one run on one machine)")
    ap.add_argument("--frames-dir", default="",
                    help="where the daemon's frames are saved (default: next "
                         "to --out, else a temp directory)")
    ap.add_argument("--image", default=str(DEFAULT_IMAGE),
                    help="image for the custom_art check")
    ap.add_argument("--size", type=int, default=0,
                    help="panel size; 0 asks the daemon, falling back to 16")
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

    if args.frames_dir:
        frames_dir = args.frames_dir
    elif args.out:
        report = Path(args.out)
        frames_dir = str(report.parent / f"{report.stem}_frames")
    else:
        frames_dir = tempfile.mkdtemp(prefix="hw_verify_frames_")
    info(f"frames (the daemon's own pictures) are saved in: {frames_dir}")

    ctx: dict = {"image": args.image, "frames_dir": frames_dir}
    if args.size:
        ctx["size"] = args.size
    if not Path(args.image).is_file():
        err(f"--image does not exist: {args.image}")
        return 2

    results: list[Result] = []
    run_packet(client, checks, interactive, results, ctx)

    section("summary")
    tally: dict[str, int] = {}
    for r in results:
        tally[r.verdict] = tally.get(r.verdict, 0) + 1
        line = f"{r.verdict:<8} {r.check}"
        (ok if r.verdict in (PASS, XPASS) else err if r.verdict == FAIL
         else warn)(line)
        if r.note:
            info(f"         {r.note}")
    hr()
    info("  ".join(f"{k}={v}" for k, v in sorted(tally.items())))

    if args.out:
        Path(args.out).write_text(json.dumps(
            [r.__dict__ for r in results], indent=2), encoding="utf-8")
        ok(f"report written to {args.out}")

    # The exit code IS the verdict, and it follows the same contract as
    # --self-test: 1 = FAIL, 3 = PARTIAL (nothing was proven), 0 = every check
    # that ran was answered. A run with nobody watching records every verdict
    # UNKNOWN, and exiting 0 there would be exactly the silent pass this
    # packet exists to refuse.
    if tally.get(FAIL):
        return 1
    if tally.get(UNKNOWN) or tally.get(SKIP):
        warn("PARTIAL — at least one check was not answered; nothing was proven")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
