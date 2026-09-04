"""Locate the native ``libdivoom_compact`` shared library for this platform.

The library is built by ``scripts/build_libdivoom.sh`` into ``divoom_lib/`` with a
platform-specific extension — ``.dylib`` (macOS), ``.so`` (Linux), ``.dll``
(Windows). Every ctypes loader (`framing`, `media_decoder`, `native.image_encoder`,
`native.downscaler`) imports :func:`library_path` from here so the per-OS naming
lives in one place. All callers already carry a pure-Python fallback, so a
missing or foreign-platform build degrades gracefully (just slower).
"""
from __future__ import annotations

import sys
from pathlib import Path

_LIB_DIR = Path(__file__).parent
_BASENAME = "libdivoom_compact"


def platform_libname() -> str:
    """The expected library filename for the current platform."""
    if sys.platform == "darwin":
        return f"{_BASENAME}.dylib"
    if sys.platform.startswith("win"):
        return f"{_BASENAME}.dll"
    return f"{_BASENAME}.so"  # linux + other unixes


def library_path() -> Path:
    """Path to the native lib for this platform.

    Falls back to any existing build of another extension (so a ``.dylib``
    checked into the repo is still found on macOS, etc.). The returned path is
    not guaranteed to exist — callers check ``.exists()`` and fall back to the
    pure-Python implementation.
    """
    primary = _LIB_DIR / platform_libname()
    if primary.exists():
        return primary
    for ext in (".so", ".dylib", ".dll"):
        cand = _LIB_DIR / f"{_BASENAME}{ext}"
        if cand.exists():
            return cand
    return primary
