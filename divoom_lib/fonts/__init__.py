"""Bitmap fonts for device-bound text (R28).

The Divoom matrix is 16/32/64px — anti-aliased TrueType text is unreadable at
that resolution, so everything we rasterise for the device uses the crisp bitmap
font in :mod:`divoom_lib.fonts.bitmap_font` (extracted from the official Divoom
APK; see ``scripts/extract_apk_font.py``).
"""
from divoom_lib.fonts.bitmap_font import (
    BitmapFont,
    get_default_font,
    get_small_font,
)

__all__ = ["BitmapFont", "get_default_font", "get_small_font"]
