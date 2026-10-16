#!/usr/bin/env bash
# platform_gate.sh — the ONE place that decides whether this host may build what
# a script is about to build. Sourced, not run:
#
#   . "$ROOT/scripts/lib/platform_gate.sh"
#   divoom_platform_gate macos "the .app bundle is a macOS TCC artifact"
#
# House policy: 64-bit only, and macOS is Apple silicon only. Both are HARD
# failures -- never a warning, never a fallback build. The failure this prevents
# is specific and was paid for twice: a `*)` arch branch printed "Unknown arch:
# building with no SIMD flags" and KEPT GOING, so an i686 or armv7 host silently
# produced an untested binary; and the OS branch did the same ("Building a
# generic .so with -shared") until R67 hardened it. An Intel Mac is the same
# shape one level up: it builds, and ships a bundle nobody has run.
#
# This lived inline in `scripts/build_libdivoom.sh` with its test beside it, and
# both went out with the C encoder chain (`9a1cade`, 2026-09-25). Six entry
# points then checked `uname -s` alone and nothing failed, because no test asked
# two of them the same question. One library, called by every entry point, is how
# "the class lost its gate" stops being a thing that can happen quietly.
#
# SEAM: DIVOOM_BUILD_OS / DIVOOM_BUILD_ARCH stand in for `uname`, so the REJECT
# direction is testable on the machine you have rather than the one you don't;
# DIVOOM_BUILD_GATE_ONLY stops the caller immediately after the gate, so the
# ACCEPT direction is testable without doing the slow work. Both are set by
# tests/test_build_platform_gate.py and by nothing else.

# divoom_platform_gate <core|macos> [why]
#   core  -- builds the cross-platform daemon core: Darwin/arm64, and Linux
#            (x86_64/amd64, aarch64/arm64), which the `rust-core` CI job targets.
#            Linux support is why this gate is per script and not global.
#   macos -- produces a macOS artifact (.app, .dmg, .dylib, an installed
#            bundle): Apple silicon only.
# `why` is the caller's one-line reason, printed with a macOS-only refusal so the
# person reading it is told what the script actually does.
divoom_platform_gate() {
  local policy="${1:-core}"
  local why="${2:-this script produces a macOS artifact}"
  local os="${DIVOOM_BUILD_OS:-$(uname -s)}"
  local arch="${DIVOOM_BUILD_ARCH:-$(uname -m)}"

  # Exported so callers branch on these resolved values instead of asking
  # `uname` a second time (build.sh skips its macOS-only steps this way) -- one
  # read, one answer, in the script and in its test.
  export DIVOOM_BUILD_OS="${os}"
  export DIVOOM_BUILD_ARCH="${arch}"

  case "${os}" in
    Darwin | Linux) ;;
    *)
      echo "✗ Unsupported OS: ${os}/${arch}. Supported: Darwin (Apple silicon) and Linux." >&2
      exit 1
      ;;
  esac

  case "${arch}" in
    arm64 | aarch64 | x86_64 | amd64) ;;
    *)
      echo "✗ Unsupported architecture: ${arch} on ${os}. 64-bit only (arm64/aarch64 or x86_64)." >&2
      exit 1
      ;;
  esac

  if [[ "${os}" == "Darwin" ]]; then
    # Apple silicon only. The x86_64 case cannot reach here for Linux, so the
    # message can safely say so, and a reader on the wrong machine learns why.
    case "${arch}" in
      arm64 | aarch64) ;;
      *)
        echo "✗ macOS Intel (${arch}) is not supported — Apple silicon (arm64) only." >&2
        echo "  Linux x86_64 remains supported; this gate is macOS-specific." >&2
        exit 1
        ;;
    esac
  elif [[ "${policy}" != "core" ]]; then
    echo "✗ macOS-only: ${why} (got ${os}/${arch})." >&2
    exit 1
  fi

  # Test seam: exit right after the gate, before the (slow) work, so the ACCEPT
  # direction is testable too -- a gate nobody has seen say yes is a gate nobody
  # has seen at all.
  if [[ -n "${DIVOOM_BUILD_GATE_ONLY:-}" ]]; then
    echo "gate ok: ${os}/${arch} (${policy})"
    exit 0
  fi
}
