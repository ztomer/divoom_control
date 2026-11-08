"""
divoom_legacy.native -- the image encoder and downscaler, in pure Python.

The name is historical. These modules wrapped `libdivoom_compact.dylib` (a C
library: tile compacting, a LANCZOS3 downscaler, a palette encoder) and fell back
to Python when it was absent. The C sources, the dylib and
`scripts/build_libdivoom.sh` were deleted in L4 (2026-09-25, 9a1cade) -- the
daemon encodes in Rust -- so the fallback is all that has run since, and the
unreachable native branches are now deleted from the wrappers too.

Public API
----------
- `downsample_lanczos(in_bytes, in_w, in_h, out_w, out_h, channels)` --
  LANCZOS3 downscale, identical to `PIL.Image.resize((out_w, out_h),
  Image.LANCZOS)`.
- `encode_animation_frame(rgb, w, h, time_ms)` -- single-frame 0x49 body.
- `encode_static_image(rgb, w, h)` -- single-image 0x44 body.
- `encode_animation(frames)` -- list of 0x49 packet payloads.
- `CHANNELS_RGB` / `CHANNELS_RGBA` -- channel count constants.
"""

from divoom_legacy.native.downscaler import (
    CHANNELS_RGB,
    CHANNELS_RGBA,
    downsample_lanczos,
)
from divoom_legacy.native.image_encoder import (
    encode_animation_frame,
    encode_animation,
    encode_static_image,
)

__all__ = [
    "CHANNELS_RGB",
    "CHANNELS_RGBA",
    "downsample_lanczos",
    "encode_animation_frame",
    "encode_animation",
    "encode_static_image",
]
