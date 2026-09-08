#!/usr/bin/env python3
"""Gate: every name in the hardware packet must be one the daemon answers.

**Why this exists.** On 2026-09-07 `scripts/hw_verify.py` was run against a
connected device and failed five checks out of five. Three of them never
reached the panel: the daemon replied `method not ported yet` to
`live_jobs.start`, `media.push_album_art` and `display.show_weather`, none of
which it has ever implemented. They were the pre-port Python spellings, left
behind when the widget jobs moved into `divoomd` as `live_job_start`, and the
R12 visual pass sat in the roadmap as "needs a device" for rounds while it
would have failed identically with no device attached.

`--self-test` did not catch it, and could not: it proves the packet reports
FAILURE for a deliberately bogus method, which is a statement about the packet's
error handling and says nothing about whether its OWN names exist. Both
properties read as "the harness is calibrated". Only one of them was.

So the missing gate is static and runs with no hardware: read the daemon's match
arms, read the packet, and fail when the packet names something the daemon does
not answer. A moved API now reddens a push instead of masquerading as a
hardware fault in front of someone holding a device.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from _tui import err, info, ok  # noqa: E402
from capability_census import _ARM_BEFORE, daemon_capabilities  # noqa: E402

COORDINATOR = REPO / "divoomd" / "src" / "live_jobs" / "coordinator.rs"

# Below these, the extractor is not reading what it thinks it is reading, and a
# gate that compares against an empty set reports compliance over nothing. The
# real counts are ~444 and 4; these are floors, not targets.
MIN_CAPABILITIES = 100
MIN_KINDS = 2


def live_job_kinds() -> set[str]:
    """The kinds `LiveJobs::start` will dispatch, from its own match arms."""
    text = COORDINATOR.read_text(encoding="utf-8", errors="ignore")
    marker = "match kind.as_str() {"
    if marker not in text:
        return set()
    body = text[text.index(marker) + len(marker):]
    # `_ => return Err(...)` closes the match; anything after it belongs to
    # another one and would inflate the set with names `start` never accepts.
    cut = body.find("_ =>")
    if cut != -1:
        body = body[:cut]
    return set(_ARM_BEFORE.findall(body))


def main() -> int:
    caps = daemon_capabilities()
    kinds = live_job_kinds()

    # Calibrate before comparing: an extractor that silently returns nothing
    # passes every packet, which is the failure this whole file is about.
    if len(caps) < MIN_CAPABILITIES or len(kinds) < MIN_KINDS:
        err(f"[hw-verify-methods] extractor is not reading the daemon "
            f"({len(caps)} commands, {len(kinds)} live-job kinds)")
        info("  Below the floor the comparison below is vacuous, so this is a")
        info("  FAILURE, not a pass over an empty set. Check that")
        info("  divoomd/src/daemon/dispatch.rs and live_jobs/coordinator.rs")
        info("  still hold their match arms in the expected shape.")
        return 1

    from scripts.hw_verify import CallCheck, CommandCheck, LiveJobCheck, build_checks

    bad: list[str] = []
    for c in build_checks():
        if isinstance(c, LiveJobCheck):
            if "live_job_start" not in caps:
                bad.append(f"{c.id}: daemon has no 'live_job_start' command")
            if c.kind not in kinds:
                bad.append(f"{c.id}: live-job kind {c.kind!r} is not one of "
                           f"{sorted(kinds)}")
        elif isinstance(c, CallCheck):
            if c.method not in caps:
                bad.append(f"{c.id}: device_call method {c.method!r} is not a "
                           f"daemon capability")
        elif isinstance(c, CommandCheck):
            if c.command not in caps:
                bad.append(f"{c.id}: socket command {c.command!r} is not a "
                           f"daemon capability")
        else:
            bad.append(f"{c.id}: unknown check type {type(c).__name__} — this "
                       f"gate cannot vouch for it")

    if bad:
        err(f"[hw-verify-methods] {len(bad)} packet entr"
            f"{'y' if len(bad) == 1 else 'ies'} name something the daemon does "
            f"not answer")
        for b in bad:
            print(f"  ✗ {b}", flush=True)
        info("  These fail at the socket, before any pixel is drawn, and read")
        info("  to an operator as a hardware fault. Fix the name, not the device.")
        return 1

    ok(f"[hw-verify-methods] OK — packet checked against {len(caps)} daemon "
       f"commands, {len(kinds)} live-job kinds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
