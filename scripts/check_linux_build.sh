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

# FAIL, never skip, when the cross toolchain is absent (2026-10-18). This used
# to warn and exit 0 -- and the x86_64-unknown-linux-gnu target was in fact not
# installed, so every pre-push "passed" it while CI's Linux lint went red on 19
# of 20 main runs (`unused import: err_with`, used only under cfg(macos)). A
# step that skips itself green is not a gate. A machine that genuinely cannot
# cross-check opts out by typing DIVOOM_SKIP_LINUX_CHECK=1, which is loud.
if [ "${DIVOOM_SKIP_LINUX_CHECK:-}" = "1" ]; then
    warn "[linux] SKIPPED by DIVOOM_SKIP_LINUX_CHECK=1 — CI's Linux lint is unchecked here"
    exit 0
fi
missing=""
command -v cargo-zigbuild >/dev/null 2>&1 || missing+=" cargo-zigbuild"
command -v zig >/dev/null 2>&1 || missing+=" zig"
grep -qx "$TARGET" <<<"$(rustup target list --installed 2>/dev/null)" \
    || missing+=" rust-target:$TARGET (rustup target add $TARGET)"
if [ -n "$missing" ]; then
    printf '✗ [linux] cannot cross-check, missing:%s\n' "$missing" >&2
    exit 1
fi

info "[linux] checking divoomd for $TARGET"
# CI_LINT_ARGS is CI's "Lint core without BLE" step, flag for flag
# (.github/workflows/tests.yml, rust-core job); tests/test_linux_lint_parity.py
# holds the two together. It was `clippy --no-default-features` alone: no
# --all-targets, no -D warnings, so a Linux-only WARNING -- the exact class CI
# denies -- passed here as long as it compiled.
CI_LINT_ARGS=(-p divoomd --no-default-features --all-targets --locked -- -D warnings)
LOG="${TMPDIR:-/tmp}/divoom_linux_check.log"
if cargo-zigbuild clippy --target "$TARGET" "${CI_LINT_ARGS[@]}" >"$LOG" 2>&1; then
    ok "[linux] OK — divoomd lints clean for $TARGET (CI flags)"
else
    grep -E "^error" "$LOG" | head -20 || true
    echo "  full log: $LOG"
    exit 1
fi
