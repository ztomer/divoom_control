#!/usr/bin/env bash
# Local-CI step wrapper: run the house emoji gate with this repo's exemption
# (.gatesrc GOH_EXCLUDE), passing --exclude ONLY when non-empty. Kept out of
# the GOH_CI_STEPS string because the step list is colon-separated and
# `${GOH_EXCLUDE:+...}` expansions contain a colon — the dry-run caught the
# runner splitting mid-expansion.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$ROOT/.gatesrc" ] && source "$ROOT/.gatesrc"

GOH="${GOH_DIR:-$HOME/Projects/gates_of_heck}"

args=()
if [ -n "${GOH_EXCLUDE:-}" ]; then
    args+=(--exclude "$GOH_EXCLUDE")
fi

exec python3 "$GOH/checks/check_no_emoji.py" "${args[@]+"${args[@]}"}"
