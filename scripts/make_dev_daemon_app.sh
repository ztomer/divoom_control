#!/usr/bin/env bash
# make_dev_daemon_app.sh — build a minimal .app that runs the divoomd daemon with
# a Bluetooth usage description, so it can be `open`ed (LaunchServices re-parents
# the TCC responsible process to the bundle) and granted BLE once, then reused.
#
# Why: macOS attributes Bluetooth TCC by *responsible process*. A daemon launched
# from an un-granted shell is attributed to that shell and HARD-CRASHES on first
# CoreBluetooth touch (no NSBluetoothAlwaysUsageDescription). Wrapping it in a
# .app launched via `open` makes the .app the responsible process; its Info.plist
# supplies the usage string, so the first BT touch PROMPTS instead of crashing,
# and the grant (bundle id com.divoom.devdaemon) persists.
#
# R67: this script used to exec `python -m divoom_lib.cli daemon`. That
# subcommand was archived in R66 and now only prints an error and returns 1, so
# the bundle it produced could not run AT ALL — and nothing noticed for 12 days,
# because no gate exercises scripts/. It now execs the Rust daemon, and --verify
# (default) PROVES the built bundle answers `ping` before reporting success. A
# build that yields a non-running app must fail loudly, not quietly.
#
# Usage:
#   scripts/make_dev_daemon_app.sh              # build + verify into dist/
#   scripts/make_dev_daemon_app.sh --no-verify  # build only (no launch)
#   open "dist/Divoom Dev Daemon.app"           # launch granted daemon
#                                               # (click Allow on the BT prompt once)
# The daemon listens on /tmp/divoom.sock (the default) — drive it with
# scripts/hw_e2e.py, scripts/hw_smoke.py, or any DaemonClient.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
. "${GOH_DIR:-$HOME/Projects/gates_of_heck}/tui/lib.sh"

VERIFY=1
[[ "${1:-}" == "--no-verify" ]] && VERIFY=0

APP="$REPO/dist/Divoom Dev Daemon.app"
SOCK="${DIVOOM_DEV_SOCKET:-/tmp/divoom.sock}"
TRACE_LOG="${DIVOOM_TRACE_LOG:-/tmp/divoom_dev_daemon.log}"
DAEMON="$REPO/target/release/divoomd"

[[ "$(uname -s)" == "Darwin" ]] || die "macOS-only (the .app bundle is a macOS TCC artifact)"
[[ -x "$DAEMON" ]] || die "daemon not built: $DAEMON — run ./build.sh first"

section "Divoom Dev Daemon.app"
info "daemon: $DAEMON"
info "socket: $SOCK"
info "trace:  $TRACE_LOG (DIVOOMD_BLE_DEBUG=1)"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Divoom Dev Daemon</string>
  <key>CFBundleDisplayName</key><string>Divoom Dev Daemon</string>
  <key>CFBundleIdentifier</key><string>com.divoom.devdaemon</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>run</string>
  <key>LSUIElement</key><true/>
  <key>NSBluetoothAlwaysUsageDescription</key>
  <string>Divoom Dev Daemon uses Bluetooth to test connecting to and controlling Divoom pixel displays.</string>
  <key>NSAppleEventsUsageDescription</key>
  <string>Divoom Dev Daemon reads the now-playing track from your music players to show album art on the device.</string>
</dict>
</plist>
PLIST

# The daemon binary is rebuilt by ./build.sh; this wrapper always execs whatever
# is at that path, so a rebuild is picked up on the next launch (no re-bundle).
# BLE_DEBUG is ON in the dev bundle by design: it emits the `[ble] tx cmd=0x..`
# wire trace that scripts/hw_e2e.py asserts against. Without it the hardware
# scenarios can only check that an RPC returned success — which it does even
# when the payload is wrong (the exact R67 ambient defect), so the harness would
# be blind to the thing it exists to catch.
cat > "$APP/Contents/MacOS/run" <<RUN
#!/bin/bash
cd "$REPO"
export DIVOOMD_BLE_DEBUG=1
exec "$DAEMON" --socket "$SOCK" >> "$TRACE_LOG" 2>&1
RUN
chmod +x "$APP/Contents/MacOS/run"

/usr/bin/plutil -lint "$APP/Contents/Info.plist" >/dev/null || die "Info.plist is malformed"

# Register with LaunchServices so `open` finds it by bundle id.
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP" 2>/dev/null || true

ok "built: $APP"

if [[ "$VERIFY" == "0" ]]; then
  warn "skipped launch verification (--no-verify) — the bundle is UNPROVEN"
  exit 0
fi

# ── Verify the bundle actually RUNS ───────────────────────────────────────
# The whole point of this script is a launchable daemon. Building a bundle that
# cannot run is the failure mode this verification exists to catch, so a build
# that cannot be proven to answer `ping` exits non-zero.
if [[ -S "$SOCK" ]] && python3 "$REPO/scripts/daemon_ping.py" --socket "$SOCK" >/dev/null 2>&1; then
  warn "a daemon already owns $SOCK — cannot verify this bundle without evicting it"
  info "stop that daemon and re-run to verify this bundle"
  exit 0
fi

info "launching to verify..."
open "$APP"
if python3 "$REPO/scripts/daemon_ping.py" --socket "$SOCK" --wait 15; then
  ok "verified: the bundle launched and answered ping"
  info "trace log: $TRACE_LOG"
else
  err "the built bundle did NOT answer ping within 15s"
  info "last 20 log lines:"
  tail -20 "$TRACE_LOG" 2>/dev/null || true
  die "build produced a non-running app"
fi
