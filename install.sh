#!/usr/bin/env bash
# install.sh — build the current source and install Divoom Control to
# /Applications, so the app runs from there with no dependency on this checkout.
#
# WHAT THIS FIXES (R67/C5). Today `Divoom.app` in the repo root is a DEV bundle:
# its launcher is `exec python3 divoom_gui/gui_main.py` against the source tree,
# and it does no cleanup at all. Single-instance enforcement lives only in
# `run.sh`, so launching the app the normal way — from Finder, from the Dock —
# gave you no protection against a second daemon. Two daemons fighting over a
# single-owner BLE device is exactly the "connection is unreliable" symptom this
# round chased down, and one orphan had been running for 34 hours.
#
# The installed bundle carries the daemon and the menubar agent INSIDE it
# (PyInstaller collects them under Contents/Frameworks/bin), so there is one
# obvious copy of each binary and no way to accidentally run a stale one from
# target/release.
#
# Usage:
#   ./install.sh                 # build + install to /Applications
#   ./install.sh --no-build      # install whatever is already in dist/
#   ./install.sh --uninstall     # remove the installed app (and stop it)
#   ./install.sh --launch        # also start it when done
#
# macOS only: the bundle is a macOS TCC artifact (Bluetooth + Apple Events usage
# strings must be attributed to the responsible bundle).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
# shellcheck source=/dev/null
. "${GOH_DIR:-$HOME/Projects/gates_of_heck}/tui/lib.sh"

DEST_DIR="/Applications"
APP_NAME="Divoom.app"
DEST="$DEST_DIR/$APP_NAME"
BUILD=1
LAUNCH=0
UNINSTALL=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-build)  BUILD=0 ;;
    --launch)    LAUNCH=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help)   grep '^#' "$0" | cut -c3- ; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
  shift
done

[[ "$(uname -s)" == "Darwin" ]] || die "install.sh is macOS-only (the .app bundle is a macOS TCC artifact)"

# ── stop anything currently running ───────────────────────────────────────
# Both paths need this: an upgrade must not leave the OLD daemon holding the
# device while the new app starts, and an uninstall must not orphan one.
stop_running() {
  local found=0
  for pat in "divoom_gui.gui_main" "divoom_gui/gui_main.py" "Divoom.app/Contents/MacOS/Divoom" \
             "divoomd" "divoom-menubar"; do
    if pgrep -f "$pat" >/dev/null 2>&1; then
      pkill -f "$pat" 2>/dev/null || true
      found=1
    fi
  done
  if [[ "$found" == "1" ]]; then
    sleep 2
    # Second pass for anything that ignored SIGTERM.
    for pat in "divoomd" "divoom-menubar"; do
      pkill -9 -f "$pat" 2>/dev/null || true
    done
    ok "stopped running Divoom processes"
  else
    info "nothing running"
  fi
  # The daemon only unlinks a socket it still owns (R67/C5), so a socket can
  # outlive a SIGKILL. Clear the well-known paths after everything is down.
  rm -f /tmp/divoom.sock /tmp/divoomd.sock /tmp/divoom_gui.lock 2>/dev/null || true
}

if [[ "$UNINSTALL" == "1" ]]; then
  section "Uninstall"
  stop_running
  if [[ -d "$DEST" ]]; then
    rm -rf "$DEST"
    ok "removed $DEST"
  else
    warn "not installed: $DEST"
  fi
  info "user data was left alone (settings, presets, gallery cache)"
  exit 0
fi

VERSION="$(grep -m1 '^version' pyproject.toml | sed -E 's/.*"(.*)".*/\1/')"
section "Divoom Control v${VERSION} → ${DEST}"

# ── build ─────────────────────────────────────────────────────────────────
if [[ "$BUILD" == "1" ]]; then
  PYBUILD="${ROOT}/.buildvenv/bin/python"
  if [[ ! -x "$PYBUILD" ]]; then
    info "creating build venv (.buildvenv)"
    python3 -m venv .buildvenv
    "$PYBUILD" -m pip install --quiet --upgrade pip
    "$PYBUILD" -m pip install --quiet -e '.[gui]' pyinstaller psutil \
      || die "could not install build dependencies"
  fi
  "$PYBUILD" -c "import PyInstaller" 2>/dev/null \
    || "$PYBUILD" -m pip install --quiet pyinstaller psutil

  info "building self-contained bundle (this takes a few minutes)"
  # build_release.sh owns the bundle: native dylib, divoomd, divoom-menubar,
  # icon, PyInstaller, the references leak-guard, and the adhoc signature. This
  # script does not duplicate any of it — one builder, one bundle.
  bash scripts/build_release.sh "$PYBUILD"
else
  info "skipping build (--no-build)"
fi

SRC="$ROOT/dist/$APP_NAME"
[[ -d "$SRC" ]] || die "no bundle at $SRC — run without --no-build"

# The bundle must be self-contained: the daemon and menubar have to be INSIDE
# it, or the installed app would reach back into this checkout's target/release
# and silently run whatever is there.
for b in divoomd divoom-menubar; do
  found="$(find "$SRC" -name "$b" -type f -perm -u+x 2>/dev/null | head -1)"
  [[ -n "$found" ]] || die "bundle is missing $b — it would fall back to the source tree"
  info "bundled $b: ${found#"$SRC"/}"
done

# ── install ───────────────────────────────────────────────────────────────
section "Installing"
stop_running

if [[ -d "$DEST" ]]; then
  info "replacing existing install"
  rm -rf "$DEST"
fi

# Copy to a staging name first, then move into place, so an interrupted copy
# never leaves a half-written .app that Finder will happily try to launch.
STAGING="$DEST_DIR/.divoom-install-$$"
rm -rf "$STAGING"
if ! cp -R "$SRC" "$STAGING" 2>/dev/null; then
  rm -rf "$STAGING"
  die "cannot write to $DEST_DIR — re-run with sufficient permissions"
fi
mv "$STAGING" "$DEST"
ok "installed $DEST"

# Make LaunchServices pick up the fresh bundle (icon, Info.plist, TCC identity).
touch "$DEST"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -f "$DEST" 2>/dev/null || true

installed_version="$(/usr/bin/defaults read "$DEST/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null || echo "?")"
ok "version ${installed_version}"

section "Done"
info "launch:    open -a Divoom"
info "uninstall: ./install.sh --uninstall"
info "The first run prompts for Bluetooth, and for Automation when a music"
info "player is queried. Both are attributed to the installed bundle."

if [[ "$LAUNCH" == "1" ]]; then
  info "launching..."
  open "$DEST"
fi
