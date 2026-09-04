#!/usr/bin/env bash
# Local driver: rsync the working tree to the Linux test host and run the build +
# test + BLE-scan suite there. Repeatable validation of the native daemon on
# real Linux (btleplug/BlueZ) that this macOS dev box can't do directly.
#
#   scripts/linux_remote/run.sh                 # rsync + test
#   scripts/linux_remote/run.sh --provision     # also (re)install toolchain/deps
#
# Config via env (no secrets committed):
#   DIVOOM_LINUX_HOST   ssh target           (default: ztomer@192.168.0.33)
#   DIVOOM_LINUX_DIR    remote repo path     (default: ~/divoom-control)
#   SUDO_PASS           sudo password for --provision (apt); never stored
set -uo pipefail

HOST="${DIVOOM_LINUX_HOST:-ztomer@192.168.0.33}"
RDIR="${DIVOOM_LINUX_DIR:-divoom-control}"
SSH=(ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "[*] rsync $REPO_ROOT -> $HOST:~/$RDIR"
rsync -az --delete -e "${SSH[*]}" \
  --exclude '.git' --exclude 'target' --exclude 'node_modules' \
  --exclude '*.app' --exclude '__pycache__' --exclude 'dist' \
  "$REPO_ROOT/" "$HOST:$RDIR/"

if [ "${1:-}" = "--provision" ]; then
  echo "[*] provisioning $HOST"
  "${SSH[@]}" "$HOST" "SUDO_PASS='${SUDO_PASS:-}' bash ~/$RDIR/scripts/linux_remote/provision_host.sh"
fi

echo "[*] running test_host.sh on $HOST"
"${SSH[@]}" "$HOST" "bash ~/$RDIR/scripts/linux_remote/test_host.sh"
