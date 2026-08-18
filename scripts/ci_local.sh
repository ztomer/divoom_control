#!/usr/bin/env bash
# ci_local.sh — run the FULL CI gate locally, because GitHub Actions credits are
# exhausted and CI now always fails.
#
# This is the only remaining signal. The pre-commit hook is deliberately narrow
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
# Run before every push and before cutting a release (scripts/release.sh's
# ci_gate cannot verify a green CI while billing is out — see AGENTS.md's
# credit-depletion exception).
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
