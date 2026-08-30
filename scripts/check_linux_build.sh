#!/usr/bin/env bash
# Compile divoomd for LINUX from this Apple-silicon Mac, so a macOS-only symbol
# referenced from shared code is caught before it is pushed.
#
# R67 broke the Linux build TWICE the same way: `nowplaying` (MediaRemote) is a
# macOS-only dependency, and a call site referencing it stayed ungated. Both
# times the whole macOS gate ran green, because a macOS build is structurally
# incapable of seeing that class — CI was the only instrument, so each fix was
# a blind push-and-wait.
#
# `--all-features` cannot run here: the `ble` feature pulls btleplug -> dbus ->
# libdbus-sys, which needs Linux dbus headers zig cannot supply. That does not
# matter for this class. The defect lives in the LIB, behind no feature, and
# this command reproduces CI's exact error:
#
#     error[E0432]: unresolved import `music_job`
#
# Verified by removing the cfg and watching it fail before it was trusted.
# CI still owns full-feature Linux coverage; this catches the common case early.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

GOH="${GOH_DIR:-$HOME/Projects/gates_of_heck}"
# shellcheck disable=SC1091
[ -f "$GOH/tui/lib.sh" ] && source "$GOH/tui/lib.sh"
type info >/dev/null 2>&1 || { info() { echo "→ $*"; }; ok() { echo "✓ $*"; }
                               warn() { echo "⚠ $*"; }; }

TARGET="${LINUX_TARGET:-x86_64-unknown-linux-gnu}"

# Skip rather than fail when the cross toolchain is absent: CI is authoritative
# for Linux, and a machine without zig must still be able to commit.
if ! command -v cargo-zigbuild >/dev/null 2>&1 || ! command -v zig >/dev/null 2>&1; then
    warn "[linux] skipped — cargo-zigbuild + zig not installed (CI still covers Linux)"
    exit 0
fi
if ! rustup target list --installed 2>/dev/null | grep -qx "$TARGET"; then
    warn "[linux] skipped — rust target $TARGET not installed (rustup target add $TARGET)"
    exit 0
fi

info "[linux] checking divoomd for $TARGET"
if cargo-zigbuild clippy -p divoomd --no-default-features \
        --target "$TARGET" >/tmp/divoom_linux_check.log 2>&1; then
    ok "[linux] OK — divoomd compiles for $TARGET"
else
    grep -E "^error" /tmp/divoom_linux_check.log | head -20 || true
    echo "  full log: /tmp/divoom_linux_check.log"
    exit 1
fi
