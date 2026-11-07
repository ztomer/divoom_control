"""Tests for divoom_legacy.utils.divoom_image_encode -- the primitives.

Palette dedup, palette byte encoding and LSB-first bit packing. The packet
builders that use them (static 0x44, animation 0x49) are in
``test_divoom_image_encode.py``.
"""

import pytest

from divoom_legacy.utils.divoom_image_encode import (
    Frame,
    build_palette_and_pixels,
    encode_palette,
    encode_pixels,
    encode_static_image,
    encode_animation_frame,
    encode_animation,
)


# ───────────────────────── palette + bit-pack primitives ─────────────────────────


def test_palette_dedup_one_color():
    """A single-color 2x2 image has 1 palette entry, nbBits=1."""
    rgb = bytes([0xFF, 0x00, 0x00]) * 4  # 2x2 red
    palette, pixels, nb_bits = build_palette_and_pixels(rgb, 2, 2)
    assert palette == [(0xFF, 0x00, 0x00)]
    assert pixels == [0, 0, 0, 0]
    assert nb_bits == 1


def test_palette_dedup_two_colors():
    """A 2-color image has 2 palette entries, nbBits=1."""
    rgb = bytes([0xFF, 0x00, 0x00, 0x00, 0xFF, 0x00])  # red, green
    palette, pixels, nb_bits = build_palette_and_pixels(rgb, 2, 1)
    assert palette == [(0xFF, 0x00, 0x00), (0x00, 0xFF, 0x00)]
    assert pixels == [0, 1]
    assert nb_bits == 1


def test_palette_dedup_four_colors():
    """A 4-color image has 4 palette entries, nbBits=2 (log2(4)=2)."""
    rgb = bytes(
        [
            0xFF,
            0x00,
            0x00,  # red
            0x00,
            0xFF,
            0x00,  # green
            0x00,
            0x00,
            0xFF,  # blue
            0xFF,
            0xFF,
            0xFF,  # white
        ]
    )
    palette, pixels, nb_bits = build_palette_and_pixels(rgb, 4, 1)
    assert len(palette) == 4
    assert nb_bits == 2


def test_palette_dedup_256_colors():
    """A 256-color image has 256 palette entries, nbBits=8."""
    rgb = bytearray()
    for i in range(256):
        rgb.extend([i, i, i])  # 256 unique gray shades
    palette, pixels, nb_bits = build_palette_and_pixels(bytes(rgb), 256, 1)
    assert len(palette) == 256
    assert nb_bits == 8


def test_palette_too_many_colors_raises():
    """An image with >256 unique colors is rejected (device can't represent it)."""
    # 257 unique colors, each differing in the R channel via a hash that
    # wraps into 0-255. (i * 17 + 31) & 0xFF gives a permutation of [0,255]
    # extended by one more unique value at the 257th iteration.
    rgb = bytearray()
    seen = set()
    for i in range(257):
        r = (i * 17 + 31) & 0xFF
        g = (i * 13 + 7) & 0xFF
        b = (i * 29 + 11) & 0xFF
        color = (r, g, b)
        if color in seen:
            # Avoid collisions; bump b until unique
            for bump in range(256):
                candidate = (r, g, (b + bump) & 0xFF)
                if candidate not in seen:
                    color = candidate
                    break
        seen.add(color)
        rgb.extend(color)
    with pytest.raises(ValueError, match="more than 256 unique colors"):
        build_palette_and_pixels(bytes(rgb), 257, 1)


def test_palette_first_seen_order_is_canonical():
    """The palette is in first-seen order (deterministic)."""
    # 2x2 image: green, red, red, green
    rgb = bytes(
        [
            0x00,
            0xFF,
            0x00,  # green (first)
            0xFF,
            0x00,
            0x00,  # red (second)
            0xFF,
            0x00,
            0x00,  # red (already seen)
            0x00,
            0xFF,
            0x00,  # green (already seen)
        ]
    )
    palette, pixels, nb_bits = build_palette_and_pixels(rgb, 2, 2)
    assert palette == [(0x00, 0xFF, 0x00), (0xFF, 0x00, 0x00)]
    assert pixels == [0, 1, 1, 0]
    assert nb_bits == 1


def test_palette_wrong_size_raises():
    """rgb_bytes length must equal w*h*3."""
    rgb = bytes([0xFF, 0x00, 0x00])  # 1 byte too few
    with pytest.raises(ValueError, match="rgb_bytes length"):
        build_palette_and_pixels(rgb, 2, 1)


# ───────────────────────── palette byte encoding ─────────────────────────


def test_encode_palette_empty():
    """An empty palette is zero bytes."""
    assert encode_palette([]) == b""


def test_encode_palette_three_colors():
    """Three colors → 9 bytes (3 per color, R G B)."""
    palette = [(0xFF, 0x00, 0x00), (0x00, 0xFF, 0x00), (0x00, 0x00, 0xFF)]
    assert encode_palette(palette) == bytes(
        [
            0xFF,
            0x00,
            0x00,
            0x00,
            0xFF,
            0x00,
            0x00,
            0x00,
            0xFF,
        ]
    )


# ───────────────────────── bit packing ─────────────────────────


def test_encode_pixels_1bit():
    """nbBits=1: 8 pixels per byte, LSB first into LSB-first byte."""
    # Pixels [1, 0, 1, 0, 1, 0, 1, 0] → byte 0b01010101 = 0x55
    assert encode_pixels([1, 0, 1, 0, 1, 0, 1, 0], 1) == bytes([0x55])
    # Pixels [0, 0, 0, 0, 0, 0, 0, 0] → byte 0x00
    assert encode_pixels([0] * 8, 1) == bytes([0x00])
    # Pixels [1, 1, 1, 1, 1, 1, 1, 1] → byte 0xFF
    assert encode_pixels([1] * 8, 1) == bytes([0xFF])


def test_encode_pixels_2bit():
    """nbBits=2: 4 pixels per byte.

    Pixels [0, 1, 2, 3]:
      pixel 0 (idx=0): bits [0,1] = 00
      pixel 1 (idx=1): bits [2,3] = 01
      pixel 2 (idx=2): bits [4,5] = 10
      pixel 3 (idx=3): bits [6,7] = 11
    → byte 0b11100100 = 0xE4
    """
    assert encode_pixels([0, 1, 2, 3], 2) == bytes([0xE4])


def test_encode_pixels_4bit():
    """nbBits=4: 2 pixels per byte (low nibble = first pixel, high nibble = second)."""
    # Pixels [0xA, 0x5] → byte = (0x5 << 4) | 0xA = 0x5A
    assert encode_pixels([0xA, 0x5], 4) == bytes([0x5A])


def test_encode_pixels_8bit():
    """nbBits=8: 1 pixel per byte, no packing."""
    assert encode_pixels([0x00, 0x7F, 0x80, 0xFF], 8) == bytes([0x00, 0x7F, 0x80, 0xFF])


def test_encode_pixels_1bit_unaligned():
    """nbBits=1: leftover bits in final byte are zero-padded."""
    # 9 pixels: 8 fit in one byte, 1 leftover → 2 bytes
    pixels = [1, 0, 1, 0, 1, 0, 1, 0, 1]
    result = encode_pixels(pixels, 1)
    assert len(result) == 2
    assert result[0] == 0x55  # first 8 pixels
    assert result[1] == 0x01  # 9th pixel at bit 0


def _decode_pixels_lsb_first(data: bytes, nb_bits: int, count: int):
    """Reference LSB-first continuous unpacker (mirrors bitstream_io LE)."""
    out = []
    acc = 0
    acc_bits = 0
    pos = 0
    mask = (1 << nb_bits) - 1
    for _ in range(count):
        while acc_bits < nb_bits:
            acc |= data[pos] << acc_bits
            acc_bits += 8
            pos += 1
        out.append(acc & mask)
        acc >>= nb_bits
        acc_bits -= nb_bits
    return out


def test_encode_pixels_6bit_spans_byte_boundary():
    """nb_bits=6: pixels cross byte boundaries; high bits must carry, not drop.

    [1, 2, 3] → byte0 = 1 | (2<<6)=0x81; remaining bits of 2 (0b0000) + 3<<? ...
    verified by hand: [0x81, 0x30, 0x00]."""
    assert encode_pixels([1, 2, 3], 6) == bytes([0x81, 0x30, 0x00])


def test_encode_pixels_3bit_spans_byte_boundary():
    """nb_bits=3: [1,2,3,4] → [0xD1, 0x08] (hand-verified)."""
    assert encode_pixels([1, 2, 3, 4], 3) == bytes([0xD1, 0x08])


@pytest.mark.parametrize("nb_bits", [1, 2, 3, 4, 5, 6, 7, 8])
def test_encode_pixels_round_trip_all_widths(nb_bits):
    """Encoding then LSB-first decoding recovers the indices for every width —
    this is the property the device's bitstream_io LE reader relies on."""
    import random

    rng = random.Random(nb_bits)
    maxv = (1 << nb_bits) - 1
    pixels = [rng.randint(0, maxv) for _ in range(256)]
    encoded = encode_pixels(pixels, nb_bits)
    assert len(encoded) == (256 * nb_bits + 7) // 8
    assert _decode_pixels_lsb_first(encoded, nb_bits, 256) == pixels


def test_encode_pixels_index_too_large_raises():
    """A pixel index that doesn't fit in nbBits is rejected."""
    with pytest.raises(ValueError, match="doesn't fit in 2 bits"):
        encode_pixels([0, 4], 2)  # 4 needs 3 bits


def test_encode_pixels_invalid_nb_bits_raises():
    """nbBits must be in [1, 8]."""
    with pytest.raises(ValueError, match="nb_bits must be in"):
        encode_pixels([0, 1], 0)
    with pytest.raises(ValueError, match="nb_bits must be in"):
        encode_pixels([0, 1], 9)
