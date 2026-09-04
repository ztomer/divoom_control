"""R20 — the native-lib path resolver picks the right per-platform filename and
keeps every ctypes loader pointing at one place (Linux compatibility)."""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from divoom_lib import native_lib


def test_platform_libname_matches_os(monkeypatch):
    monkeypatch.setattr(native_lib.sys, "platform", "darwin")
    assert native_lib.platform_libname() == "libdivoom_compact.dylib"
    monkeypatch.setattr(native_lib.sys, "platform", "linux")
    assert native_lib.platform_libname() == "libdivoom_compact.so"
    monkeypatch.setattr(native_lib.sys, "platform", "win32")
    assert native_lib.platform_libname() == "libdivoom_compact.dll"


def test_library_path_lives_in_divoom_lib():
    p = native_lib.library_path()
    assert p.parent.name == "divoom_lib"
    assert p.name.startswith("libdivoom_compact")


def test_all_loaders_share_the_resolver():
    """framing / media_decoder / native encoders must resolve through the same
    helper so the per-OS name lives in exactly one place."""
    from divoom_lib import framing, media_decoder
    from divoom_lib.native import image_encoder, downscaler
    expected = native_lib.library_path()
    # framing/media_decoder load at import; the native encoders cache _DYLIB_PATH.
    assert image_encoder._DYLIB_PATH == expected
    assert downscaler._DYLIB_PATH == expected
