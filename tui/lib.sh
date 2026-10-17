#!/usr/bin/env bash
# tui/lib.sh — Kare TUI output primitives (vendored from ~/projects/scripts/_lib.sh).
# Source at the top of any script:  source "$(dirname "$0")/tui/lib.sh"
# Self-contained: reads tui/stylerc (repo source of truth), no machine dependency.
# Icons: → · ✓ ✗ ⚠   Colors: restrained, NO_COLOR + non-tty aware (degrades to plain text).
# Consumers load HEAD's copy of this file, never the shared working tree (C4, gates/_from_head.sh).
# (A copy of this file outside a gates checkout -- vendored, against the house rule -- has no
# gates/ beside it, and loads itself.)
if [ -f "$(dirname "${BASH_SOURCE[0]}")/../gates/_from_head.sh" ]; then
    . "$(dirname "${BASH_SOURCE[0]}")/../gates/_from_head.sh" && goh_from_head_lib "${BASH_SOURCE[0]}" && return 0
fi

_TUI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

# Icons + colors from the repo stylerc (fall back to Kare defaults if absent).
ICON_START="→"; ICON_STEP="·"; ICON_OK="✓"; ICON_ERR="✗"; ICON_WARN="⚠"
# shellcheck disable=SC1091
[ -f "$_TUI_DIR/stylerc" ] && source "$_TUI_DIR/stylerc"

# no-color.org spec: ANY non-empty NO_COLOR value disables color (NO_COLOR=0
# is still a set variable — "0" used to re-enable color here).
if [[ -t 1 ]] && [[ -z "${NO_COLOR:-}" ]]; then
  : "${C_RESET:=\033[0m}"; : "${C_DIM:=\033[2m}"; : "${C_BOLD:=\033[1m}"
  : "${C_GREEN:=\033[0;32m}"; : "${C_RED:=\033[0;31m}"
  : "${C_YELLOW:=\033[0;33m}"; : "${C_GRAY:=\033[0;90m}"
else
  C_RESET=''; C_DIM=''; C_BOLD=''; C_GREEN=''; C_RED=''; C_YELLOW=''; C_GRAY=''
fi

# Decode the stylerc's literal \033 sequences into real ESC characters ONCE,
# here — output functions use printf '%s', which (unlike echo -e) never
# interprets escapes at print time. That is deliberate: a config-derived
# label containing backslash-n must stay data. lib.py does the same decode
# in its stylerc parser.
_TUI_ESC="$(printf '\033')"
for _c in C_RESET C_DIM C_BOLD C_GREEN C_RED C_YELLOW C_GRAY; do
    printf -v "$_c" '%s' "${!_c//\\033/$_TUI_ESC}"
done
unset _c _TUI_ESC

export ICON_START ICON_STEP ICON_OK ICON_ERR ICON_WARN
export C_RESET C_DIM C_BOLD C_GREEN C_RED C_YELLOW C_GRAY

# ── Log functions ──────────────────────────────────────────────────────
# Private implementations first; EVERY public name (and the _lib_* alias set)
# delegates here. Call cycles are structurally impossible: nothing ever calls
# a name that could itself be re-overlaid by a consumer.
# printf '%s\n', never `echo -e` with interpolated data: a config-derived
# label containing \n, %s or backslash escapes stays DATA, never format.
# warn goes to STDERR like err — it is a diagnostic, not program output.
_tui_info() { printf '%s\n' "${C_GRAY}${ICON_START}${C_RESET} ${C_DIM}$1${C_RESET}"; }
_tui_step() { printf '%s\n' "${C_DIM}${ICON_STEP} $1${C_RESET}"; }
_tui_ok()   { printf '%s\n' "${C_GREEN}${ICON_OK}${C_RESET} $1"; }
_tui_err()  { printf '%s\n' "${C_RED}${ICON_ERR}${C_RESET} $1" >&2; }
_tui_warn() { printf '%s\n' "${C_YELLOW}${ICON_WARN}${C_RESET} $1" >&2; }

info()  { _tui_info "$1"; }
step()  { _tui_step "$1"; }   # a sub-item under an info line
ok()    { _tui_ok "$1"; }
err()   { _tui_err "$1"; }
warn()  { _tui_warn "$1"; }
die()   { err "$1"; exit "${2:-1}"; }
bold()  { printf '%s\n' "${C_BOLD}$1${C_RESET}"; }

# Private aliases: gates/_common.sh overlays its fallbacks onto the public
# names unconditionally, then re-overlays from these _lib_* names when present.
# Without them the styled lib could never engage (the overlay always won).
_lib_info() { _tui_info "$1"; }
_lib_ok()   { _tui_ok "$1"; }
_lib_warn() { _tui_warn "$1"; }
_lib_err()  { _tui_err "$1"; }

# ── Dividers ───────────────────────────────────────────────────────────
# Build the rule by concatenation — `tr ' ' '─'` mangles the multibyte ─ (byte-oriented).
hr() {
  local cols="${1:-72}" line="" i
  for ((i = 0; i < cols; i++)); do line+="─"; done
  printf '%s\n' "${C_GRAY}${line}${C_RESET}"
}

section() { printf '\n'; hr; bold "  $1"; hr; }

# ── Utilities ──────────────────────────────────────────────────────────
require_commands() {
  local missing=()
  for cmd in "$@"; do
    command -v "$cmd" &>/dev/null || missing+=("$cmd")
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    die "Missing required commands: ${missing[*]}"
  fi
}
