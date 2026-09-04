#!/usr/bin/env bash
# Divoom-specific local-CI step: the Python suite (build the native dylib,
# honestly report camoufox availability, run pytest). Kept as its own script
# because scripts/ci_local.sh is now a thin driver over gates_of_heck's
# local_ci.sh, and this job carries behavior a generic runner cannot know:
# a missing camoufox browser is NOT a failing gate (CI fetches it; a dev
# machine may legitimately skip the ~150 MB download), but the 15 GUI e2e
# suites SKIP silently without it — so the absence must be said out loud,
# never reported green by omission.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=/Users/ztomer/Projects/gates_of_heck/tui/lib.sh
source "${GOH_DIR:-$HOME/Projects/gates_of_heck}/tui/lib.sh"

info "build native dylib"
if ! bash scripts/build_libdivoom.sh >/tmp/py_ci_dylib.log 2>&1; then
    tail -30 /tmp/py_ci_dylib.log >&2
    exit 1
fi
ok "native dylib built"

have_camoufox=0
if python3 tools/check_camoufox_installed.py >/tmp/py_ci_camoufox.log 2>&1; then
    ok "camoufox browser present ($(cat /tmp/py_ci_camoufox.log))"
    have_camoufox=1
else
    warn "no camoufox browser — the 15 GUI e2e suites will SKIP, not run"
    warn "  install with: python3 -m camoufox fetch"
fi

# ── coverage floor (R70 P0.4) ────────────────────────────────────────────────
#
# Scoped to divoom_gui + divoom_client: the code the GUI actually SHIPS.
# `divoom_lib` is deliberately out of scope — it is reference-only (the
# protocol ground truth the Rust port was derived from), and folding it in
# would make this number a claim about a code path that is not the product.
#
# This lives here rather than in .gatesrc's GOH_PY_COV_MIN because the house
# py_gate.sh is COMMENTED OUT in tools/gate.sh — which is the whole mechanical
# reason the "coverage gate (>=95%)" this repo credited to R61 was enforced by
# nobody: the setting was real and its consumer was disabled. It also scopes
# --cov to a single pkg_dir, which cannot express "these two packages, not that
# third one".
#
# The floor only BINDS when camoufox is present. Without it 15 e2e suites skip,
# coverage drops for a reason that has nothing to do with the change under
# test, and a red floor would be punishing the wrong thing. Not enforcing it is
# said out loud rather than passed over in silence — the same rule this script
# already applies to the skipping suites themselves.
# Raised 89 -> 90 by R70 P5.5. The deletions removed more uncovered code
# than covered: the dead audio visualizer had 100% coverage, but the
# cloud panels (38-50%) and media_sync (31%) shrank far more. Stated out
# loud because a floor moved quietly is a floor that stops meaning
# anything.
#
# ...and then R71 P0.4 found that "90" never meant 90. coverage.py's
# should_fail_under is `round(total, precision) < fail_under`, and
# precision defaults to 0 -- so a total of 89.50 ROUNDS UP to 90 and
# passes, while 89.49 fails. Measured coverage on a clean tree is exactly
# 89.50%, i.e. the gate has been green on a 0.01-point margin against a
# floor it advertised as a full point higher.
#
# Fixed by stating the real number instead of one that rounds to it.
# NOT identical, and the first draft of this comment claimed it was --
# checked against coverage.py rather than asserted, which is the only
# reason the difference was found:
#
#   precision 0, floor 90     -> everything in [89.5, 90) passes  (0.5 slack)
#   precision 2, floor 89.5   -> everything in [89.495, 89.5) does (0.005)
#
# So this shrinks the undeserved slack by 100x; it does not abolish it.
# No precision can: `round(total, p) < floor` always lets a sliver just
# below the floor round up onto it. What changes is that the sliver is now
# far narrower than the resolution this suite can actually produce, and
# the advertised number is the one being enforced. Raise the floor
# deliberately when coverage earns it, and say the number out loud.
# R72 FINAL, 2026-08-31. Coverage is 89.30%; floor 89.2 (0.10 margin).
#
# P1.1 deleted 35 statements and the miss count did not move (402 before, 402
# after) -- i.e. every deleted statement was COVERED. That is what dead code
# looks like after Hole D: `save_preset_file` had no caller and eleven tests.
# Deleting it improved the codebase and lowered the ratio by 0.09 points, which
# is the metric being perverse, not the code getting worse.
#
# The round dropped this to 89.0 as a working margin while deleting, and P1.6
# owed the trip back up. Paid here: 89.0 -> 89.4.
#
# The full arc, out loud, because a floor that moves quietly stops meaning
# anything:
#
#   start of R71   89.50%   floor 89.5 (really ">= 89.5" -- see the rounding
#                           note above, which is what P0.4 fixed)
#   after P1.1     89.41%   deleting well-covered dead code lowers a ratio
#   after P1-P3    88.99%   ~290 more statements gone
#   R71 final      89.48%   after covering play_album / push_playlist, whose
#                           migration into the LAN funnel had left them tested
#                           only through e2e
#
# R72 continued the same arc, for the same reason:
#
#   after R72 cuts 88.94%   292 lines of dead notification polling deleted from
#                           divoom_client, plus verify_gallery_render.py's own
#                           auth/HTTP/decoder stack
#   R72 final      89.30%   after covering the two credential wrappers P1.1 had
#                           shipped with ZERO coverage -- which the floor caught
#
# Two rounds, ~730 statements of dead code removed, and the ratio is 0.20 points
# lower than where R71 started. That is the metric behaving as designed: code
# that was well covered and reachable by nothing drags the ratio DOWN when it
# goes, while the codebase gets better. Read a falling number here as a question
# ("what was deleted?"), never as decay on its own.
#
# Floor 89.2 rather than 89.30 so routine work is not blocked by hundredths.
COV_MIN="${DIVOOM_PY_COV_MIN:-89.2}"
COV_PRECISION=2

if [ "$have_camoufox" -eq 1 ]; then
    info "pytest (coverage floor ${COV_MIN}% over divoom_gui + divoom_client)"
    python3 -m pytest -q \
        --cov=divoom_gui --cov=divoom_client \
        --cov-report=term-missing:skip-covered \
        --cov-precision="$COV_PRECISION" \
        --cov-fail-under="$COV_MIN"
else
    warn "coverage floor NOT enforced — needs camoufox for a comparable number"
    python3 -m pytest -q
fi
