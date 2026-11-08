"""
LANCZOS3 image downscaler -- a single PIL call.

This once tried the `libdivoom_compact` dylib first (the C pipeline:
per-channel LANCZOS3 for RGB; premultiply, resample, un-premultiply for RGBA)
and fell back to `PIL.Image.resize`. The dylib was deleted in L4 (2026-09-25,
9a1cade), so the C branch could never load and PIL is what has always run. The
unreachable branch is deleted; the output is unchanged.

This is a *library* function: not just for cover art. Future callers:
  - Google Photos album thumbnails
  - Live wallpaper rendering
  - Animation frame rescaling
  - Any time we need a deterministic downscale to a Divoom buffer
"""

from __future__ import annotations

from PIL import Image

CHANNELS_RGB = 3
CHANNELS_RGBA = 4


def _pil_downsample(in_bytes: bytes, in_w: int, in_h: int, out_w: int, out_h: int, channels: int) -> bytes:
    """LANCZOS3 downscale via PIL."""
    mode = "RGB" if channels == CHANNELS_RGB else "RGBA"
    img = Image.frombytes(mode, (in_w, in_h), in_bytes)
    out = img.resize((out_w, out_h), Image.Resampling.LANCZOS)
    return out.tobytes()


def downsample_lanczos(
    in_bytes: bytes, in_w: int, in_h: int, out_w: int, out_h: int, channels: int = CHANNELS_RGB
) -> bytes:
    """LANCZOS3 downscale, identical to PIL.Image.resize(..., LANCZOS).

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
        raise ValueError(f"dimensions must be positive, got in=({in_w},{in_h}) out=({out_w},{out_h})")
    expected_in = in_w * in_h * channels
    if len(in_bytes) != expected_in:
        raise ValueError(f"in_bytes length {len(in_bytes)} != in_w*in_h*channels = {expected_in}")

    return _pil_downsample(in_bytes, in_w, in_h, out_w, out_h, channels)
