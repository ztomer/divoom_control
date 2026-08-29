#!/usr/bin/env bash
# Build script for the native libdivoom_compact shared library.
# Combines four C sources into a single shared library (all under divoom_lib — R17):
#   - divoom_lib/native_src/compact.c          (tile compacting + framing — encode_basic/ios_le)
#   - divoom_lib/native_src/downsample.c       (LANCZOS3 downscale — used by the library)
#   - divoom_lib/native_src/image_encode.c     (16x16 palette encoder for 0x44/0x49)
#   - divoom_lib/native_src/image_encode_32.c  (32x32 encoder + 0x8B 3-phase chunker — Round 4)
#
# compact.c exports encode_basic_payload + encode_ios_le_payload used by
# divoom_lib/framing.py.
#
# Cross-platform (R20): produces a .dylib on macOS and a .so on Linux. The
# Python loaders resolve the right name via divoom_lib/native_lib.py.
#
# Usage:  ./scripts/build_libdivoom.sh
# Output: ./divoom_lib/libdivoom_compact.{dylib|so} (overwrites existing)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LIB_DIR="${PROJECT_ROOT}/divoom_lib"
NATIVE_SRC_DIR="${LIB_DIR}/native_src"

# OS/ARCH are overridable so the platform gate below is testable without a
# cross-arch machine (tests/test_build_platform_gate.py drives it).
OS="${DIVOOM_BUILD_OS:-$(uname -s)}"
ARCH="${DIVOOM_BUILD_ARCH:-$(uname -m)}"

# -ffp-contract=off: forbid FMA contraction of `a*b+c` into a single fused op.
# At -O3 with SIMD, clang contracts differently across versions/arches, which
# made the LANCZOS3 downscaler byte-exact locally but 1 LSB off PIL on the CI
# runner's clang (the test_native_downscaler::test_stress_random flake). Off =
# IEEE-strict separate multiply+add everywhere, matching PIL's scalar math.
CFLAGS=(-O3 -ffp-contract=off -fPIC -Wall -Wextra -Wno-unused-parameter)
ARCH_FLAGS=()
LD_FLAGS=()

case "${OS}" in
  Darwin)
    CC="${CC:-clang}"
    OUT="${LIB_DIR}/libdivoom_compact.dylib"
    CFLAGS+=(-dynamiclib)
    # shellcheck disable=SC2054  # the commas are inside single -Wl, arguments
    LD_FLAGS=(
      -dynamiclib
      -Wl,-install_name,@rpath/libdivoom_compact.dylib
      -Wl,-undefined,dynamic_lookup
    )
    ;;
  Linux)
    CC="${CC:-cc}"
    OUT="${LIB_DIR}/libdivoom_compact.so"
    CFLAGS+=(-shared)
    LD_FLAGS=(-shared -lm)
    ;;
  *)
    # R67: this used to warn and build a generic .so anyway — the same
    # silently-ships-an-untested-binary shape the ARCH gate below already
    # rejects. R66 hard-failed the arch case and left this one; supported
    # OSes are macOS and Linux, and anything else is a hard failure.
    echo "✗ Unsupported OS: ${OS}. Supported: Darwin (Apple silicon), Linux." >&2
    exit 1
    ;;
esac

# ── Platform gate: 64-bit only ────────────────────────────────────────
# macOS is Apple silicon only — Apple has dropped Intel Macs, so have we.
# Linux keeps x86_64 (and aarch64); only macOS loses its x86_64 build.
if [[ "${OS}" == "Darwin" && ( "${ARCH}" == "x86_64" || "${ARCH}" == "amd64" ) ]]; then
  echo "✗ macOS Intel (x86_64) is not supported — Apple silicon (arm64) only." >&2
  echo "  Linux x86_64 remains supported; this gate is macOS-specific." >&2
  exit 1
fi

# Detect arch — ARM gets NEON, x86_64 gets SSE2. Anything else is a hard
# failure: a 32-bit build (i686/armv7) previously fell through to a silent
# "no SIMD flags" build that was never compiled, run, or tested by anyone.
case "${ARCH}" in
  arm64|aarch64)
    ARCH_FLAGS=(-march=armv8-a+simd)
    ;;
  x86_64|amd64)
    ARCH_FLAGS=(-msse2)
    ;;
  *)
    echo "✗ Unsupported architecture: ${ARCH}. 64-bit only (arm64/aarch64 or x86_64)." >&2
    exit 1
    ;;
esac

# Test seam: exit right after the platform gate, before the (slow) compile, so
# the ACCEPT direction of the gate is testable too — not just the reject path.
if [[ -n "${DIVOOM_BUILD_GATE_ONLY:-}" ]]; then
  echo "gate ok: ${OS}/${ARCH}"
  exit 0
fi

echo "Building ${OUT} for ${OS}/${ARCH} with ${CC}…"
"${CC}" "${CFLAGS[@]}" "${ARCH_FLAGS[@]}" \
  -I"${NATIVE_SRC_DIR}" \
  "${NATIVE_SRC_DIR}/compact.c" \
  "${NATIVE_SRC_DIR}/downsample.c" \
  "${NATIVE_SRC_DIR}/downsample_kernel.c" \
  "${NATIVE_SRC_DIR}/image_encode.c" \
  "${NATIVE_SRC_DIR}/image_encode_32.c" \
  "${LD_FLAGS[@]}" \
  -o "${OUT}"

echo "Done."
if command -v file >/dev/null 2>&1; then
  file "${OUT}"
fi
