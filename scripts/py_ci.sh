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

if python3 tools/check_camoufox_installed.py >/tmp/py_ci_camoufox.log 2>&1; then
    ok "camoufox browser present ($(cat /tmp/py_ci_camoufox.log))"
else
    warn "no camoufox browser — the 15 GUI e2e suites will SKIP, not run"
    warn "  install with: python3 -m camoufox fetch"
fi

python3 -m pytest -q
