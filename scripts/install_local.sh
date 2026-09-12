#!/usr/bin/env bash
#
# install_local.sh — install dist/Divoom.app into /Applications and PROVE that
# the daemon now running is the one just installed.
#
# The proof is the whole point. On 2026-09-07 the same install was done by hand
# three times and silently failed twice, because two things conspire:
#
#   * the GUI SUPERVISES the daemon and respawns it the instant one exits, so
#     "shut the daemon down, copy the binary, relaunch" restarts it from the OLD
#     file before the copy lands; and
#   * `open` on an already-running app only ACTIVATES it — it launches nothing.
#
# Every step reported success and a hardware measurement was taken against the
# previous build, which turned a correct hypothesis into a recorded "disproven".
#
# A checksum against target/release/divoomd does NOT settle it either: codesign
# rewrites the binary in place, so the installed copy legitimately differs
# byte-for-byte. The reliable comparison is the running process's text inode
# against the inode of the file on disk.
#
#   scripts/install_local.sh              # install, relaunch, verify
#   scripts/install_local.sh --no-launch  # install and verify the files only
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GOH="${GOH_DIR:-$HOME/Projects/gates_of_heck}"
[ -f "$GOH/tui/lib.sh" ] && source "$GOH/tui/lib.sh"

# Fallbacks so this script still runs where the house TUI is absent, rather
# than dying on an undefined function inside the failure path it exists for.
type info >/dev/null 2>&1 || info() { echo "→ $*"; }
type ok   >/dev/null 2>&1 || ok()   { echo "✓ $*"; }
type warn >/dev/null 2>&1 || warn() { echo "⚠ $*" >&2; }
type err  >/dev/null 2>&1 || err()  { echo "✗ $*" >&2; }
type die  >/dev/null 2>&1 || die()  { err "$*"; exit 1; }
type section >/dev/null 2>&1 || section() { echo; echo "── $* ──"; }

SRC="$ROOT/dist/Divoom.app"
DEST="/Applications/Divoom.app"
BUNDLE_ID="com.divoom.control"
DAEMON_REL="Contents/Frameworks/bin/divoomd"
LAUNCH=1
[ "${1:-}" = "--no-launch" ] && LAUNCH=0

[ -d "$SRC" ] || die "no $SRC — run scripts/build_release.sh first"
[ -x "$SRC/$DAEMON_REL" ] || die "no daemon inside $SRC/$DAEMON_REL"

section "quiescing"
# Quit by BUNDLE ID, never by LaunchServices name: `tell application "Divoom"`
# can launch a stranger's app of that name. Same rule check_applescript_launch.py
# enforces on this repo's source.
osascript -e "tell application id \"$BUNDLE_ID\" to quit" >/dev/null 2>&1 || true
sleep 2
# The supervisor is what respawns the daemon, so it has to go too, and the
# install must not proceed until nothing is left holding the old binary.
pkill -f "Divoom.app/Contents/Frameworks/bin/" >/dev/null 2>&1 || true
pkill -f "Divoom.app/Contents/MacOS/Divoom" >/dev/null 2>&1 || true
sleep 2
if pgrep -f "Divoom.app/Contents/" >/dev/null 2>&1; then
    pgrep -fl "Divoom.app/Contents/" >&2 || true
    die "processes still running from a Divoom bundle — refusing to install over them"
fi
ok "nothing running from a Divoom bundle"

section "installing"
rm -rf "$DEST"
cp -R "$SRC" "$DEST"
# shellcheck source=scripts/codesign_identity.sh
. "$(dirname "$0")/codesign_identity.sh"
if divoom_codesign "$DEST" 2>/dev/null; then
    ok "signed $DEST"
else
    warn "codesign failed (an unsigned bundle still runs locally)"
fi
DEST_INODE="$(stat -f '%i' "$DEST/$DAEMON_REL")"
info "installed daemon inode $DEST_INODE"
"$DEST/$DAEMON_REL" --version | sed 's/^/  /'

if [ "$LAUNCH" -eq 0 ]; then
    ok "installed (not launched; --no-launch)"
    exit 0
fi

section "launching and proving"
open "$DEST"
PID=""
for _ in $(seq 1 15); do
    sleep 1
    PID="$(pgrep -f "$DEST/$DAEMON_REL" | head -1 || true)"
    [ -n "$PID" ] && break
done
[ -n "$PID" ] || die "no daemon appeared from $DEST after 15s"

RUN_INODE="$(lsof -p "$PID" 2>/dev/null \
    | awk '$4=="txt" && $NF ~ /divoomd$/ {print $(NF-1); exit}')"
info "daemon pid $PID, running image inode ${RUN_INODE:-<unknown>}"

if [ -z "$RUN_INODE" ]; then
    die "could not read the running image's inode — the install is UNVERIFIED"
fi
if [ "$RUN_INODE" != "$DEST_INODE" ]; then
    err "the running daemon is NOT the binary just installed"
    err "  running $RUN_INODE, on disk $DEST_INODE"
    err "  something respawned it from an older file; do not trust any"
    err "  measurement taken against this process."
    exit 1
fi
ok "the running daemon IS the binary just installed (inode $RUN_INODE)"
