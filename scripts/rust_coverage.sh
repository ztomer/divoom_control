#!/bin/bash
# Delegating shim — the gate lives in gates_of_heck
# (gates/coverage_gate.sh --lang rust); this keeps the invocation path stable.
#
# Floor: NONE was enforced before (plain `cargo llvm-cov --all-targets`
# report, no threshold), and neither CI (.github/workflows/tests.yml has no
# coverage job) nor docs imply one — so an explicit floor is PINNED HERE:
# 29% of coverable lines, measured 2026-08-25 on the divoomd crate at
# 29.74% (3066/10301 lines). Any regression fails; most project logic lives
# in the Python suite, which is why the number looks low for a Rust crate.

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

exec "$GOH/gates/coverage_gate.sh" --lang rust --floor 29 "$ROOT/divoomd"
