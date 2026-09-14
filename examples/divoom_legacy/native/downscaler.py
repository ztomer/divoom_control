"""
LANCZOS3 image downscaler — native dylib with PIL fallback.

The dylib (`divoom_lib/libdivoom_compact.dylib`) implements the full PIL-equivalent
pipeline in C:
    - For RGB:    per-channel LANCZOS3 resample
    - For RGBA:   convert('RGBa')  →  resize()  →  convert('RGBA')
                  (pre-multiply → resample → un-premultiply, all in C)

If the dylib is missing, fails to load, or returns an error, the wrapper
falls back to a single call to PIL.Image.resize, which produces the same
output. The two paths are kept completely independent — the Python side
has no RGBA pre/un-premult math of its own.

This is a *library* function: not just for cover art. Future callers:
  - Google Photos album thumbnails
  - Live wallpaper rendering
  - Animation frame rescaling
  - Any time we need a fast, deterministic downscale to a Divoom buffer
"""
from __future__ import annotations

import ctypes
import logging
from pathlib import Path

from PIL import Image

logger = logging.getLogger("divoom_lib")

CHANNELS_RGB = 3
CHANNELS_RGBA = 4

_lib = None
_lib_load_error: str | None = None

# The dylib lives in divoom_lib/ (R17): it bundles native_src/compact.c with
# native_src/downsample.c (LANCZOS3) into one shared library.
# native_lib.library_path() resolves the per-platform name (.dylib/.so/.dll).
from divoom_lib.native_lib import library_path
_DYLIB_PATH = library_path()


def _load_lib():
    """Try to load the native dylib. Returns the ctypes handle or None."""
    global _lib, _lib_load_error
    if _lib is not None:
        return _lib
    if _lib_load_error is not None:
        return None
    if not _DYLIB_PATH.exists():
        _lib_load_error = f"dylib not found at {_DYLIB_PATH}"
        logger.info("downscaler: %s — using PIL fallback", _lib_load_error)
        return None
    try:
        handle = ctypes.CDLL(str(_DYLIB_PATH))
        handle.downsample_lanczos3.argtypes = [
            ctypes.POINTER(ctypes.c_ubyte),  # const uint8_t* in
            ctypes.c_int,                    # int in_w
            ctypes.c_int,                    # int in_h
            ctypes.POINTER(ctypes.c_ubyte),  # uint8_t* out
            ctypes.c_int,                    # int out_w
            ctypes.c_int,                    # int out_h
            ctypes.c_int,                    # int channels
        ]
        handle.downsample_lanczos3.restype = ctypes.c_int
        _lib = handle
        logger.info("downscaler: loaded %s", _DYLIB_PATH)
        return _lib
    except OSError as e:
        _lib_load_error = f"failed to load {_DYLIB_PATH}: {e}"
        logger.warning("downscaler: %s — using PIL fallback", _lib_load_error)
        return None


def _pil_downsample(
    in_bytes: bytes, in_w: int, in_h: int, out_w: int, out_h: int, channels: int
) -> bytes:
    """Reference LANCZOS3 downscale via PIL. Kept completely separate from
    the C path so each can be reasoned about and tested in isolation."""
    mode = "RGB" if channels == CHANNELS_RGB else "RGBA"
    img = Image.frombytes(mode, (in_w, in_h), in_bytes)
    out = img.resize((out_w, out_h), Image.Resampling.LANCZOS)
    return out.tobytes()


def downsample_lanczos(
    in_bytes: bytes, in_w: int, in_h: int, out_w: int, out_h: int, channels: int = CHANNELS_RGB
) -> bytes:
    """LANCZOS3 downscale, byte-identical to PIL.Image.resize(..., LANCZOS).

    Args:
        in_bytes:  Source image bytes (RGB or RGBA, row-major).
        in_w, in_h: Source dimensions.
        out_w, out_h: Target dimensions.
        channels:   3 for RGB, 4 for RGBA.

    Returns:
        New byte buffer of size out_w * out_h * channels.

    Raises:
        ValueError: For invalid channels or dimensions, or input size mismatch.
    """
    if channels not in (CHANNELS_RGB, CHANNELS_RGBA):
        raise ValueError(f"channels must be {CHANNELS_RGB} or {CHANNELS_RGBA}, got {channels}")
    if in_w <= 0 or in_h <= 0 or out_w <= 0 or out_h <= 0:
        raise ValueError(
            f"dimensions must be positive, got in=({in_w},{in_h}) out=({out_w},{out_h})"
        )
    expected_in = in_w * in_h * channels
    if len(in_bytes) != expected_in:
        raise ValueError(
            f"in_bytes length {len(in_bytes)} != in_w*in_h*channels = {expected_in}"
        )

    lib = _load_lib()
    if lib is not None:
        try:
            in_buf = (ctypes.c_ubyte * len(in_bytes)).from_buffer_copy(in_bytes)
            out_size = out_w * out_h * channels
            out_buf = (ctypes.c_ubyte * out_size)()
            rc = lib.downsample_lanczos3(
                in_buf, in_w, in_h, out_buf, out_w, out_h, channels
            )
            if rc != 0:
                raise OSError(f"downsample_lanczos3 returned rc={rc}")
            return bytes(out_buf)
        except Exception as e:
            logger.warning(
                "downscaler: native call failed (%s) — using PIL fallback", e
            )

    return _pil_downsample(in_bytes, in_w, in_h, out_w, out_h, channels)


def is_native_available() -> bool:
    """True if the C dylib is loaded and the downsample call will go to native code."""
    return _load_lib() is not None


def reset_for_tests() -> None:
    """Forget the cached dylib handle. Used by tests to simulate a fresh load."""
    global _lib, _lib_load_error
    _lib = None
    _lib_load_error = None
