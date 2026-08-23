#!/usr/bin/env bash
# ci_local.sh — run the FULL CI gate locally, before spending a CI run on it.
#
# GitHub Actions is ACTIVE for this repo. It is PUBLIC, and Actions on standard
# runners is free for public repositories, so no credits are consumed and a red
# check is a real code signal. (The 2026-08-17 "credits are exhausted" state is
# over — see AGENTS.md.) This script is the fast local gate, NOT a substitute
# for reading the CI result.
#
# The pre-commit hook is deliberately narrow
# (staged files only, divoomd only, no tests) so commits stay fast; that means it
# is WEAKER than CI in three ways and must not be mistaken for it:
#   - it checks only STAGED files, CI checks the whole tree
#   - it gates only divoomd, never divoom-menubar
#   - it never runs a single test
#
# Mirrors .github/workflows/tests.yml job-for-job, WITH ONE LIMIT THAT MATTERS:
# it runs on this machine only. CI's rust-core / rust-ble-linux jobs run on
# Ubuntu, so a Linux-only failure is invisible here. That is not hypothetical --
# v0.23.0 shipped with a red rust-core because workspace-wide clippy pulled in
# divoom-menubar (tao/tray-icon -> GTK/glib), which builds fine on macOS and
# fails on a Linux runner without a GTK toolchain. A green run here means "the
# macOS-reachable jobs pass", never "CI would be green".
#
# Run before every push and before cutting a release. release.sh's ci_gate then
# checks the REAL CI result for the commit being tagged; this script passing is
# a precondition for that, not a replacement (the credit-depletion exception in
# AGENTS.md is a dormant safety valve, not the current state).
#
#   ./scripts/ci_local.sh            all jobs
#   ./scripts/ci_local.sh --fast     skip the Python suite (the slow one)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../tui/lib.sh
source "$ROOT/tui/lib.sh"
cd "$ROOT"

FAST=0
for a in "$@"; do
  case "$a" in
    --fast)    FAST=1 ;;
    -h|--help) echo "usage: ./scripts/ci_local.sh [--fast]"; exit 0 ;;
    *)         die "unknown option: $a (try --help)" ;;
  esac
done

require_commands cargo python3
FAILED=()
run() {  # run <label> <cmd...>
  local label="$1"; shift
  info "$label"
  if "$@" >/tmp/ci_local_step.log 2>&1; then
    ok "$label"
  else
    err "$label"
    tail -30 /tmp/ci_local_step.log >&2
    FAILED+=("$label")
  fi
}

# ── job: no-emoji (whole tree, not just staged) ───────────────────────
section "House gates"
run "no-emoji (all tracked files)"  python3 tools/check_no_emoji.py
run "file-size 500-line limit"      python3 tools/check_file_size.py
run "no #[allow] in Rust source"    python3 tools/check_no_allow.py

# ── job: rust-core (the no-BLE, platform-free gate) ───────────────────
section "Rust core (no BLE)"
run "cargo fmt --check"             cargo fmt --all -- --check
run "clippy (all targets/features)" cargo clippy --all-targets --all-features -- -D warnings
run "build --no-default-features"   cargo build -p divoomd --no-default-features --locked
run "test  --no-default-features"   cargo test  -p divoomd --no-default-features --locked

# ── job: rust-ble (default features include ble) ──────────────────────
section "Rust with BLE"
run "cargo test (ble)"              cargo test --locked

# ── job: test (Python) ────────────────────────────────────────────────
if [ "$FAST" = "1" ]; then
  section "Python suite"
  warn "skipped (--fast)"
else
  section "Python suite"
  run "build native dylib"          bash scripts/build_libdivoom.sh
  # NOT a failing gate locally: CI fetches the browser, a dev machine may
  # legitimately not have the ~150 MB download. But a silent absence means all
  # 15 GUI e2e suites SKIP, so a green run here would mean far less than it
  # looks like. Say so out loud instead.
  if python3 tools/check_camoufox_installed.py >/tmp/ci_local_camoufox.log 2>&1; then
    ok "camoufox browser present ($(cat /tmp/ci_local_camoufox.log))"
  else
    warn "no camoufox browser — the 15 GUI e2e suites will SKIP, not run"
    warn "  install with: python3 -m camoufox fetch"
  fi
  run "pytest"                      python3 -m pytest -q
fi

section "Result"
if [ ${#FAILED[@]} -eq 0 ]; then
  ok "all CI-equivalent jobs passed"
  exit 0
fi
err "${#FAILED[@]} job(s) failed:"
for f in "${FAILED[@]}"; do err "  $f"; done
exit 1
