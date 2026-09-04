"""32×32 PixooMax / extended-LED Divoom device encoder.

APK comparison (R35): the APK uses the **same** AA-format frame encoding
for ALL sizes (16×16, 32×32, 64×64, etc.) via `NDKMain.pixelEncode()`.
The hass-divoom-derived pre-frames (0x05/0x06) and extended palette flag
(RR=0x03, 2-byte color count) are NOT in the APK.

We therefore delegate to the standard `encode_animation` / `encode_animation_frame`
from `divoom_image_encode.py` for 32×32 as well. This file remains as a thin
re-export shim so existing callers (display/__init__.py, animation_8b.py,
native/image_encoder.py) work unchanged.

The APK also has a separate `pixelEncodeBlueHigh()` path (0x25/0x2A header)
for Pixoo Max 32×32+. We do NOT implement this — it's only needed if a
target device rejects the standard format.

See `docs/APK_COMPARISON.md` for full byte-level comparison.
"""
from __future__ import annotations

from typing import List

from .divoom_image_encode import Frame, encode_animation, encode_animation_frame

SCREENSIZE_32 = 32


def pre_frames() -> List[bytes]:
    """Legacy: pre-frames are NOT in the APK protocol. Returns empty list.
    
    Kept for backward compat with callers that import it. The APK's
    `pixelEncode()` does not send pre-frames for any screen size.
    """
    return []


def encode_animation_frame_32(
    rgb_bytes: bytes, w: int, h: int, time_ms: int,
) -> bytes:
    """Encode a single 32×32 animation frame using the standard AA format.

    Delegates to the standard `encode_animation_frame` (RR=0x00, 1-byte NN),
    which matches the APK's `pixelEncode()` output for ALL screen sizes.
    """
    return encode_animation_frame(rgb_bytes, w, h, time_ms)


def encode_animation_32(frames: List[Frame]) -> List[bytes]:
    """Encode a 32×32 animation as 0x49 packet payloads.

    Delegates to the standard `encode_animation` (no pre-frames, standard
    AA format, standard 0x49 packetizer). Returns 0x49 packet payloads
    matching the APK reference.
    """
    return encode_animation(frames)
