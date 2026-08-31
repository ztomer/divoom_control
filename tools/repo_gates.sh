#!/usr/bin/env bash
# repo_gates.sh — layer 3 of the pre-push gate: run this repo's REAL CI locally.
#
# WHY THIS FILE EXISTS (R71 P0.1). Until 2026-08-31 `tools/gate.sh --full` ran
# `structural.sh` and nothing else — emoji, conflict markers, file length, disk
# hygiene. The rust and python layers were commented out, so `pre-push` ran no
# clippy, no tests, neither coverage floor, and none of the nine
# `tools/check_*.py` gates. The 17-step list in `.gatesrc` and both coverage
# floors executed ONLY when a human typed `./scripts/ci_local.sh`.
#
# That is house rule #3 (gates are structural, not disciplinary) violated at the
# top of the stack, and R70 is the receipt: CI was red from P3.3 to P6.3 and
# nobody looked, because the gates that were run were the ones somebody
# remembered. A gate you have to remember to run is not a gate.
#
# THE ESCAPE HATCH IS DELIBERATELY NARROW. `DIVOOM_GATE_FAST=1` skips the slow
# Python suite and SAYS SO, loudly, every time. There is no "skip everything"
# variable on purpose: `git push --no-verify` already exists, and it has the
# property a bypass needs — the person typing it knows they bypassed. A silent
# fast path in here would recreate the hole this file was written to close.
#
# NOTE ON DUPLICATED WORK: `structural.sh` (layer 1) and GOH_CI_STEPS both run
# the emoji and file-length checks, so they execute twice per push. That is a
# few seconds and it is the correct trade: GOH_CI_STEPS mirrors
# .github/workflows/tests.yml job-for-job, and thinning it to dedupe against a
# local-only layer would break the mirror that makes a green local run mean
# something about CI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GOH="${GOH_DIR:-${GOH:-$HOME/Projects/gates_of_heck}}"
# shellcheck source=/Users/ztomer/Projects/gates_of_heck/tui/lib.sh
source "$GOH/tui/lib.sh"

# Recursion guard. Nothing in GOH_CI_STEPS calls back into gate.sh today, but a
# future step that did would fork-bomb the push with no obvious cause. Cheap
# insurance, and it is exercised by tests/test_repo_gates.py rather than
# assumed — an unguarded guard is the failure-path-no-op shape.
if [ -n "${DIVOOM_IN_REPO_GATES:-}" ]; then
    err "repo_gates.sh re-entered (a GOH_CI_STEPS entry is calling gate.sh)"
    exit 2
fi
export DIVOOM_IN_REPO_GATES=1

args=()
if [ -n "${DIVOOM_GATE_FAST:-}" ]; then
    args+=(--fast)
    warn "DIVOOM_GATE_FAST=1 — SKIPPING the Python suite (~3000 tests) and the"
    warn "  Python coverage floor. The Rust jobs and all check_*.py still run."
    warn "  Clear the variable, or run ./scripts/ci_local.sh, before you trust"
    warn "  a green push to mean what it usually means."
fi

# Forward our own arguments through. gate.sh passes none; this exists so the
# wiring can be tested with ci_local.sh's --dry-run without inventing a bypass
# env var (a variable that made a push skip the gates silently is precisely the
# hole this file closes, so there is not one).
section "local CI (pre-push)"
exec "$ROOT/scripts/ci_local.sh" ${args[@]+"${args[@]}"} "$@"
