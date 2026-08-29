#!/usr/bin/env bash
# build.sh — build divoom-control's runtime pieces: the Python UI's native
# companions.
#
# The desktop UI is the Python pywebview GUI (run it with ./run.sh). At runtime
# the GUI spawns two native Rust binaries — this script builds them, plus the C
# encoder dylib they use:
#   - divoomd        (the daemon)
#   - divoom-menubar (the menubar/tray agent)
#   - libdivoom_compact.dylib (C image encoder, macOS, via FFI)
#
# For a shippable Python .app bundle, use scripts/build_release.sh (py2app).
#
#   ./build.sh           release binaries + encoder dylib
#   ./build.sh --debug   debug build (faster compile, slower runtime)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

# C encoder dylib (image / pixel-art / text encoding via FFI). macOS → .dylib.
if [[ "$(uname -s)" == "Darwin" ]]; then
  info "building C encoder dylib"
  if bash scripts/build_libdivoom.sh >/dev/null 2>&1; then
    ok "libdivoom_compact.dylib"
  else
    warn "encoder dylib build failed — image push won't encode (UI/control still work)"
  fi
fi

# The MediaRemote helper the daemon shells out to for now-playing + album art.
if [[ "$(uname -s)" == "Darwin" ]]; then
  if bash scripts/build_nowplaying_helper.sh >/dev/null 2>&1; then
    ok "now-playing helper"
  else
    warn "now-playing helper failed to build — album art will report unavailable"
  fi
fi

info "cargo build ${FLAG:-(debug)} — divoomd"
cargo build $FLAG -p divoomd
ok "divoomd"

info "cargo build ${FLAG:-(debug)} — divoom-menubar"
cargo build $FLAG -p divoom-menubar
ok "divoom-menubar"

section "Done"
ok "binaries under target/$PROFILE/"
if [[ "$PROFILE" == "debug" ]]; then
  info "run the app with:  ./run.sh --debug"
else
  info "run the app with:  ./run.sh"
fi
