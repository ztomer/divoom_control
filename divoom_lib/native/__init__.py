"""
divoom_lib.native — performance-sensitive native code exposed to Python.

The three C sources that make up libdivoom_compact.dylib:

  - `divoom_lib/native_src/compact.c`              — tile-compacting and protocol-framing
                                   (encode_basic_payload, encode_ios_le_payload,
                                    compact_tiles). Used by `divoom_lib.framing`
                                   and the GUI's media decoder.

  - `divoom_lib/native_src/downsample.c` — LANCZOS3 image downscaler
                                            (drop-in for `PIL.Image.resize`).
                                            Used by this module.

  - `divoom_lib/native_src/image_encode.c` — palette encoder for 0x44/0x49
                                              image push. Byte-identical to
                                              the pure-Python encoder in
                                              `divoom_lib.utils.divoom_image_encode`.

The dylib is built by `scripts/build_libdivoom.sh` and lives at
`divoom_lib/libdivoom_compact.dylib`.

Public API
----------
- `downsample_lanczos(in_bytes, in_w, in_h, out_w, out_h, channels)` —
  LANCZOS3 downscale, byte-identical to `PIL.Image.resize((out_w, out_h),
  Image.LANCZOS)`. Falls back to a single PIL call if the dylib is
  unavailable.
- `encode_animation_frame(rgb, w, h, time_ms)` — single-frame 0x49 body.
  Falls back to the pure-Python encoder if the dylib is unavailable.
- `encode_static_image(rgb, w, h)` — single-image 0x44 body.
  Falls back to the pure-Python encoder if the dylib is unavailable.
- `encode_animation(frames)` — list of 0x49 packet payloads.
  Falls back to the pure-Python encoder if the dylib is unavailable.
- `is_native_available()` — `True` if the dylib is loaded.
- `CHANNELS_RGB` / `CHANNELS_RGBA` — channel count constants.
"""
from .downscaler import (
    CHANNELS_RGB,
    CHANNELS_RGBA,
    downsample_lanczos,
    is_native_available as _downscaler_is_native_available,
    reset_for_tests as _downscaler_reset_for_tests,
)
from .image_encoder import (
    encode_animation_frame,
    encode_animation,
    encode_static_image,
    is_native_available as _encoder_is_native_available,
    reset_for_tests as _encoder_reset_for_tests,
)


def is_native_available() -> bool:
    """True if the C dylib is loaded for BOTH the downscaler and the encoder."""
    return _downscaler_is_native_available() and _encoder_is_native_available()


def reset_for_tests() -> None:
    """Forget all cached dylib handles. Used by tests to simulate a fresh load."""
    _downscaler_reset_for_tests()
    _encoder_reset_for_tests()


__all__ = [
    "CHANNELS_RGB",
    "CHANNELS_RGBA",
    "downsample_lanczos",
    "encode_animation_frame",
    "encode_animation",
    "encode_static_image",
    "is_native_available",
    "reset_for_tests",
]
