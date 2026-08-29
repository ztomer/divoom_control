#!/usr/bin/env bash
# build_release.sh — build the self-contained Divoom.app + Divoom-v<version>.dmg
# for the Homebrew cask, via PyInstaller. macOS only.
#
# PyInstaller (not py2app): pywebview's WKWebView renders blank inside a py2app
# bundle (file:// loads are blocked there); PyInstaller is pywebview's supported
# packager and renders correctly. The spec is divoom.spec.
#
# Produces (under dist/):
#   Divoom.app                 — self-contained (Python + deps + Rust daemon/menubar)
#   Divoom-v<version>.dmg       — the cask artifact
#   Divoom-v<version>.dmg.sha256
#
# Usage:
#   python3 -m venv .buildvenv
#   .buildvenv/bin/pip install -e '.[gui]' pyinstaller psutil
#   scripts/build_release.sh [path-to-build-venv-python]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "build_release.sh is macOS-only." >&2
  exit 1
fi

PYBUILD="${1:-${ROOT}/.buildvenv/bin/python}"
if [[ ! -x "${PYBUILD}" ]]; then
  echo "Build venv python not found at ${PYBUILD}." >&2
  echo "Create it:  python3 -m venv .buildvenv && .buildvenv/bin/pip install -e '.[gui]' pyinstaller psutil" >&2
  exit 1
fi
if ! "${PYBUILD}" -c "import PyInstaller" 2>/dev/null; then
  echo "PyInstaller not in the build venv: ${PYBUILD} -m pip install pyinstaller psutil" >&2
  exit 1
fi

VERSION="$(grep -m1 '^version' pyproject.toml | sed -E 's/.*"(.*)".*/\1/')"
export DIVOOM_BUILD_VERSION="${VERSION}"
echo "Building Divoom Control v${VERSION} (PyInstaller)"

# 1. Native C encoder dylib (palette encoder / downsampler / framing).
echo "→ building native dylib"
bash scripts/build_libdivoom.sh

# 1b. Native Rust daemon + menubar — bundled INSIDE the .app (divoom.spec collects
#     them under bin/); the GUI spawns them at runtime.
if ! command -v cargo >/dev/null 2>&1 && [ -x "${HOME}/.cargo/bin/cargo" ]; then
  export PATH="${HOME}/.cargo/bin:${PATH}"
fi
command -v cargo >/dev/null 2>&1 || { echo "ERROR: cargo not found (needed for divoomd/divoom-menubar)." >&2; exit 1; }
# The now-playing helper (MediaRemote host dylib + its perl loader), shipped
# next to the daemon inside the bundle.
echo "→ building now-playing helper"
bash scripts/build_nowplaying_helper.sh >/dev/null

echo "→ building native rust daemon (divoomd)"
( cd divoomd && cargo build --release )
echo "→ building native rust menubar (divoom-menubar)"
cargo build --release -p divoom-menubar

# 2. App icon → packaging/Divoom.icns (regenerate so it always matches source).
echo "→ generating app icon (.icns)"
"$(dirname "$0")/make_icns.sh"

# 3. PyInstaller build → dist/Divoom.app.
echo "→ pyinstaller build"
rm -rf build dist
"${PYBUILD}" -m PyInstaller --noconfirm --distpath dist --workpath build divoom.spec

APP="dist/Divoom.app"
[[ -d "${APP}" ]] || { echo "ERROR: PyInstaller did not produce ${APP}." >&2; exit 1; }

# 2b. Ensure the bundled Rust binaries are executable (PyInstaller datas can drop +x).
for b in divoomd divoom-menubar libnp_helper.dylib np_load.pl; do
  f="${APP}/Contents/Frameworks/bin/${b}"
  if [[ -f "${f}" ]]; then
    chmod +x "${f}"
    echo "→ bundled ${b}: $(ls -lh "${f}" | awk '{print $5}')"
  else
    echo "WARN: ${b} not bundled (expected ${f})." >&2
  fi
done

# 3. Guard: the reverse-engineered APK / references must never be in the bundle.
if find "${APP}" \( -iname '*smali*' -o -path '*references*' -o -iname '*.apk' \) | grep -q .; then
  echo "ERROR: reverse-engineered references leaked into the bundle — aborting." >&2
  exit 1
fi

# 4. Adhoc re-sign the whole bundle (covers the chmod'd binaries + the .app's
#    Info.plist BT usage strings → TCC attributes Bluetooth to com.divoom.control).
echo "→ codesigning (adhoc, deep)"
codesign --force --deep --sign - "${APP}" 2>/dev/null \
  && echo "   signed" || echo "   WARN: codesign failed (unsigned bundle still runs locally)"

# 5. .dmg (plain folder image with an /Applications symlink for drag-install).
DMG="dist/Divoom-v${VERSION}.dmg"
echo "→ packaging ${DMG}"
STAGE="$(mktemp -d)"
cp -R "${APP}" "${STAGE}/"
ln -s /Applications "${STAGE}/Applications"
rm -f "${DMG}"
hdiutil create -volname "Divoom Control" -srcfolder "${STAGE}" -ov -format UDZO "${DMG}" >/dev/null
rm -rf "${STAGE}"

# 6. sha256 for the cask.
shasum -a 256 "${DMG}" | tee "${DMG}.sha256"
echo "Done: ${DMG}"
