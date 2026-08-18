"""py2app build recipe → a self-contained ``Divoom.app``.

    python setup_app.py py2app          # build dist/Divoom.app
    (driven by scripts/build_release.sh in a dedicated build venv)

What ships: the four runtime packages (divoom_lib / divoom_daemon / divoom_gui /
divoom_gui) and their package data (web_ui/, fonts/, the native dylib), plus
the third-party runtime deps (bleak, aiohttp, Pillow, pywebview, pyobjc).

What does NOT ship — enforced by `excludes` + listing only the runtime packages:
references/ (the decompiled APK + third-party reference projects), tests/,
scripts/, examples/, docs/. The app must never bundle the reverse-engineered APK.

The Info.plist declares the Bluetooth usage descriptions so the bundle is its own
TCC "responsible process" and macOS shows the normal Allow-Bluetooth prompt
(instead of crashing on first CoreBluetooth touch). See scripts/make_app_bundle.sh
for the background.
"""
import os
import tomllib
from pathlib import Path

from setuptools import setup


def _version() -> str:
    """Single source of truth for the app version, so the bundle's CFBundleVersion
    can never drift from the package version (it did — the first v0.16.0 dmg
    shipped an app stamped 0.15.2 because this was hardcoded).

    Order: an explicit build override (DIVOOM_BUILD_VERSION, set by
    scripts/build_release.sh), else pyproject.toml located by walking UP from this
    file's resolved dir — robust to py2app running us with a relative __file__ or
    from a temp cwd (the un-resolved Path(__file__).parent broke the build)."""
    env = os.environ.get("DIVOOM_BUILD_VERSION")
    if env:
        return env
    here = Path(__file__).resolve().parent
    for d in (here, *here.parents):
        pp = d / "pyproject.toml"
        if pp.is_file():
            with pp.open("rb") as f:
                return tomllib.load(f)["project"]["version"]
    raise RuntimeError("setup_app.py: could not locate pyproject.toml to read the version")


VERSION = _version()
BT_DESC = ("Divoom Control uses Bluetooth to discover and control your Divoom "
           "pixel display.")
AE_DESC = ("Divoom Control reads the now-playing track from Music and Spotify to "
           "show album art on your screen.")

APP = ["divoom_gui/gui_main.py"]

# Ship the native Rust daemon + its encoder dylib at the bundle's Resources root
# (Contents/Resources/) so the app runs `divoomd` instead of the Python fallback.
# daemon_client.spawn_daemon finds them via RESOURCEPATH and points
# DIVOOMD_ENCODER_LIB at the bundled dylib. Skipped if divoomd isn't built (the
# Python daemon then ships as the fallback). build_release.sh builds divoomd first.
_RES_FILES = [
    p for p in (
        "target/release/divoomd",
        # The native Rust menubar agent — the GUI spawns it (see gui_main
        # _resolve_menubar_binary, which finds it via RESOURCEPATH). Replaces the
        "target/release/divoom-menubar",
        "divoom_lib/libdivoom_compact.dylib",
    ) if os.path.exists(p)
]
DATA_FILES = [("", _RES_FILES)] if _RES_FILES else []

_ICON = str(Path(__file__).resolve().parent / "packaging" / "Divoom.icns")

OPTIONS = {
    "argv_emulation": False,
    # App icon (py2app sets CFBundleIconFile from this). PyInstaller is the
    # shipping packager (divoom.spec), but keep parity in case this path revives.
    **({"iconfile": _ICON} if os.path.exists(_ICON) else {}),
    # Listing the runtime packages as `packages` copies each as a real directory
    # tree (not byte-compiled into the zip), so web_ui/, fonts/ and the native
    # dylib travel with their package and resolve via Path(__file__).parent.
    "packages": [
        "divoom_lib", "divoom_daemon", "divoom_gui",
        "bleak", "aiohttp", "PIL", "webview",
        "objc", "Foundation", "AppKit", "CoreBluetooth", "WebKit", "Quartz",
    ],
    "includes": ["divoom_lib.cli"],   # spawned via -m, so pull it in explicitly
    # Belt-and-suspenders: never let the reverse-engineered APK / dev trees in.
    "excludes": [
        "references", "tests", "scripts", "examples", "docs",
        "pytest", "_pytest", "py2app",
    ],
    "plist": {
        "CFBundleName": "Divoom",
        "CFBundleDisplayName": "Divoom Control",
        "CFBundleIdentifier": "com.divoom.control",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "LSUIElement": False,
        "NSBluetoothAlwaysUsageDescription": BT_DESC,
        "NSBluetoothPeripheralUsageDescription": BT_DESC,
        "NSAppleEventsUsageDescription": AE_DESC,
    },
}

setup(
    name="Divoom",
    app=APP,
    version=VERSION,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
