#!/usr/bin/env bash
# build.sh — build divoom-control's runtime pieces: the Python UI's native
# companions.
#
# The desktop UI is the Python pywebview GUI (run it with ./run.sh). At runtime
# the GUI spawns two native Rust binaries, and this script builds them:
#   - divoomd        (the daemon — cross-platform; Linux builds it too)
#   - divoom-menubar (the menubar/tray agent — macOS only, no Linux build)
#
# The C encoder dylib that used to be built here went with the C chain (L4,
# 2026-09-25): the daemon encodes in Rust now.
#
# For a shippable Python .app bundle, use scripts/build_release.sh.
#
#   ./build.sh           release binaries
#   ./build.sh --debug   debug build (faster compile, slower runtime)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The platform gate comes first, and ahead of the house TUI library: a host this
# script does not build for is refused whether or not GOH_DIR is set up.
# shellcheck source=scripts/lib/platform_gate.sh
. "$ROOT/scripts/lib/platform_gate.sh"
divoom_platform_gate core "builds the cross-platform daemon core (divoomd)"

# shellcheck source=/Users/ztomer/Projects/gates_of_heck/tui/lib.sh
GOH="${GOH_DIR:-$HOME/Projects/gates_of_heck}"
source "$GOH/tui/lib.sh"
cd "$ROOT"

PROFILE="release"; FLAG="--release"
for a in "$@"; do
  case "$a" in
    --debug)   PROFILE="debug"; FLAG="" ;;
    -h|--help) echo "usage: ./build.sh [--debug]"; exit 0 ;;
    *)         die "unknown option: $a (try --help)" ;;
  esac
done

require_commands cargo

section "Native Rust binaries ($PROFILE)"

# The MediaRemote helper the daemon shells out to for now-playing + album art.
if [[ "$DIVOOM_BUILD_OS" == "Darwin" ]]; then
  if bash scripts/build_nowplaying_helper.sh >/dev/null 2>&1; then
    ok "now-playing helper"
  else
    warn "now-playing helper failed to build — album art will report unavailable"
  fi
fi

info "cargo build ${FLAG:-(debug)} — divoomd"
cargo build $FLAG -p divoomd
ok "divoomd"

# divoom-menubar is macOS-only: its tray deps are Apple-target code and the
# crate has no Linux build (which is also why CI's Linux job lints divoomd
# alone). On Linux this script builds the daemon core, which is what Linux
# supports — see the policy at the top.
if [[ "$DIVOOM_BUILD_OS" == "Darwin" ]]; then
  info "cargo build ${FLAG:-(debug)} — divoom-menubar"
  cargo build $FLAG -p divoom-menubar
  ok "divoom-menubar"
fi

section "Done"
ok "binaries under target/$PROFILE/"
if [[ "$PROFILE" == "debug" ]]; then
  info "run the app with:  ./run.sh --debug"
else
  info "run the app with:  ./run.sh"
fi
