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
COV_MIN="${DIVOOM_PY_COV_MIN:-90}"

if [ "$have_camoufox" -eq 1 ]; then
    info "pytest (coverage floor ${COV_MIN}% over divoom_gui + divoom_client)"
    python3 -m pytest -q \
        --cov=divoom_gui --cov=divoom_client \
        --cov-report=term-missing:skip-covered \
        --cov-fail-under="$COV_MIN"
else
    warn "coverage floor NOT enforced — needs camoufox for a comparable number"
    python3 -m pytest -q
fi
