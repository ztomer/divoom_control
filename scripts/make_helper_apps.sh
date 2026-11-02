#!/usr/bin/env bash
# make_helper_apps.sh — wrap the app's long-lived helpers in helper app bundles.
#
# D.HELPER (ROADMAP P1.18, 2026-11-02). A helper the app STARTS stays tied to
# the app's LaunchServices record for as long as it lives, and the record is
# keyed by the app's pid: the next AppKit process to draw that pid after the
# app quits is bound to the dead record and exits 1 (D.CFXSBX). Measured on
# this machine with a throwaway applet, every way of starting a helper keeps
# the record alive -- a forked child (it stays in the app's coalition), a
# `launchctl bootstrap`ped job (the record lists it under `loadedJobs`), even
# a job bootstrapped by a trampoline job -- EXCEPT one: an app bundle opened
# through LaunchServices (`open -g -n -a`) is an app of its own, and the
# opener's record goes when the opener quits.
#
# So each helper is the main executable of a bundle under Contents/Helpers,
# and Contents/Frameworks/bin/<name> is a relative symlink to it, so every
# caller that runs the binary by its old path still finds it.
#
#   scripts/make_helper_apps.sh dist/Divoom.app
set -euo pipefail

APP="${1:?usage: make_helper_apps.sh <Divoom.app>}"
BIN="${APP}/Contents/Frameworks/bin"
VERSION="${DIVOOM_HELPER_VERSION:-0}"

# name|bundle id|display name|extra Info.plist keys (python dict literal)
HELPERS=(
  "divoom-menubar|com.divoom.menubar|Divoom Menubar|{'LSUIElement': True}"
  "divoomd|com.divoom.divoomd|divoomd|{'LSBackgroundOnly': True, 'NSBluetoothAlwaysUsageDescription': 'divoomd talks to your Divoom panels over Bluetooth.'}"
)

for spec in "${HELPERS[@]}"; do
  IFS='|' read -r name ident display extra <<<"${spec}"
  exe="${BIN}/${name}"
  if [[ -L "${exe}" ]]; then
    echo "→ ${name}: already a helper app"
    continue
  fi
  [[ -f "${exe}" ]] || { echo "ERROR: ${exe} is missing" >&2; exit 1; }
  bundle="${APP}/Contents/Helpers/${display}.app"
  mkdir -p "${bundle}/Contents/MacOS"
  mv "${exe}" "${bundle}/Contents/MacOS/${name}"
  python3 - "${bundle}/Contents/Info.plist" "${name}" "${ident}" "${display}" "${VERSION}" "${extra}" <<'PY'
import ast, plistlib, sys
path, name, ident, display, version, extra = sys.argv[1:]
plist = {
    "CFBundleExecutable": name,
    "CFBundleIdentifier": ident,
    "CFBundleName": display,
    "CFBundlePackageType": "APPL",
    "CFBundleShortVersionString": version,
    "CFBundleVersion": version,
    "LSMinimumSystemVersion": "13.0",
}
plist.update(ast.literal_eval(extra))
with open(path, "wb") as fh:
    plistlib.dump(plist, fh)
PY
  # Relative, so the link survives the bundle being copied anywhere.
  ln -s "../../Helpers/${display}.app/Contents/MacOS/${name}" "${exe}"
  [[ -x "${exe}" ]] || { echo "ERROR: ${exe} does not resolve" >&2; exit 1; }
  echo "→ ${name}: Contents/Helpers/${display}.app (${ident})"
done
