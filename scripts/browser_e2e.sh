#!/usr/bin/env bash
# The browser e2e suites, as ONE command both CI and the local gate run (P1.13).
#
# Before 2026-10-19 they ran only in CI's own step, so the one step that went
# red on main (run 39171574815) was the one pre-push could not see. The reason
# was the browser build: CI pinned one, the machine-wide camoufox cache held
# another. Both now come from `.camoufox-build`, and this script refuses to run
# on any other build -- loudly, with the install command -- instead of running
# the suites against a browser CI does not use, or skipping them.
#
#   DIVOOM_BROWSER_WORKERS  pytest-xdist workers (default 8; CI passes 0 =
#                           serial, its 3-core runner). Measured 2026-10-18 on
#                           the 16-core dev machine: -n 8 is 10-11 min, serial
#                           29 min.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=/Users/ztomer/Projects/gates_of_heck/tui/lib.sh
source "${GOH_DIR:-$HOME/Projects/gates_of_heck}/tui/lib.sh"

python3 tools/camoufox_installed.py || die "the browser suites need the pinned camoufox build (above)"

suites=()
while IFS= read -r f; do suites+=("$f"); done < <(grep -l playwright tests/test_*.py)
[ "${#suites[@]}" -gt 0 ] || die "no browser suites found (tests/test_*.py importing playwright)"

workers="${DIVOOM_BROWSER_WORKERS:-8}"
info "browser e2e: ${#suites[@]} suites, --run-browser, -n ${workers}"
python3 -m pytest -q -p no:cacheprovider --run-browser -n "$workers" "${suites[@]}"
ok "browser suites green"
