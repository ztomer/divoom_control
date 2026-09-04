#!/bin/bash
# Delegating shim — the gate lives in gates_of_heck
# (gates/coverage_gate.sh --lang rust); this keeps the invocation path stable.
#
# Floor: a RATCHET against regression, not a target. Raised 2026-08-30 from 29
# to 42, measured twice at 43.06% (5356/12438 lines) — identical to the digit
# both runs, so the number is deterministic and safe to pin against. One point
# of headroom absorbs ordinary churn without red-lighting a green tree.
#
# The 29 it replaces was set 2026-08-25 at a then-measured 29.74%
# (3066/10301). It was 14 points stale by the time anyone looked, which is what
# a ratchet does when nobody re-measures: it stops being a floor and becomes a
# number. Re-measure and raise it whenever coverage moves up for real.
#
# Note the SCOPE. The path argument says divoomd, but the gate enumerates the
# workspace — the run also exports `nowplaying`, and its uncovered lines count
# against this percentage. The original comment's "on the divoomd crate" was
# never quite true, and the growth from 10301 to 12438 coverable lines is new
# code plus that wider scope, not divoomd alone.
#
# Most project logic still lives in the Python suite (which holds ~95%), which
# is why the Rust number looks low for a crate of this size.
#
# Proven to bite on 2026-08-30: --floor 44 against the same tree exits 1 and
# names the uncovered lines. A floor nobody has watched fail is not a floor.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GOH="${GOH_DIR:-$HOME/Projects/gates_of_heck}"

if ! command -v cargo-llvm-cov >/dev/null 2>&1; then
    echo "cargo-llvm-cov is not installed."
    echo "To install it, run:"
    echo "    rustup component add llvm-tools-preview"
    echo "    cargo install cargo-llvm-cov"
    exit 1
fi

exec "$GOH/gates/coverage_gate.sh" --lang rust --floor 42 "$ROOT/divoomd"
