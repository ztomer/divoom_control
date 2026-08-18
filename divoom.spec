# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Divoom Control (macOS .app).

pywebview's py2app bundle showed a blank WKWebView (file:// loads are blocked in
that context); PyInstaller is pywebview's officially-supported packager and renders
correctly. This builds a windowed onedir .app bundling the Python GUI + deps +
web_ui, the native encoder dylib, and the Rust daemon + menubar binaries.

    .buildvenv/bin/pyinstaller --noconfirm divoom.spec   # -> dist/Divoom.app
"""
import os
import tomllib
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.getcwd())


def _ex(p):
    return os.path.join(ROOT, p)


def _version():
    env = os.environ.get("DIVOOM_BUILD_VERSION")
    if env:
        return env
    with open(_ex("pyproject.toml"), "rb") as f:
        return tomllib.load(f)["project"]["version"]


VERSION = _version()
BT_DESC = "Divoom Control uses Bluetooth to discover and control your Divoom pixel display."
AE_DESC = "Divoom Control reads the now-playing track from Music and Spotify to show album art."

# --- data files -------------------------------------------------------------
datas = []
datas += collect_data_files("divoom_gui")          # web_ui/** (frontend)
datas += collect_data_files("divoom_lib")          # fonts/*.bin + the native dylib
datas += collect_data_files("divoom_daemon")       # any packaged data
# Rust binaries the GUI spawns — bundled under bin/ (resolved via sys._MEIPASS).
for _src in ("target/release/divoomd",
             "target/release/divoom-menubar"):
    if os.path.exists(_ex(_src)):
        datas += [(_ex(_src), "bin")]

# --- hidden imports ---------------------------------------------------------
hiddenimports = [
    "divoom_lib.cli",                      # spawned via -m
    "objc", "Foundation", "AppKit", "WebKit", "CoreBluetooth", "Quartz",
    "psutil",                             # system-stats widget
]
hiddenimports += collect_submodules("bleak")
hiddenimports += collect_submodules("aiohttp")
hiddenimports += collect_submodules("webview")
# Cloud-container gallery decode (media_decoder) needs these; they are
# imported lazily inside functions, so force-collect to guarantee the
# DMG bundles them (a clean install with no system Crypto would
# otherwise render ZERO cloud gallery items). R64.
hiddenimports += collect_submodules("Crypto")
hiddenimports += collect_submodules("lzallright")

a = Analysis(
    ["divoom_gui/gui_main.py"],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["references", "tests", "scripts", "examples", "docs",
              "py2app", "pytest", "_pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="Divoom", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Divoom")

# App icon: PyInstaller copies this into Contents/Resources/ and sets
# CFBundleIconFile automatically. Regenerate from source via scripts/make_icns.sh.
_ICON = _ex("packaging/Divoom.icns")

app = BUNDLE(
    coll,
    name="Divoom.app",
    icon=_ICON if os.path.exists(_ICON) else None,
    bundle_identifier="com.divoom.control",
    version=VERSION,
    info_plist={
        "CFBundleName": "Divoom",
        "CFBundleDisplayName": "Divoom Control",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "LSUIElement": False,
        "NSBluetoothAlwaysUsageDescription": BT_DESC,
        "NSBluetoothPeripheralUsageDescription": BT_DESC,
        "NSAppleEventsUsageDescription": AE_DESC,
    },
)
