#!/usr/bin/env python3
"""ci_jobs.py check OWNER/NAME SHA [--wait] -- the one reader of a commit's GitHub check runs for the
release scripts (scripts/ship_release.sh waits on it; scripts/release.sh's ci_gate asks once).

DV.CIADVISORY. A release is cut only on a CI that local cannot reproduce being green. The macOS `gate`
job runs the same ./tools/gate.sh the pre-push gate already passed, so waiting on it only waits on
GitHub's runner queue: the 0.45.2 and 0.45.3 ships both stopped there with nothing tagged. It is
ADVISORY: reported, never blocking. Every other job (`linux-all-features`, which local cannot
reproduce) blocks while pending or red. A commit with no blocking job registered yet is pending.

The advisory names live HERE and nowhere else; the scripts call this file and never name a job.

Exit: 0 clear to release, 1 red / no verdict / unreadable, 3 pending (the --wait bound ran out, or
no --wait), 75 GitHub throttled (EX_TEMPFAIL: not a failure, not a green).

Seams (the tests): GOH_GH names the gh binary; DIVOOM_CI_POLL_S and DIVOOM_CI_TIMEOUT_S set the
wait's interval and bound (defaults 60 s and 1800 s).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

RULING = (
    "owner, 2026-11-11: \"does goh github ci does anything we don't do locally? if the answer is "
    "negative, we can just move forward instead of waiting. we're not hostage to github's capacity\""
)
# job name -> why it is advisory (the gate job runs ./tools/gate.sh, which the pre-push hook ran)
ADVISORY = {"gate": "runs the same ./tools/gate.sh the local pre-push gate already passed"}

OK, PENDING, FAIL, NO_RUNS, THROTTLED, UNREAD = 0, 3, 1, 1, 75, 1
GOOD = ("success", "neutral", "skipped")
CREDITS_RE = re.compile(r"\b(credit|billing)\w*\b|out of minutes|usage limit", re.I)
THROTTLE_RE = re.compile(r"rate limit|HTTP 429|abuse detection|secondary", re.I)


def judge(runs: list[dict]) -> tuple[int, str]:
    """(exit code, one-line verdict) for a commit's check runs; advisory jobs never decide it."""
    advisory = [r for r in runs if r.get("name") in ADVISORY]
    blocking = [r for r in runs if r.get("name") not in ADVISORY]
    notes = []
    for r in advisory:
        state = r.get("conclusion") if r.get("status") == "completed" else "still running"
        notes.append(f"advisory job '{r['name']}': {state} (reported, never blocking)")
    note = ("; " + "; ".join(notes)) if notes else ""
    if not runs:
        return NO_RUNS, "no CI check runs found"
    pending = [r["name"] for r in blocking if r.get("status") != "completed"]
    if pending:
        return PENDING, "CI still running -- " + ", ".join(pending) + note
    if not blocking:
        return PENDING, "CI still running -- no blocking job has registered yet" + note
    for r in blocking:
        if r.get("conclusion") in GOOD:
            continue
        out = r.get("output") or {}
        blob = " ".join(str(x) for x in (r.get("name"), out.get("title"), out.get("summary")) if x)
        if CREDITS_RE.search(blob):
            return OK, f"CI failure on '{r['name']}' looks like credit/billing depletion -- allowed{note}"
        return FAIL, f"CI check run failed -- {r['name']}{note}"
    return OK, "CI green (every blocking check run passed)" + note


def fetch(slug: str, sha: str) -> tuple[int, list[dict] | str]:
    """(0, runs) or (code, why): 75 for a throttled GitHub, 1 for anything else unreadable."""
    gh = os.environ.get("GOH_GH", "gh")
    try:
        done = subprocess.run([gh, "api", f"repos/{slug}/commits/{sha}/check-runs"], capture_output=True,
                              text=True, timeout=120, check=False, stdin=subprocess.DEVNULL)  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as e:
        return UNREAD, f"could not query CI status ({e})"
    if done.returncode != 0:
        why = (done.stderr or done.stdout).strip()
        if THROTTLE_RE.search(why):
            return THROTTLED, f"GitHub is throttled ({why.splitlines()[0] if why else 'rate limit'})"
        return UNREAD, f"could not query CI status (gh api failed: {why[:200]})"
    try:
        return 0, json.loads(done.stdout).get("check_runs") or []
    except ValueError:
        return UNREAD, "could not parse CI status"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check")
    p.add_argument("slug")
    p.add_argument("sha")
    p.add_argument("--wait", action="store_true", help="poll until clear, red, throttled or the bound")
    args = ap.parse_args(argv)
    poll = float(os.environ.get("DIVOOM_CI_POLL_S", "60"))
    end = time.monotonic() + float(os.environ.get("DIVOOM_CI_TIMEOUT_S", "1800"))
    while True:
        code, got = fetch(args.slug, args.sha)
        if code:
            print(got, file=sys.stderr if code != THROTTLED else sys.stdout)
            return code
        assert isinstance(got, list)
        code, text = judge(got)
        waiting = code == PENDING or (code == NO_RUNS and args.wait)  # just pushed: runs register late
        if not (args.wait and waiting):
            print(text, file=sys.stderr if code not in (OK, PENDING) else sys.stdout)
            return code
        if time.monotonic() + poll > end:
            print(f"{text}; still not clear after the wait's bound", file=sys.stdout)
            return PENDING
        print(f"{text}; next read in {poll:g}s", flush=True)
        time.sleep(poll)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
