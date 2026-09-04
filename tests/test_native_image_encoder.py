"""
Parity tests for the C image encoder.

The C encoder in `divoom_lib/native_src/image_encode.c` MUST produce
byte-identical output to the pure-Python encoder in
`divoom_lib/utils/divoom_image_encode.py` for any input. These tests
verify that across a wide range of:
  - image sizes (16x16, 32x32, 64x64, 100x100, 160x140)
  - color counts (1, 2, 4, 16, 256)
  - image content (random, single color, 4-color quadrants, edge cases)
  - animation lengths (1, 3, 10, 50 frames)

If the dylib is missing, these tests are SKIPPED (not failed). The
encoder wrapper falls back to pure-Python in that case.
"""
import os
import random
import sys

import pytest

from divoom_lib.native import image_encoder
from divoom_lib.utils.divoom_image_encode import (
    encode_animation_frame as py_encode_animation_frame,
    encode_static_image as py_encode_static_image,
    _py_encode_animation,
)


# Skip the whole module if the dylib isn't built.
pytestmark = pytest.mark.skipif(
    not image_encoder.is_native_available(),
    reason="C dylib not available — image encoder parity requires libdivoom_compact.dylib"
)


# ---- helpers ----

def _make_random_rgb(w: int, h: int, num_colors: int = 256, seed: int = 0) -> bytes:
    """Build a w*h*3 byte string with `num_colors` distinct colors."""
    rng = random.Random(seed)
    palette = [
        (rng.randrange(256), rng.randrange(256), rng.randrange(256))
        for _ in range(num_colors)
    ]
    out = bytearray()
    for _ in range(w * h):
        r, g, b = palette[rng.randrange(num_colors)]
        out.extend((r, g, b))
    return bytes(out)


def _make_solid_rgb(w: int, h: int, r: int, g: int, b: int) -> bytes:
    return bytes((r, g, b)) * (w * h)


# ---- single frame parity ----

@pytest.mark.parametrize("w,h,seed,num_colors", [
    (1, 1, 1, 1),                  # smallest
    (1, 1, 2, 256),                # 1-pixel 256-color
    (2, 2, 3, 2),                  # 4-pixel 2-color
    (16, 16, 4, 1),                # 16x16 solid
    (16, 16, 5, 2),                # 16x16 2-color
    (16, 16, 6, 4),                # 16x16 4-color
    (16, 16, 7, 16),               # 16x16 16-color
    (16, 16, 8, 256),              # 16x16 256-color
    (16, 16, 9, 100),              # 16x16 unaligned color count
    (32, 32, 10, 8),
    (32, 32, 11, 256),
    (64, 64, 12, 32),
    (64, 64, 13, 256),
    (100, 100, 14, 64),            # non-square
    (160, 140, 15, 256),           # Tivoo Max size
    (16, 32, 16, 5),               # non-square, unaligned
    (3, 5, 17, 3),                 # tiny non-power-of-2
])
def test_encode_animation_frame_parity(w, h, seed, num_colors):
    """C encoder must match Python byte-for-byte for every (w, h, num_colors)."""
    rgb = _make_random_rgb(w, h, num_colors, seed=seed)
    time_ms = random.Random(seed).randrange(0, 65536)
    py = py_encode_animation_frame(rgb, w, h, time_ms)
    cn = image_encoder.encode_animation_frame(rgb, w, h, time_ms)
    assert cn == py, (
        f"Parity mismatch at w={w} h={h} num_colors={num_colors} seed={seed} "
        f"time_ms={time_ms}: "
        f"len(py)={len(py)} len(c)={len(cn)}, "
        f"first diff at byte {[i for i, (a, b) in enumerate(zip(py, cn)) if a != b][:3]}"
    )


def test_encode_static_image_parity_quadrant():
    """4-color quadrant 16x16 — the case verified live on Timoo."""
    rgb = bytearray()
    for y in range(16):
        for x in range(16):
            if x < 8 and y < 8: rgb.extend((255, 0, 0))
            elif x >= 8 and y < 8: rgb.extend((0, 255, 0))
            elif x < 8 and y >= 8: rgb.extend((0, 0, 255))
            else: rgb.extend((255, 255, 0))
    py = py_encode_static_image(bytes(rgb), 16, 16)
    cn = image_encoder.encode_static_image(bytes(rgb), 16, 16)
    assert cn == py
    # And the exact wire bytes we know are correct
    assert cn[:7] == bytes.fromhex("aa530000000004")


@pytest.mark.parametrize("w,h,seed,num_colors", [
    (16, 16, 100, 1),
    (16, 16, 101, 2),
    (16, 16, 102, 4),
    (16, 16, 103, 16),
    (16, 16, 104, 256),
    (32, 32, 105, 32),
    (64, 64, 106, 64),
])
def test_encode_static_image_parity(w, h, seed, num_colors):
    """C static encoder must match Python for any (w, h, num_colors)."""
    rgb = _make_random_rgb(w, h, num_colors, seed=seed)
    py = py_encode_static_image(rgb, w, h)
    cn = image_encoder.encode_static_image(rgb, w, h)
    assert cn == py


# ---- animation parity (the path that show_image actually uses) ----

@pytest.mark.parametrize("n_frames,w,h,seed,num_colors", [
    (1, 16, 16, 200, 1),       # 1-frame "static" (Timoo actual usage)
    (1, 16, 16, 201, 4),       # 1-frame 4-color (Timoo quadrant test)
    (1, 32, 32, 202, 16),
    (1, 64, 64, 203, 256),
    (3, 16, 16, 204, 8),       # 3-frame 1-packet
    (3, 32, 32, 205, 32),      # 3-frame multi-packet
    (10, 16, 16, 206, 16),
    (50, 16, 16, 207, 8),      # stress
    (10, 64, 64, 208, 64),     # large frame count
    (5, 160, 140, 209, 64),    # Tivoo Max frame
])
def test_encode_animation_parity(n_frames, w, h, seed, num_colors):
    """Animation packets must be byte-identical between C and Python paths."""
    rng = random.Random(seed)
    frames = []
    for i in range(n_frames):
        rgb = _make_random_rgb(w, h, num_colors, seed=seed * 1000 + i)
        time_ms = rng.randrange(100, 2000)
        frames.append((rgb, w, h, time_ms))

    py_packets = _py_encode_animation(frames)
    c_packets = image_encoder.encode_animation(frames)

    assert len(py_packets) == len(c_packets), (
        f"Packet count mismatch: py={len(py_packets)} c={len(c_packets)}"
    )
    for i, (a, b) in enumerate(zip(py_packets, c_packets)):
        assert a == b, f"Packet {i} mismatch: py={len(a)} c={len(b)}"


def test_encode_animation_parity_empty():
    """Empty input must produce empty output, both paths."""
    assert _py_encode_animation([]) == []
    assert image_encoder.encode_animation([]) == []


# ---- edge cases ----

def test_encode_animation_frame_all_same_color():
    """All-pixels-same-color → 1-color palette, 1 bit/pixel."""
    rgb = _make_solid_rgb(16, 16, 0xAB, 0xCD, 0xEF)
    py = py_encode_animation_frame(rgb, 16, 16, 1000)
    cn = image_encoder.encode_animation_frame(rgb, 16, 16, 1000)
    assert cn == py
    # 7 header + 3 colors + 32 pixel bytes (256 bits / 8) = 42
    assert len(cn) == 7 + 3 + 32
    # NN = 1
    assert cn[6] == 1


def test_encode_animation_frame_256_distinct_colors():
    """256-color image → NN=0 in wire format, 8 bits/pixel."""
    rgb = bytearray()
    for i in range(256):
        r = i & 0xFF
        g = (i * 7) & 0xFF
        b = (i * 13) & 0xFF
        rgb.extend((r, g, b))
    # Pad to 256 pixels (16x16)
    while len(rgb) < 16 * 16 * 3:
        rgb.extend((0, 0, 0))
    py = py_encode_animation_frame(bytes(rgb)[:16*16*3], 16, 16, 500)
    cn = image_encoder.encode_animation_frame(bytes(rgb)[:16*16*3], 16, 16, 500)
    assert cn == py
    # NN = 0 means 256 colors per the device protocol
    assert cn[6] == 0


def test_encode_animation_frame_wide_time_ms():
    """time_ms can be 0 or 65535 (max u16)."""
    rgb = _make_random_rgb(4, 4, 2, seed=999)
    py_lo = py_encode_animation_frame(rgb, 4, 4, 0)
    cn_lo = image_encoder.encode_animation_frame(rgb, 4, 4, 0)
    assert cn_lo == py_lo
    py_hi = py_encode_animation_frame(rgb, 4, 4, 65535)
    cn_hi = image_encoder.encode_animation_frame(rgb, 4, 4, 65535)
    assert cn_hi == py_hi
    # TTTT at offset 3-4 is little-endian
    assert cn_lo[3:5] == bytes([0x00, 0x00])
    assert cn_hi[3:5] == bytes([0xFF, 0xFF])


def test_packets_have_correct_header_layout():
    """Each animation packet: [TOTAL_LEN LE u16][PACKET_NUM u8][chunk].

    Per RomRider reference (and confirmed via live device test on
    2026-06-05: BE + 2-byte-counter silently fails to play multi-frame
    animations on Timoo; LE + 1-byte-counter works).
    """
    rgb = _make_random_rgb(16, 16, 4, seed=300)
    # 1 frame is small; chain many to force multi-packet output
    frames = [(rgb, 16, 16, 1000)] * 10
    packets = image_encoder.encode_animation(frames)
    # Each packet is 3 (header) + chunk_size_i bytes.
    total_len_le = int.from_bytes(packets[0][:2], "little")
    assert total_len_le == sum(len(p) - 3 for p in packets)
    for i, pkt in enumerate(packets):
        total = int.from_bytes(pkt[:2], "little")
        num = pkt[2]
        assert total == total_len_le
        assert num == i
        # The chunk starts at offset 3
        chunk = pkt[3:]
        assert len(chunk) <= 200  # protocol limit per packet
