#!/usr/bin/env bash
# build_nowplaying_helper.sh — compile the MediaRemote entitled-host helper.
#
# Produces nowplaying/native/libnp_helper.dylib from np_helper.m. The dylib is
# loaded by /usr/bin/perl (see nowplaying/native/np_load.pl) because the
# now-playing read API has been entitlement-gated since macOS 15.4 and perl
# carries that entitlement — a dylib in its process inherits it.
#
# macOS only, and hard-fails elsewhere rather than producing something
# untested: MediaRemote is a macOS private framework and there is nothing to
# build on any other platform (house policy — an unsupported target is a hard
# failure, never a fallback build).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
. "${GOH_DIR:-$HOME/Projects/gates_of_heck}/tui/lib.sh"

OS="${DIVOOM_BUILD_OS:-$(uname -s)}"
[[ "$OS" == "Darwin" ]] || die "the now-playing helper is macOS-only (got ${OS})"

SRC="$ROOT/nowplaying/native/np_helper.m"
OUT="$ROOT/nowplaying/native/libnp_helper.dylib"
CC="${CC:-clang}"

[[ -f "$SRC" ]] || die "missing source: $SRC"
command -v "$CC" >/dev/null 2>&1 || die "$CC not found (install the Xcode command line tools)"

section "now-playing helper"
info "source: ${SRC#"$ROOT"/}"

"$CC" -fobjc-arc -dynamiclib -O2 \
  -mmacosx-version-min=11.0 \
  -framework Foundation \
  -install_name @rpath/libnp_helper.dylib \
  -o "$OUT" "$SRC"

ok "built: ${OUT#"$ROOT"/} ($(du -h "$OUT" | cut -f1))"

# Prove it LOADS and answers, rather than trusting that a clean compile means a
# working dylib. A helper that builds but cannot be loaded by perl is exactly
# the dead-on-arrival tooling this repo just spent a round fixing.
if [[ -x /usr/bin/perl ]]; then
  reply="$(/usr/bin/perl "$ROOT/nowplaying/native/np_load.pl" "$OUT" np_get 2>&1 | head -c 400 || true)"
  case "$reply" in
    '{"ok":true'*)  ok "verified: helper loaded and answered" ;;
    '{"ok":false'*) warn "helper loaded but reported: $reply" ;;
    *)              die "helper did not produce JSON: ${reply:-<no output>}" ;;
  esac
else
  warn "/usr/bin/perl missing — cannot verify the helper here"
fi
