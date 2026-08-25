#!/usr/bin/env bash
# run.sh — run divoom-control: the Python pywebview GUI, which auto-spawns the
# native Rust daemon (divoomd) and the native Rust menubar (divoom-menubar).
# Build the native bits first with ./build.sh.
#
# Before launching, it finds and kills any existing divoom processes (Python +
# Rust daemon, menubar, GUI) and clears stale sockets, so we always start from a
# clean slate (otherwise the GUI's single-instance guard reuses a stale daemon).
#
#   ./run.sh            launch the GUI (auto-spawns daemon + menubar)
#   ./run.sh --menubar  run ONLY the Rust menubar agent in the foreground
#                       (quick tray smoke; needs a daemon for live status)
#   ./run.sh --debug    prefer the debug Rust binaries
#
# Socket defaults to /tmp/divoom.sock; override with DIVOOM_SOCKET.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/Users/ztomer/Projects/gates_of_heck/tui/lib.sh
GOH="${GOH_DIR:-$HOME/Projects/gates_of_heck}"
source "$GOH/tui/lib.sh"
cd "$ROOT"

PROFILE="release"; MODE="gui"
for a in "$@"; do
  case "$a" in
    --menubar)  MODE="menubar" ;;
    --debug)    PROFILE="debug" ;;
    -h|--help)  echo "usage: ./run.sh [--menubar] [--debug]"; exit 0 ;;
    *)          die "unknown option: $a (try --help)" ;;
  esac
done

MENUBAR="target/$PROFILE/divoom-menubar"

# Find + stop processes whose command line matches $1 (TERM, then KILL stragglers).
# Patterns are specific enough not to match this script (bash .../run.sh).
kill_pat() {
  local pat="$1" label="$2" pids
  pids="$(pgrep -f "$pat" 2>/dev/null || true)"
  [[ -z "$pids" ]] && return 0
  info "stopping $label (${pids//$'\n'/ })"
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true
  sleep 0.3
  pids="$(pgrep -f "$pat" 2>/dev/null || true)"
  # shellcheck disable=SC2086
  [[ -n "$pids" ]] && kill -9 $pids 2>/dev/null || true
  return 0
}

if [[ "$MODE" == "menubar" ]]; then
  [[ -x "$MENUBAR" ]] || die "menubar not built — run ./build.sh${PROFILE/release/} first"
  kill_pat "divoom-menubar" "existing menubar"
  section "Rust menubar (foreground)"
  info "Ctrl-C to quit. Launch Dashboard needs DIVOOM_GUI_PYTHON/SCRIPT (the GUI sets these)."
  export DIVOOM_GUI_PYTHON="${DIVOOM_GUI_PYTHON:-$(command -v python3)}"
  export DIVOOM_GUI_SCRIPT="${DIVOOM_GUI_SCRIPT:-$ROOT/divoom_gui/gui_main.py}"
  exec "$MENUBAR"
fi

# Default (GUI): clean slate, then launch. The GUI spawns the daemon + menubar.
require_commands python3

section "Cleanup — stopping any existing divoom processes"
kill_pat "divoom_gui.gui_main" "GUI"
kill_pat "divoom_lib.cli daemon" "Python daemon"
kill_pat "divoomd"               "Rust daemon"
kill_pat "divoom-menubar"        "menubar"
rm -f /tmp/divoom.sock /tmp/divoomd.sock /tmp/divoom_gui.lock 2>/dev/null || true
ok "clean slate"

[[ -x "$MENUBAR" ]] || warn "menubar not built (no tray this run) — ./build.sh to enable it"
section "Divoom GUI (Python) + native daemon/menubar"
info "the GUI spawns divoomd + divoom-menubar; first BLE use prompts for Bluetooth"
exec python3 -m divoom_gui.gui_main
