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
# The toolchain is a NAMED `rust:<version>-<debian>` image (BASE_TAG below),
# never the moving `latest` tag (house rule: latest is a named release); raise
# it with the stable toolchain, in its own commit. The gate PRINTS the
# toolchain it used, so a drift between this and CI's `stable` is visible in
# the log rather than silent.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

GOH="${GOH_DIR:-$HOME/Projects/gates_of_heck}"
# shellcheck disable=SC1091
[ -f "$GOH/tui/lib.sh" ] && source "$GOH/tui/lib.sh"
type info >/dev/null 2>&1 || { info() { echo "→ $*"; }; ok() { echo "✓ $*"; }
                               warn() { echo "⚠ $*"; }; err() { echo "✗ $*" >&2; }; }
type step >/dev/null 2>&1 || step() { echo "· $*"; }

# CI's "cargo clippy (divoomd, all targets/features, deny warnings)" step
# (.github/workflows/tests.yml, rust-core job), flag for flag.
# tests/test_linux_all_features_parity.py holds the two together.
CI_CLIPPY_ARGS=(-p divoomd --all-targets --all-features -- -D warnings)

# The image: a named stable Rust + the clippy component CI's job installs. It
# is built once and cached under a tag that carries the base's, so raising
# BASE_TAG builds a new image instead of reusing the old toolchain's.
# tests/test_linux_all_features_parity.py holds both to a named release.
BASE_TAG="${DIVOOM_LINUX_LINT_BASE_TAG:-1.100.0-trixie}"
BASE_IMAGE="${DIVOOM_LINUX_LINT_BASE_IMAGE:-rust:$BASE_TAG}"
IMAGE="${DIVOOM_LINUX_LINT_IMAGE:-divoom-linux-lint:$BASE_TAG}"
# Where the container's cargo target dir lives: a docker NAMED volume. It is
# OUTSIDE the checkout on purpose (the Linux artifacts must not land in the
# repo's own target/, where tools/check_built_binaries.py would read a Linux
# binary as the macOS one), and it is NOT a host directory (DV.LINTEXEC): cargo
# execs the build scripts it links there, and on a host bind mount through
# colima's virtiofs the linker's exec bit did not always reach the file
# (0.45.7's push: `Permission denied (os error 13)` on a build-script-build left
# at mode 644 on both sides, while the same link re-run was 755). A named volume
# lives on the VM's own Linux filesystem, so the verdict cannot hang on host
# mount semantics. It persists across `colima stop`, so the cache stays warm.
# tests/test_linux_all_features_runtime.py holds the target to a named volume.
TARGET_VOLUME="${DIVOOM_LINUX_LINT_TARGET_VOLUME:-divoom-linux-lint-target}"

if [ "${DIVOOM_SKIP_LINUX_ALL_FEATURES:-}" = "1" ]; then
    warn "[linux-all-features] SKIPPED by DIVOOM_SKIP_LINUX_ALL_FEATURES=1 — CI's Linux --all-features lint is unchecked here"
    exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
    # A GitHub-hosted macOS runner has no docker, and no commit can give it one: there, and
    # only there, the step is NOT APPLICABLE (exit 78, gates_of_heck lib/not_applicable.py; goh's
    # local_ci accepts it on a hosted run only). The same script runs unedited in tests.yml's
    # linux-all-features job, which has docker, so the lint is still run hosted (CI.PUBLIC2).
    if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
        printf '⚠ NOT APPLICABLE on this hosted runner: the Linux --all-features lint needs docker, which is not here -- not a pass and not a failure; the linux-all-features job runs it, and the owner'"'"'s machine is the judge of record\n' >&2
        exit 78
    fi
    printf '✗ [linux-all-features] cannot run, missing: docker\n' >&2
    printf '  This gate IS CI'"'"'s Linux --all-features lint. Install Docker, or\n' >&2
    printf '  type DIVOOM_SKIP_LINUX_ALL_FEATURES=1 to skip it loudly.\n' >&2
    exit 1
fi
# The container runtime. A gate that goes red because docker happens to be
# down is a gate people learn to skip, so when it is down this gate starts it
# (colima), and stops it again on the way out -- ONLY what goh started, not
# while another gate holds it, and not while anyone else's container is
# running on it (owner ruling OW.27, 2026-10-31). The seam is goh's
# lib/container_runtime.sh (GOH.CR1), which takes the colima binary from `COLIMA`
# (the stub the test drives).
# shellcheck source=/dev/null # goh's lib/container_runtime.sh: outside this repo; gates_of_heck lints it
. "$GOH/lib/container_runtime.sh"
trap goh_container_runtime_down EXIT
if ! goh_container_runtime_up "divoom linux-all-features"; then
    printf '  Start your container runtime, or type DIVOOM_SKIP_LINUX_ALL_FEATURES=1 to skip loudly.\n' >&2
    exit 1
fi


# Build the lint image when it is missing, WITHOUT a docker builder (DV.LINTTIDY).
# `docker build` with no buildx plugin runs the deprecated legacy builder ("DEPRECATED: The legacy
# builder is deprecated and will be removed in a future release"), and house rule 17 forbids building
# on a deprecated API. buildx is a plugin this machine and a runner may not have; the image is the base
# plus ONE rustup component, so it is made by running that command in a container of the base and
# committing the result: the same image, no builder, nothing to install.
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    info "[linux-all-features] making $IMAGE (one time; stable Rust + clippy)"
    BUILD_CTR="divoom-linux-lint-build-$$"
    docker rm -f "$BUILD_CTR" >/dev/null 2>&1 || true
    if ! docker run --name "$BUILD_CTR" "$BASE_IMAGE" rustup component add clippy >/dev/null \
        || ! docker commit "$BUILD_CTR" "$IMAGE" >/dev/null; then
        docker rm -f "$BUILD_CTR" >/dev/null 2>&1 || true
        err "[linux-all-features] could not make $IMAGE from $BASE_IMAGE"
        exit 1
    fi
    docker rm "$BUILD_CTR" >/dev/null 2>&1 || true
fi

# Drop what raising BASE_TAG replaced (DV.LINTTIDY): every other tag of THIS gate's own image
# repository, then the `rust:<tag>` each was made from. 0.45.8 left divoom-linux-lint:1.99.1-trixie
# (2.2 GB) and rust:1.99.1-trixie on the colima disk for good. Only when the image name is the
# default (an overriding DIVOOM_LINUX_LINT_IMAGE is someone's own), never forced (an image a
# container or another image still builds on survives), and the lint image goes before its base.
if [ "$IMAGE" = "divoom-linux-lint:$BASE_TAG" ]; then
    for old in $(docker images --format '{{.Tag}}' divoom-linux-lint 2>/dev/null || true); do
        [ "$old" = "$BASE_TAG" ] && continue
        info "[linux-all-features] removing the image BASE_TAG replaced: divoom-linux-lint:$old"
        docker rmi "divoom-linux-lint:$old" >/dev/null 2>&1 || true
        [ "$old" = "latest" ] || docker rmi "rust:$old" >/dev/null 2>&1 || true
    done
fi

info "[linux-all-features] CI's Linux clippy, flag for flag: cargo clippy ${CI_CLIPPY_ARGS[*]}"
LOG="${TMPDIR:-/tmp}/divoom_linux_all_features.log"
set +e
docker run --rm \
    -v "$ROOT":/w -w /w \
    -v "$HOME/.cargo/registry":/cache/cargo/registry \
    -v "$HOME/.cargo/git":/cache/cargo/git \
    -v "$TARGET_VOLUME":/cache/target \
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
# `-D warnings` after `--` reaches rustc and clippy, not cargo's own manifest lints (`warning:
# unused dependency`), so a run could print a warning and be called OK (DV.LINTTIDY): any warning in
# the log is red.
if grep -qE "^warning" "$LOG"; then
    grep -E "^warning" "$LOG" | head -10 || true
    echo "  full log: $LOG"
    err "[linux-all-features] FAILED — the lint printed a warning (cargo's own lints are not under -D warnings)"
    exit 1
fi
toolchain="$(awk '/^rustc /{print; exit}' "$LOG")"
if [ -n "$toolchain" ]; then
    step "$toolchain"
fi
ok "[linux-all-features] OK — divoomd lints clean on Linux with --all-features (CI flags)"
