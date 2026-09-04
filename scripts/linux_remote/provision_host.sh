#!/usr/bin/env bash
# Runs ON the Linux test host. Idempotent provisioning for building/testing the
# native daemon: rustup (user-local, no sudo) + the apt build deps btleplug and
# the openssl-sys transitive dep need.
#
#   SUDO_PASS=... bash scripts/linux_remote/provision_host.sh
#
# SUDO_PASS is read from the environment (never hardcoded). If unset, falls back
# to interactive sudo.
set -uo pipefail

if ! command -v cargo >/dev/null 2>&1 && [ ! -x "$HOME/.cargo/bin/cargo" ]; then
  echo "[*] installing rustup (user-local)…"
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
    | sh -s -- -y --default-toolchain stable --profile minimal
fi
source "$HOME/.cargo/env" 2>/dev/null || true
cargo --version

# build-essential: cc for libdivoom + sys crates; pkg-config + libdbus-1-dev:
# btleplug BlueZ backend; libssl-dev: openssl-sys (transitive).
PKGS="build-essential pkg-config libdbus-1-dev libssl-dev"
echo "[*] apt deps: $PKGS"
if [ -n "${SUDO_PASS:-}" ]; then
  echo "$SUDO_PASS" | sudo -S apt-get update -qq
  echo "$SUDO_PASS" | sudo -S apt-get install -y $PKGS
else
  sudo apt-get update -qq && sudo apt-get install -y $PKGS
fi
echo "[*] provision done."
