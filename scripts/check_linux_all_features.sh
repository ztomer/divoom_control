#!/usr/bin/env bash
# CI's LINUX `--all-features` lint, run locally, in a Linux container.
#
# WHY THIS FILE EXISTS. The Linux half of the daemon (the `ble` feature ->
# btleplug -> bluer -> dbus -> libdbus-sys) is only compiled on Linux, and CI's
# `rust-core` job is the only thing that has ever compiled it with the feature
# ON:
#
#     cargo clippy -p divoomd --all-targets --all-features -- -D warnings
#
# `scripts/check_linux_build.sh` cross-compiles the NO-BLE half (the `ble`
# feature needs the system dbus-1.pc, which zig cannot supply), so the
# `--all-features` half ran in CI and NOWHERE ELSE: a Linux-only clippy
# finding was invisible until a push went red on the runner. The
# `.gatesrc` comment said so in as many words ("Still NOT covered: anything
# behind --all-features"), and the fix was left as a note instead of a gate.
#
# A gate you have to remember to run is not a gate (house rule #3), so this
# runs it BEFORE the push. The container is Linux, the toolchain is the same
# stable Rust CI uses, the D-Bus headers are the same package CI installs, and
# the clippy line is CI's line, character for character -- pinned by
# tests/test_linux_all_features_parity.py, the way
# tests/test_linux_lint_parity.py pins the no-BLE half.
#
# WHY A CONTAINER AND NOT A CROSS-BUILD. `cargo-zigbuild` cannot supply
# dbus-1.pc, and faking one would be a gate that proves nothing: the whole
# point is to compile the Linux BLE backend against the real headers. Docker
# gives the same Debian userland CI's Ubuntu runner has, and the same
# `libdbus-1-dev` + `pkg-config` pair CI installs.
#
# The toolchain tracks the `rust:latest` image (stable), like CI's
# `dtolnay/rust-toolchain@stable`. The gate PRINTS the toolchain it used, so a
# drift between this and CI is visible in the log rather than silent.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

GOH="${GOH_DIR:-$HOME/Projects/gates_of_heck}"
# shellcheck disable=SC1091
[ -f "$GOH/tui/lib.sh" ] && source "$GOH/tui/lib.sh"
type info >/dev/null 2>&1 || { info() { echo "→ $*"; }; ok() { echo "✓ $*"; }
                               warn() { echo "⚠ $*"; }; err() { echo "✗ $*" >&2; }; }

# CI's "cargo clippy (divoomd, all targets/features, deny warnings)" step
# (.github/workflows/tests.yml, rust-core job), flag for flag.
# tests/test_linux_all_features_parity.py holds the two together.
CI_CLIPPY_ARGS=(-p divoomd --all-targets --all-features -- -D warnings)

# The image: stable Rust + the clippy component CI's job installs. It is
# built once and cached; the base is `rust:latest`, so a refreshed base
# rebuilds it.
BASE_IMAGE="${DIVOOM_LINUX_LINT_BASE_IMAGE:-rust:latest}"
IMAGE="${DIVOOM_LINUX_LINT_IMAGE:-divoom-linux-lint:latest}"
# Where the container's cargo target dir and registry live. The target dir is
# OUTSIDE the checkout on purpose: the Linux artifacts must not land in the
# repo's own target/, where tools/check_built_binaries.py would read a Linux
# binary as the macOS one.
CACHE="${DIVOOM_LINUX_LINT_CACHE:-$HOME/.cache/divoom-linux-lint}"

if [ "${DIVOOM_SKIP_LINUX_ALL_FEATURES:-}" = "1" ]; then
    warn "[linux-all-features] SKIPPED by DIVOOM_SKIP_LINUX_ALL_FEATURES=1 — CI's Linux --all-features lint is unchecked here"
    exit 0
fi

missing=""
command -v docker >/dev/null 2>&1 || missing+=" docker"
if [ -n "$missing" ]; then
    printf '✗ [linux-all-features] cannot run, missing:%s\n' "$missing" >&2
    printf '  This gate IS CI'"'"'s Linux --all-features lint. Install Docker, or\n' >&2
    printf '  type DIVOOM_SKIP_LINUX_ALL_FEATURES=1 to skip it loudly.\n' >&2
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    printf '✗ [linux-all-features] docker is installed but not running (start it, e.g. `colima start`)\n' >&2
    exit 1
fi

mkdir -p "$CACHE/target"

# Build the lint image when it is missing. `--progress=plain` keeps the
# component download out of the way of the gate's own output.
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    info "[linux-all-features] building $IMAGE (one time; stable Rust + clippy)"
    printf 'FROM %s\nRUN rustup component add clippy\n' "$BASE_IMAGE" \
        | docker build -t "$IMAGE" - >/dev/null
fi

info "[linux-all-features] CI's Linux clippy, flag for flag: cargo clippy ${CI_CLIPPY_ARGS[*]}"
LOG="${TMPDIR:-/tmp}/divoom_linux_all_features.log"
set +e
docker run --rm \
    -v "$ROOT":/w -w /w \
    -v "$HOME/.cargo/registry":/cache/cargo/registry \
    -v "$HOME/.cargo/git":/cache/cargo/git \
    -v "$CACHE/target":/cache/target \
    -e CARGO_HOME=/cache/cargo \
    -e CARGO_TARGET_DIR=/cache/target \
    -e PATH="/usr/local/cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    "$IMAGE" \
    bash -c "set -euo pipefail
        apt-get update -qq >/dev/null 2>&1
        apt-get install -y -qq libdbus-1-dev pkg-config >/dev/null 2>&1
        rustc --version
        cargo clippy ${CI_CLIPPY_ARGS[*]}" >"$LOG" 2>&1
rc=$?
set -e
if [ "$rc" -ne 0 ]; then
    grep -E "^(error|warning)" "$LOG" | head -30 || true
    echo "  full log: $LOG"
    err "[linux-all-features] FAILED — CI's Linux --all-features lint is red here too"
    exit 1
fi
toolchain="$(awk '/^rustc /{print; exit}' "$LOG")"
if [ -n "$toolchain" ]; then
    step "$toolchain"
fi
ok "[linux-all-features] OK — divoomd lints clean on Linux with --all-features (CI flags)"
