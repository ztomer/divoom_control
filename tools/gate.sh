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
    # Layer 3 — this repo's real CI, run locally before anything leaves the
    # machine (R71 P0.1). See tools/repo_gates.sh for why this line is not
    # optional: without it `--full` was four structural checks, and the 17-step
    # list plus both coverage floors ran only when somebody remembered to.
    ./tools/repo_gates.sh
    # The house per-language layers are deliberately NOT used here:
    #   "$GOH/gates/rust_gate.sh"  .
    #   "$GOH/gates/py_gate.sh"    .
    # repo_gates.sh delegates to scripts/ci_local.sh, which mirrors
    # .github/workflows/tests.yml job-for-job. That mirror is the whole value of
    # a local run — a green one has to mean something about CI. py_gate.sh would
    # also read GOH_PY_COV_MIN, which this repo documents as unused: the real
    # Python floor lives in scripts/py_ci.sh, scoped to divoom_gui +
    # divoom_client, because --cov cannot express "these two packages, not that
    # third one".
    ;;
esac
