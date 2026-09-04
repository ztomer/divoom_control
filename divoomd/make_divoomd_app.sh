#!/usr/bin/env bash
# make_divoomd_app.sh — wrap the divoomd binary in a signed .app for the
# CoreBluetooth TCC grant (com.divoom.divoomd).
#
# GRANT-ONCE design: the .app is a STABLE THIN LAUNCHER (like the Python dev
# daemon). Its bundle executable is a fixed `run` script that exec's the
# freshly-built binary from target/release. Because the bundle never changes
# between `cargo build`s, its code signature is stable and the Bluetooth grant
# PERSISTS — you grant once. (Copying the changing binary INTO the bundle, as
# before, gave a new code hash each build, so macOS re-prompted every time.)
#
# Run this ONCE to create + sign the bundle (grant Bluetooth on first launch).
# Afterwards just rebuild + relaunch — do NOT re-run this unless the launcher
# itself must change:
#   cargo build --release
#   open "dist/Divoom Daemon (rs).app"     # no re-prompt
#
# Toggle BLE frame logging WITHOUT changing the bundle (so the grant survives):
#   echo 'export DIVOOMD_BLE_DEBUG=1' > /tmp/divoomd.env     # on
#   rm -f /tmp/divoomd.env                                   # off
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="${HERE}/target/release/divoomd"
APP="${HERE}/dist/Divoom Daemon (rs).app"
SOCK="${DIVOOMD_SOCKET:-/tmp/divoomd.sock}"

if [[ ! -x "${BIN}" ]]; then
  echo "build first:  cargo build --release   (missing ${BIN})" >&2
  exit 1
fi

rm -rf "${APP}"
mkdir -p "${APP}/Contents/MacOS"
cp "${HERE}/Info.plist" "${APP}/Contents/Info.plist"

# Stable launcher: exec the (changing) build output by absolute path. This script
# is byte-identical across rebuilds, so the bundle's code signature is stable.
cat > "${APP}/Contents/MacOS/run" <<RUN
#!/usr/bin/env bash
# optional dev overrides (e.g. DIVOOMD_BLE_DEBUG) — external so the bundle is stable
[ -f /tmp/divoomd.env ] && source /tmp/divoomd.env
exec "${BIN}" --socket "${SOCK}" >> /tmp/divoomd.log 2>&1
RUN
chmod +x "${APP}/Contents/MacOS/run"

codesign --force --sign - --identifier com.divoom.divoomd "${APP}" 2>/dev/null \
  && echo "signed (ad-hoc): ${APP}" \
  || echo "WARN: codesign failed"

echo "built: ${APP}   (execs ${BIN})"
echo "run once:  open \"${APP}\"   (grant Bluetooth) — then just rebuild + relaunch, no re-prompt"
echo "socket: ${SOCK}   logs: /tmp/divoomd.log"
