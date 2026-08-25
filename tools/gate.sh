#!/usr/bin/env bash
# Per-repo gate entry point. Declares which toolchains this repo contains and
# delegates; it holds no gate logic of its own.
#   --staged : pre-commit scope (fast) — layer 1 only
#   --full   : pre-push scope — every layer
set -euo pipefail
GOH="${GOH_DIR:-${GOH:-$HOME/Projects/gates_of_heck}}"

"$GOH/gates/structural.sh" "$@"

case "${1:-}" in
  --full)
    # Add per-language layers for what this repo actually contains:
    #   "$GOH/gates/rust_gate.sh"  .
    #   "$GOH/gates/py_gate.sh"    .
    #   "$GOH/gates/swift_gate.sh" .
    # Layer 3 (genuinely local checks): create ./tools/repo_gates.sh and
    # uncomment:
    #   ./tools/repo_gates.sh
    ;;
esac
