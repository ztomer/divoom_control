#!/usr/bin/env bash
#
# ship_install.sh -- `goh ship`'s install step for divoom-control (.gatesrc GOH_SHIP_INSTALL;
# DV.SHIPINSTALL). goh ran the release kit (scripts/ship_release.sh -> scripts/release.sh, which
# bumps the tap's cask on GitHub) and, with no install step declared, left the previous Divoom.app
# installed: 0.45.2 shipped while /Applications held 0.45.1 and `loopctl verify` reported it.
#
# The release ends at the cask, so the install is the cask's:
#
#   1. refresh  the local clone of the tap (`git pull --ff-only`): release.sh bumped the cask on
#               GitHub, and brew reads the clone, so without this `brew upgrade` sees no new version.
#   2. check    the tap's cask declares the version HEAD's pyproject.toml declares, else stop: an
#               upgrade from a stale cask would "succeed" by installing nothing new.
#   3. upgrade  `brew upgrade --cask ztomer/tap/divoom-control` (install when it is not installed).
#               The cask's `uninstall quit:` stops the running app and its helpers first.
#   4. prove    the installed Divoom.app reports that version, else the ship fails at install.
#   5. launch   the new app, in the background, when nothing of it is running after the upgrade.
#
#   scripts/ship_install.sh
#
# Seams (tests/test_ship_install.py): DIVOOM_BREW names brew, DIVOOM_TAP_DIR the tap clone,
# DIVOOM_APP the installed bundle, DIVOOM_OPEN the launcher. Nothing else is touched.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
GOH="${GOH_DIR:-$HOME/Projects/gates_of_heck}"
# shellcheck source=/dev/null # goh's tui/lib.sh: outside this repo; gates_of_heck lints it
. "$GOH/tui/lib.sh"

CASK="ztomer/tap/divoom-control"
BREW="${DIVOOM_BREW:-brew}"
APP="${DIVOOM_APP:-/Applications/Divoom.app}"
OPEN="${DIVOOM_OPEN:-open}"

V="$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")"
[ -n "$V" ] || die "pyproject.toml declares no version"

TAP_DIR="${DIVOOM_TAP_DIR:-$("$BREW" --repository ztomer/tap)}"
[ -d "$TAP_DIR/.git" ] || die "no tap clone at ${TAP_DIR} -- run: brew tap ztomer/tap"
info "refreshing the tap clone ${TAP_DIR}"
git -C "$TAP_DIR" pull --ff-only --quiet || die "the tap clone did not fast-forward (above) -- nothing installed"

CASK_FILE="$TAP_DIR/Casks/divoom-control.rb"
HAVE_CASK="$(sed -n '/^  version "/{s/^  version "\([^"]*\)".*/\1/p;q;}' "$CASK_FILE" 2>/dev/null || true)"
[ "$HAVE_CASK" = "$V" ] \
  || die "the tap's cask declares '${HAVE_CASK:-nothing}', not ${V}: the release did not bump it -- nothing installed"

if "$BREW" list --cask --versions divoom-control >/dev/null 2>&1; then
  info "brew upgrade --cask ${CASK} (→ ${V})"
  "$BREW" upgrade --cask "$CASK" || die "brew upgrade refused (above)"
else
  info "brew install --cask ${CASK} (${V})"
  "$BREW" install --cask "$CASK" || die "brew install refused (above)"
fi

INSTALLED="$(plutil -extract CFBundleShortVersionString raw -o - "$APP/Contents/Info.plist" 2>/dev/null || true)"
[ "$INSTALLED" = "$V" ] \
  || die "${APP} reports '${INSTALLED:-no version}', not ${V}: the upgrade did not install the release"
ok "installed ${APP} ${V}"

if pgrep -qf "^${APP}/Contents/" 2>/dev/null; then
  ok "Divoom ${V} is running"
else
  info "launching ${APP} in the background"
  "$OPEN" -g "$APP" || die "could not launch ${APP} (above)"
  ok "launched Divoom ${V}"
fi
