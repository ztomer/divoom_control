"""
Divoom device image encoder -- the pure-Python path under the `native` names.

The package is called `native` for a reason that no longer holds: it once
loaded the `libdivoom_compact` dylib for a faster C encoder and fell back
to the Python one when the dylib was absent. The dylib was deleted in L4
(2026-09-25, 9a1cade) -- the daemon encodes in Rust -- so the C branch could
never load and the Python encoder is what has always run. The unreachable
branch (ctypes loader, argtypes, buffer marshalling) is deleted; these
functions are the same Python encoder, reachable under the same names.

The recorded C output is `divoomd/tests/image_vectors.json`, asserted by the
Rust encoder; the Python encoder here reproduces it (see the note beside it).
"""

from __future__ import annotations

from typing import List

from divoom_legacy.utils.divoom_image_encode import (
    encode_animation_frame as _py_encode_animation_frame,
    encode_static_image as _py_encode_static_image,
    encode_animation as _py_encode_animation,
    Frame,
)
from divoom_legacy.utils.divoom_image_encode_32 import (
    encode_animation_frame_32 as _py_encode_animation_frame_32,
    pre_frames as _py_pre_frames_32,
)

# Animation packet chunk size.
ANIMATION_CHUNK_SIZE = 200


def encode_animation_frame(rgb: bytes, w: int, h: int, time_ms: int) -> bytes:
    """Encode one animation frame.

    Returns a `bytes` of length
    `7 + 3*num_colors + ceil(num_pixels * bits_per_pixel / 8)`.

    See `divoom_legacy.utils.divoom_image_encode.encode_animation_frame`
    for the full format spec.
    """
    return _py_encode_animation_frame(rgb, w, h, time_ms)


def encode_static_image(rgb: bytes, w: int, h: int) -> bytes:
    """Encode a static image.

    The 0x44 path is a silent no-op on Timoo firmware (verified 2026-06-05),
    but the byte format is preserved here for other Divoom devices.
    """
    return _py_encode_static_image(rgb, w, h)


def encode_animation(frames: List[Frame]) -> List[bytes]:
    """Encode an animation as a list of 0x49 packet payloads."""
    if not frames:
        return []
    return _py_encode_animation(frames)


def encode_animation_frame_32(rgb: bytes, w: int, h: int, time_ms: int) -> bytes:
    """Encode one 32x32 animation frame."""
    return _py_encode_animation_frame_32(rgb, w, h, time_ms)


def pre_frames_32() -> List[bytes]:
    """Return the two 32x32 pre-frames."""
    return _py_pre_frames_32()


def encode_animation_8b_phases(frames: List[Frame]) -> List[bytes]:
    """Build the 3-phase SPP payloads for an animation via 0x8B.

    Returns the list of args to pass to `send_command("app new send gif cmd",
    args)` in order.
    """
    if not frames:
        return []
    from divoom_legacy.display.animation_8b import build_8b_phases

    return build_8b_phases(frames)
