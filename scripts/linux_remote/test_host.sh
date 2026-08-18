#!/usr/bin/env bash
# Runs ON the Linux test host. Builds + tests the native daemon both feature
# matrices, builds the libdivoom .so, then starts the daemon and attempts a BLE
# scan / hardware round-trip. No sudo (deps are pre-installed by provision_host.sh).
#
#   bash scripts/linux_remote/test_host.sh
#
# Exits non-zero if any cargo test matrix fails (the BLE scan is informational —
# devices may be out of range).
set -uo pipefail
source "$HOME/.cargo/env" 2>/dev/null || true
cd "$(cd "$(dirname "$0")/../.." && pwd)"   # repo root
REPO="$(pwd)"
RC=0
sect() { echo; echo "============== $* =============="; }

sect "host"
uname -srm; (lsb_release -ds 2>/dev/null || true); cargo --version

sect "Rust core (--no-default-features)"
( cd divoomd && cargo test --no-default-features 2>&1 | grep -E '^error|test result|FAILED' ) || RC=1

sect "build libdivoom (.so)"
bash scripts/build_libdivoom.sh 2>&1 | tail -2

sect "Rust full (ble / BlueZ backend)"
( cd divoomd && cargo test 2>&1 | grep -E '^error|test result|FAILED' ) || RC=1

sect "build release daemon"
( cd divoomd && cargo build --release 2>&1 | tail -1 )

sect "BLE scan + hardware round-trip"
groups
# Reset the BlueZ adapter to clear any wedged/half-connected state from a prior
# run (these dual-mode Divoom devices can stick at the BR/EDR layer).
bluetoothctl power off >/dev/null 2>&1 || true
sleep 1
bluetoothctl power on  >/dev/null 2>&1 || true
sleep 1
pkill -f target/release/divoomd 2>/dev/null
rm -f /tmp/divoomd.sock
./target/release/divoomd --socket /tmp/divoomd.sock >/tmp/divoomd.log 2>&1 &
DPID=$!
for _ in $(seq 1 50); do [ -S /tmp/divoomd.sock ] && break; sleep 0.2; done
python3 scripts/linux_remote/scan.py /tmp/divoomd.sock || true
kill "$DPID" 2>/dev/null
echo "--- daemon log tail ---"; tail -6 /tmp/divoomd.log 2>/dev/null

sect "SUMMARY"
[ "$RC" -eq 0 ] && echo "cargo matrices: PASS" || echo "cargo matrices: FAIL"
exit "$RC"
