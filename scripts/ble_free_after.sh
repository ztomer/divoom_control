#!/usr/bin/env bash
# ble_free_after.sh — run a command, then leave target/debug/divoomd BLE-free.
#
#   ./scripts/ble_free_after.sh cargo test --locked
#   ./scripts/ble_free_after.sh --restore        # only the rebuild
#
# `divoomd`'s default features include `ble`, so the CI-mirroring cargo steps
# (`cargo test`, `cargo build -p divoomd`) uplift a BLE-enabled binary to
# target/debug/divoomd, and every later local run or probe got a BLE build
# nobody asked for (D.BLEDBG). The dev build everything else documents is
# `--no-default-features`. The restore is carried by each step, not by a
# trailing step: goh's proven-step cache can skip a trailing step while an
# earlier one re-runs. It runs whatever the command's status, and the command's
# own status wins; a failed restore fails an otherwise green step.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 2

rc=0
if [ "${1:-}" != "--restore" ]; then
  [ "$#" -gt 0 ] || { echo "usage: ble_free_after.sh CMD... | --restore" >&2; exit 2; }
  "$@"
  rc=$?
fi

printf '→ leaving target/debug/divoomd BLE-free (cargo build -p divoomd --no-default-features)\n'
cargo build -p divoomd --no-default-features --locked
restore_rc=$?

[ "$rc" -ne 0 ] && exit "$rc"
exit "$restore_rc"
