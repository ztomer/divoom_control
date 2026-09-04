#!/usr/bin/env bash
# ci_local.sh — run the FULL CI-equivalent gate locally, before spending a CI
# run on it.
#
# GitHub Actions is ACTIVE for this repo (public, free on standard runners);
# this script is the fast local gate, NOT a substitute for reading the CI
# result. The pre-commit hook is deliberately narrower (staged only, divoomd
# only, no tests).
#
# The step list is now DECLARATIVE: .gatesrc GOH_CI_STEPS, executed by
# gates_of_heck's gates/local_ci.sh (fail-accumulating, log-on-failure). This
# file stays as the entry point for one reason: the Python suite is the slow,
# genuinely divoom-specific job and --fast must be able to skip just it.
#
# WHAT MACOS-LOCAL CANNOT SEE — see the comment above GOH_CI_STEPS in
# .gatesrc: CI's Linux jobs can fail where this macOS run is green. A green
# run here means "the macOS-reachable jobs pass", never "CI would be green".
#
#   ./scripts/ci_local.sh            all jobs
#   ./scripts/ci_local.sh --fast     skip the Python suite (the slow one)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GOH="${GOH_DIR:-$HOME/Projects/gates_of_heck}"

FAST=0
extra=()
for a in "$@"; do
  case "$a" in
    --fast)    FAST=1 ;;
    --dry-run) extra+=("$a") ;;
    -h|--help) echo "usage: ./scripts/ci_local.sh [--fast] [--dry-run]" >&2; exit 0 ;;
    *)         printf '✗ unknown option: %s (try --help)\n' "$a" >&2; exit 2 ;;
  esac
done
if [ "$FAST" -eq 0 ]; then
  extra+=(--step './scripts/py_ci.sh')
fi

exec "$GOH/gates/local_ci.sh" ${extra[@]+"${extra[@]}"} "$ROOT"
