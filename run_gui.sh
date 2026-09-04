#!/bin/bash
# run_gui.sh — Launcher for the Divoom Desktop Control Center.
#
# Launch directly so Bluetooth is attributed to the already-granted `python3.14`
# identity (System Settings > Privacy > Bluetooth). The daemon the GUI spawns is
# non-detached, so it inherits this launching context's Bluetooth grant — which
# is why scanning works when you start the app from your (granted) terminal.
#
# Note: the FIRST time, the launching context (your terminal app) must be allowed
# under System Settings > Privacy & Security > Bluetooth. macOS attributes a
# python child's Bluetooth use to the terminal/responsible process. If a device
# scan finds nothing, check that toggle + that the screens are powered on.
#
# (scripts/make_app_bundle.sh builds a Divoom.app for the double-click /
# distribution case, but that creates its OWN Bluetooth identity that must be
# granted separately — prefer launching from a granted terminal for now.)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

echo "[ ==> ] Starting Divoom Desktop Control Center..."
python3 divoom_gui/gui_main.py
echo "[ Ok  ] Divoom Desktop Controller closed."
