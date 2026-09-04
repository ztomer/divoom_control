"""
Divoom device image encoder — native dylib with pure-Python fallback.

The dylib (`divoom_lib/libdivoom_compact.dylib`) implements the palette
encoder in C for ~10-50× faster animation push. The C output is
byte-identical to the pure-Python encoder in
`divoom_lib/utils/divoom_image_encode.py` — `tests/test_native_image_encoder.py`
asserts this for ≥100 random inputs.

If the dylib is missing, fails to load, or returns an error, the wrapper
falls back to the pure-Python encoder. The two paths are kept
completely independent — the Python side has no C-call-specific math.

This is a *library* function: not just for cover art. Future callers:
  - Album art push
  - Custom animations (multi-frame)
  - Live wallpaper rendering
  - Any time we need to push a palette-quantized image to a Divoom device
"""
from __future__ import annotations

import ctypes
import logging
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger("divoom_lib")

# Re-import the Python encoder symbols so the public API matches.
# This way callers can `from divoom_lib.native.image_encoder import encode_animation_frame`
# and get a single function that does the right thing (fast path native,
# fallback Python). The Python encoder is also importable directly for
# parity tests.
from ..utils.divoom_image_encode import (  # noqa: F401
    encode_animation_frame as _py_encode_animation_frame,
    encode_static_image as _py_encode_static_image,
    encode_animation as _py_encode_animation,
    Frame,
)
from ..utils.divoom_image_encode_32 import (  # noqa: F401
    encode_animation_frame_32 as _py_encode_animation_frame_32,
    pre_frames as _py_pre_frames_32,
)

_lib = None
_lib_load_error: str | None = None

# The native lib lives in divoom_lib/ (R17): it bundles native_src/compact.c
# (tile-compacting + framing) with native_src/{downsample,image_encode}.c into
# one shared library. native_lib.library_path() resolves the per-platform name
# (.dylib/.so/.dll).
from divoom_lib.native_lib import library_path
_DYLIB_PATH = library_path()

# Animation packet chunk size (must match C DIVOOM_ANIMATION_CHUNK_SIZE)
ANIMATION_CHUNK_SIZE = 200


def _load_lib():
    """Try to load the native dylib. Returns the ctypes handle or None."""
    global _lib, _lib_load_error
    if _lib is not None:
        return _lib
    if _lib_load_error is not None:
        return None
    if not _DYLIB_PATH.exists():
        _lib_load_error = f"dylib not found at {_DYLIB_PATH}"
        logger.info("image_encoder: %s — using Python fallback", _lib_load_error)
        return None
    try:
        handle = ctypes.CDLL(str(_DYLIB_PATH))
        handle.divoom_encode_animation_frame.argtypes = [
            ctypes.POINTER(ctypes.c_ubyte),  # const uint8_t* rgb
            ctypes.c_int,                    # int w
            ctypes.c_int,                    # int h
            ctypes.c_uint16,                 # uint16_t time_ms
            ctypes.POINTER(ctypes.c_ubyte),  # uint8_t* out
            ctypes.c_int,                    # int out_size
        ]
        handle.divoom_encode_animation_frame.restype = ctypes.c_int
        handle.divoom_encode_animation_packets.argtypes = [
            ctypes.POINTER(ctypes.c_ubyte),  # const uint8_t* frames_blob
            ctypes.c_int,                    # int total_len
            ctypes.POINTER(ctypes.c_ubyte),  # uint8_t* out
            ctypes.c_int,                    # int out_size
        ]
        handle.divoom_encode_animation_packets.restype = ctypes.c_int
        handle.divoom_encode_static_image.argtypes = [
            ctypes.POINTER(ctypes.c_ubyte),  # const uint8_t* rgb
            ctypes.c_int,                    # int w
            ctypes.c_int,                    # int h
            ctypes.POINTER(ctypes.c_ubyte),  # uint8_t* out
            ctypes.c_int,                    # int out_size
        ]
        handle.divoom_encode_static_image.restype = ctypes.c_int
        # Round 4: 32x32 frame encoder (Pixoo Max / Tivoo Max extended LED)
        handle.divoom_encode_animation_frame_32.argtypes = [
            ctypes.POINTER(ctypes.c_ubyte),  # const uint8_t* rgb
            ctypes.c_int,                    # int w
            ctypes.c_int,                    # int h
            ctypes.c_uint16,                 # uint16_t time_ms
            ctypes.POINTER(ctypes.c_ubyte),  # uint8_t* out
            ctypes.c_int,                    # int out_size
        ]
        handle.divoom_encode_animation_frame_32.restype = ctypes.c_int
        # Round 4: 0x8B 3-phase chunker
        handle.divoom_encode_animation_8b.argtypes = [
            ctypes.POINTER(ctypes.c_ubyte),  # const uint8_t* frames_blob
            ctypes.c_int,                    # int total_len
            ctypes.POINTER(ctypes.c_ubyte),  # uint8_t* out
            ctypes.c_int,                    # int out_size
        ]
        handle.divoom_encode_animation_8b.restype = ctypes.c_int
        # Round 4: pre-frames (32x32 only)
        handle.divoom_write_pre_frame_1.argtypes = [
            ctypes.POINTER(ctypes.c_ubyte),  # uint8_t* out
            ctypes.c_int,                    # int out_size
        ]
        handle.divoom_write_pre_frame_1.restype = ctypes.c_int
        handle.divoom_write_pre_frame_2.argtypes = [
            ctypes.POINTER(ctypes.c_ubyte),  # uint8_t* out
            ctypes.c_int,                    # int out_size
        ]
        handle.divoom_write_pre_frame_2.restype = ctypes.c_int
        _lib = handle
        logger.info("image_encoder: loaded %s", _DYLIB_PATH)
        return _lib
    except OSError as e:
        _lib_load_error = f"failed to load {_DYLIB_PATH}: {e}"
        logger.warning("image_encoder: %s — using Python fallback", _lib_load_error)
        return None


def _c_encode_animation_frame(
    rgb: bytes, w: int, h: int, time_ms: int
) -> bytes | None:
    """Call the C encoder. Returns the encoded frame bytes, or None on error."""
    lib = _load_lib()
    if lib is None:
        return None
    in_size = w * h * 3
    # Worst case: 7-byte header + 256*3 palette + 1 byte/pixel (8 bits/pixel, the
    # C's own worst_size bound). The old `(w*h+7)//8` assumed 1 BIT/pixel, so for
    # any image past ~1 pixel the buffer was smaller than the C's conservative
    # worst_size check and the C returned -1 → silent Python fallback (the native
    # encoder was effectively dead for real frames).
    out_size = 7 + 256 * 3 + w * h
    try:
        in_buf = (ctypes.c_ubyte * in_size).from_buffer_copy(rgb)
        out_buf = (ctypes.c_ubyte * out_size)()
        rc = lib.divoom_encode_animation_frame(
            in_buf, w, h, ctypes.c_uint16(time_ms), out_buf, out_size
        )
        if rc < 0:
            return None
        return bytes(out_buf[:rc])
    except Exception as e:
        logger.warning("image_encoder: native call failed (%s) — using Python fallback", e)
        return None


def _c_encode_animation_packets(frames_blob: bytes) -> bytes | None:
    """Call the C packetizer. Returns concatenated packets, or None on error."""
    lib = _load_lib()
    if lib is None:
        return None
    total_len = len(frames_blob)
    n_packets = (total_len + ANIMATION_CHUNK_SIZE - 1) // ANIMATION_CHUNK_SIZE
    out_size = n_packets * (3 + ANIMATION_CHUNK_SIZE)
    try:
        in_buf = (ctypes.c_ubyte * total_len).from_buffer_copy(frames_blob)
        out_buf = (ctypes.c_ubyte * out_size)()
        rc = lib.divoom_encode_animation_packets(
            in_buf, total_len, out_buf, out_size
        )
        if rc < 0:
            return None
        # Each packet is 3 + chunk_size. The C writes them back-to-back
        # with each packet at most 3 + 200 bytes. The actual total bytes
        # written = sum(3 + chunk_size_i) = 3*n_packets + total_len.
        actual_size = 3 * n_packets + total_len
        return bytes(out_buf[:actual_size])
    except Exception as e:
        logger.warning("image_encoder: native call failed (%s) — using Python fallback", e)
        return None


def _c_encode_static_image(rgb: bytes, w: int, h: int) -> bytes | None:
    """Call the C static encoder. Returns encoded bytes, or None on error."""
    lib = _load_lib()
    if lib is None:
        return None
    in_size = w * h * 3
    # Worst case: 7-byte header + 256*3 palette + 1 byte/pixel (matches the C's
    # worst_size bound). The old `(w*h+7)//8` (1 bit/pixel) under-allocated for any
    # multi-pixel image, so the C returned -1 → silent Python fallback.
    out_size = 7 + 256 * 3 + w * h
    try:
        in_buf = (ctypes.c_ubyte * in_size).from_buffer_copy(rgb)
        out_buf = (ctypes.c_ubyte * out_size)()
        rc = lib.divoom_encode_static_image(
            in_buf, w, h, out_buf, out_size
        )
        if rc < 0:
            return None
        return bytes(out_buf[:rc])
    except Exception as e:
        logger.warning("image_encoder: native call failed (%s) — using Python fallback", e)
        return None


def encode_animation_frame(
    rgb: bytes, w: int, h: int, time_ms: int
) -> bytes:
    """Encode one animation frame. Uses the C dylib if available, else Python.

    Byte-identical to the pure-Python encoder (the dylib is built to
    match the Python byte-for-byte). Returns a `bytes` of length
    `7 + 3*num_colors + ceil(num_pixels * bits_per_pixel / 8)`.

    See `divoom_lib.utils.divoom_image_encode.encode_animation_frame`
    for the full format spec.
    """
    result = _c_encode_animation_frame(rgb, w, h, time_ms)
    if result is not None:
        return result
    return _py_encode_animation_frame(rgb, w, h, time_ms)


def encode_static_image(rgb: bytes, w: int, h: int) -> bytes:
    """Encode a static image. Uses the C dylib if available, else Python.

    Byte-identical to the pure-Python encoder. The 0x44 path is
    a silent no-op on Timoo firmware (verified 2026-06-05), but
    the byte format is preserved here for other Divoom devices.
    """
    result = _c_encode_static_image(rgb, w, h)
    if result is not None:
        return result
    return _py_encode_static_image(rgb, w, h)


def encode_animation(frames: List[Frame]) -> List[bytes]:
    """Encode an animation as a list of 0x49 packet payloads.

    Uses the C dylib (for both frame encoding AND packetization) if
    available, else falls back to the pure-Python encoder. Output is
    byte-identical between the two paths.
    """
    if not frames:
        return []
    lib = _load_lib()
    if lib is not None:
        # Try the C path: encode each frame, concatenate, packetize.
        encoded_frames = []
        for (rgb, w, h, t) in frames:
            frame_bytes = _c_encode_animation_frame(rgb, w, h, t)
            if frame_bytes is None:
                # Fall back to Python for this frame, then bail to
                # the all-Python path for consistency.
                return _py_encode_animation(frames)
            encoded_frames.append(frame_bytes)
        blob = b"".join(encoded_frames)
        packed = _c_encode_animation_packets(blob)
        if packed is not None:
            # Split the packed blob back into individual packets.
            # Each packet is 3 (header: LE u16 + u8) + chunk_size bytes,
            # with chunks up to ANIMATION_CHUNK_SIZE bytes.
            n_packets = (len(blob) + ANIMATION_CHUNK_SIZE - 1) // ANIMATION_CHUNK_SIZE
            packets = []
            offset = 0
            for i in range(n_packets):
                chunk_size = min(ANIMATION_CHUNK_SIZE, len(blob) - i * ANIMATION_CHUNK_SIZE)
                packet_size = 3 + chunk_size
                packets.append(packed[offset : offset + packet_size])
                offset += packet_size
            return packets
    return _py_encode_animation(frames)


# ── Round 4: 32x32 encoder + 0x8B 3-phase ─────────────────────────────


def _c_encode_animation_frame_32(
    rgb: bytes, w: int, h: int, time_ms: int
) -> bytes | None:
    """Call the C 32x32 frame encoder. Returns encoded bytes, or None on error."""
    lib = _load_lib()
    if lib is None:
        return None
    if w != 32 or h != 32:
        return None
    in_size = w * h * 3
    # Worst case: 8-byte header + 256*3 palette + 1024 pixel bytes (8bpp).
    out_size = 8 + 256 * 3 + w * h
    try:
        in_buf = (ctypes.c_ubyte * in_size).from_buffer_copy(rgb)
        out_buf = (ctypes.c_ubyte * out_size)()
        rc = lib.divoom_encode_animation_frame_32(
            in_buf, w, h, ctypes.c_uint16(time_ms), out_buf, out_size
        )
        if rc < 0:
            return None
        return bytes(out_buf[:rc])
    except Exception as e:
        logger.warning(
            "image_encoder: native 32x32 call failed (%s) — using Python fallback", e
        )
        return None


def _c_write_pre_frame_1() -> bytes | None:
    """Write the 32x32 pre-frame 1 (5-byte body). Returns None on error."""
    lib = _load_lib()
    if lib is None:
        return None
    out_size = 8
    try:
        out_buf = (ctypes.c_ubyte * out_size)()
        rc = lib.divoom_write_pre_frame_1(out_buf, out_size)
        if rc < 0:
            return None
        return bytes(out_buf[:rc])
    except Exception as e:
        logger.warning("image_encoder: native pre_frame_1 failed (%s)", e)
        return None


def _c_write_pre_frame_2() -> bytes | None:
    """Write the 32x32 pre-frame 2 (6-byte body). Returns None on error."""
    lib = _load_lib()
    if lib is None:
        return None
    out_size = 9
    try:
        out_buf = (ctypes.c_ubyte * out_size)()
        rc = lib.divoom_write_pre_frame_2(out_buf, out_size)
        if rc < 0:
            return None
        return bytes(out_buf[:rc])
    except Exception as e:
        logger.warning("image_encoder: native pre_frame_2 failed (%s)", e)
        return None


def _c_encode_animation_8b(frames_blob: bytes) -> bytes | None:
    """Call the C 0x8B 3-phase chunker. Returns concatenated phases, or None on error."""
    lib = _load_lib()
    if lib is None:
        return None
    total_len = len(frames_blob)
    if total_len <= 0:
        return None
    n_chunks = (total_len + 255) // 256
    out_size = 5 + n_chunks * (7 + 256) + 1
    try:
        in_buf = (ctypes.c_ubyte * total_len).from_buffer_copy(frames_blob)
        out_buf = (ctypes.c_ubyte * out_size)()
        rc = lib.divoom_encode_animation_8b(
            in_buf, total_len, out_buf, out_size
        )
        if rc < 0:
            return None
        return bytes(out_buf[:rc])
    except Exception as e:
        logger.warning(
            "image_encoder: native 0x8B call failed (%s) — using Python fallback", e
        )
        return None


def encode_animation_frame_32(
    rgb: bytes, w: int, h: int, time_ms: int
) -> bytes:
    """Encode one 32x32 animation frame. C fast path, Python fallback."""
    result = _c_encode_animation_frame_32(rgb, w, h, time_ms)
    if result is not None:
        return result
    return _py_encode_animation_frame_32(rgb, w, h, time_ms)


def pre_frames_32() -> List[bytes]:
    """Return the two 32x32 pre-frames. C fast path, Python fallback."""
    p1 = _c_write_pre_frame_1()
    if p1 is None:
        return _py_pre_frames_32()
    p2 = _c_write_pre_frame_2()
    if p2 is None:
        return _py_pre_frames_32()
    return [p1, p2]


def encode_animation_8b_phases(frames: List[Frame]) -> List[bytes]:
    """Build the 3-phase SPP payloads for an animation via 0x8B.

    C fast path, Python fallback. Returns the list of args to pass
    to `send_command("app new send gif cmd", args)` in order.
    """
    if not frames:
        return []
    encoded: list[bytes] = []
    for (rgb, w, h, t) in frames:
        if w == 32 and h == 32:
            fb = _c_encode_animation_frame_32(rgb, w, h, t)
            if fb is None:
                fb = _py_encode_animation_frame_32(rgb, w, h, t)
        else:
            fb = _c_encode_animation_frame(rgb, w, h, t)
            if fb is None:
                fb = _py_encode_animation_frame(rgb, w, h, t)
        encoded.append(fb)
    blob = b"".join(encoded)
    packed = _c_encode_animation_8b(blob)
    if packed is None:
        from ..display.animation_8b import build_8b_phases
        return build_8b_phases(frames)
    total_len = len(blob)
    n_chunks = (total_len + 255) // 256
    phases: List[bytes] = []
    offset = 0
    phases.append(packed[0:5])
    offset = 5
    for i in range(n_chunks):
        chunk_size = min(256, total_len - i * 256)
        phases.append(packed[offset : offset + 7 + chunk_size])
        offset += 7 + chunk_size
    phases.append(packed[offset : offset + 1])
    return phases


def is_native_available() -> bool:
    """True if the C dylib is loaded and encoder calls will go to native code."""
    return _load_lib() is not None


def reset_for_tests() -> None:
    """Forget the cached dylib handle. Used by tests to simulate a fresh load."""
    global _lib, _lib_load_error
    _lib = None
    _lib_load_error = None
