"""Tests for divoom_lib.utils.divoom_image_encode.

The encoder is the bridge between PIL's RGB output and the Divoom
device's actual on-wire protocol. Bugs here manifest as a spinner
on the device that never resolves (the device is waiting for a
valid `AA` start marker that never arrives). These tests verify
the on-wire byte structure with no real hardware required.
"""
import pytest

from divoom_lib.utils.divoom_image_encode import (
    Frame,
    build_palette_and_pixels,
    encode_palette,
    encode_pixels,
    encode_static_image,
    encode_animation_frame,
    encode_animation,
)


# ───────────────────────── helpers ─────────────────────────


def _u16_be(n: int) -> bytes:
    return n.to_bytes(2, byteorder="big", signed=False)


def _u16_le(n: int) -> bytes:
    return n.to_bytes(2, byteorder="little", signed=False)


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
    rgb = bytes([
        0xFF, 0x00, 0x00,  # red
        0x00, 0xFF, 0x00,  # green
        0x00, 0x00, 0xFF,  # blue
        0xFF, 0xFF, 0xFF,  # white
    ])
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
    rgb = bytes([
        0x00, 0xFF, 0x00,  # green (first)
        0xFF, 0x00, 0x00,  # red (second)
        0xFF, 0x00, 0x00,  # red (already seen)
        0x00, 0xFF, 0x00,  # green (already seen)
    ])
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
    assert encode_palette(palette) == bytes([
        0xFF, 0x00, 0x00,
        0x00, 0xFF, 0x00,
        0x00, 0x00, 0xFF,
    ])


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


# ───────────────────────── static image (0x44) ─────────────────────────


def test_encode_static_image_1pixel_red():
    """A 1x1 red image → known byte sequence."""
    rgb = bytes([0xFF, 0x00, 0x00])  # 1x1 red
    payload = encode_static_image(rgb, 1, 1)
    # Per RomRider reference: LLLL = 7 + 3N + p = 7 + 3 + 1 = 11.
    # Layout: AA LLLL 000000 NN COLOR_DATA PIXEL_DATA
    expected = bytes([
        0xAA,                              # start marker
        0x0B, 0x00,                        # LLLL (LE u16) = 11
        0x00, 0x00, 0x00,                  # 000000 (3 bytes padding)
        0x01,                              # NN (num colors)
        0xFF, 0x00, 0x00,                  # color
        0x00,                              # pixel
    ])
    assert payload == expected


def test_encode_static_image_16x16_red():
    """A 16x16 red image (matches the test fixture in test_e2e_mock_device)."""
    rgb = bytes([0xFF, 0x00, 0x00]) * (16 * 16)
    payload = encode_static_image(rgb, 16, 16)
    # Header: AA LLLL 000000 NN = 7 bytes
    assert payload[0] == 0xAA
    # LLLL = 7 + 3 + 32 = 42
    assert payload[1:3] == bytes([42, 0])
    # 000000 padding
    assert payload[3:6] == bytes([0, 0, 0])
    # NN = 1
    assert payload[6] == 1
    # Color data = 3 bytes
    assert payload[7:10] == bytes([0xFF, 0x00, 0x00])
    # Pixel data: 256 pixels, 1 bit each, 32 bytes. All zeros.
    assert payload[10:] == bytes(32)
    assert len(payload) == 7 + 3 + 32


def test_encode_static_image_2colors_checkerboard():
    """A 2x2 checkerboard (red, green alternating)."""
    # Row 0: red green
    # Row 1: green red
    rgb = bytes([
        0xFF, 0x00, 0x00,  # red (palette idx 0)
        0x00, 0xFF, 0x00,  # green (palette idx 1)
        0x00, 0xFF, 0x00,  # green
        0xFF, 0x00, 0x00,  # red
    ])
    payload = encode_static_image(rgb, 2, 2)
    # pixels: [0, 1, 1, 0], nbBits=1, packed = 0x06 (1 byte)
    # LLLL = 7 + 6 + 1 = 14
    # total = 7 (header) + 6 (palette) + 1 (pixel) = 14
    assert len(payload) == 14
    assert payload[0] == 0xAA
    assert payload[1:3] == bytes([14, 0])
    assert payload[3:6] == bytes([0, 0, 0])
    # NN=2
    assert payload[6] == 2
    # Color data starts at offset 7: red, then green
    assert payload[7:10] == bytes([0xFF, 0x00, 0x00])
    assert payload[10:13] == bytes([0x00, 0xFF, 0x00])
    # Pixel data at offset 13
    assert payload[13] == 0x06


def test_encode_static_image_256_colors_uses_nn_zero():
    """A 256-color image uses NN=0 (device protocol: 0 means 256)."""
    rgb = bytearray()
    for i in range(256):
        rgb.extend([i, 255 - i, i ^ 0xAA])
    payload = encode_static_image(bytes(rgb), 16, 16)
    # LLLL = 7 + 3*256 + 256 = 7 + 768 + 256 = 1031
    assert payload[1:3] == bytes([1031 & 0xFF, 1031 >> 8])
    assert payload[6] == 0  # NN=0 means 256 colors
    # 3 * 256 = 768 color bytes
    # 256 pixels * 8 bits = 256 pixel bytes
    assert len(payload) == 7 + 768 + 256


# ───────────────────────── animation (0x49) ─────────────────────────


def test_encode_animation_frame_1pixel_red_1000ms():
    """A single animation frame: known byte sequence."""
    rgb = bytes([0xFF, 0x00, 0x00])  # 1x1 red
    frame = encode_animation_frame(rgb, 1, 1, time_ms=1000)
    # Per RomRider reference: LLLL = 7 + 3N + p = 11.
    # Layout: AA LLLL TTTT RR NN COLOR_DATA PIXEL_DATA
    # TTTT is LITTLE-ENDIAN (1000 = 0x03E8 → 0xE8 0x03)
    expected = bytes([
        0xAA,                              # start marker
        0x0B, 0x00,                        # LLLL (LE u16) = 11
        0xE8, 0x03,                        # TTTT (LE u16) = 1000
        0x00,                              # RR = 0 (reset palette)
        0x01,                              # NN
        0xFF, 0x00, 0x00,                  # color
        0x00,                              # pixel
    ])
    assert frame == expected


def test_encode_animation_3_frames_fits_in_1_packet():
    """Three small frames concatenate to < 200 bytes → 1 packet."""
    frames = [
        (bytes([0xFF, 0x00, 0x00]), 1, 1, 100),
        (bytes([0x00, 0xFF, 0x00]), 1, 1, 200),
        (bytes([0x00, 0x00, 0xFF]), 1, 1, 300),
    ]
    packets = encode_animation(frames)
    assert len(packets) == 1
    packet = packets[0]
    # Each frame is 11 bytes (1+2+2+2+1+1+3+1), so 33 bytes total
    # Layout per frame: AA LLLL TTTT(LE) RR NN COLOR PIXEL
    blob = (
        b"\xAA\x0B\x00\x64\x00\x00\x01\xFF\x00\x00\x00"  # red, 100ms
        b"\xAA\x0B\x00\xC8\x00\x00\x01\x00\xFF\x00\x00"  # green, 200ms
        b"\xAA\x0B\x00\x2C\x01\x00\x01\x00\x00\xFF\x00"  # blue, 300ms
    )
    # Per RomRider: [TOTAL_LEN LE u16][PACKET_NUM u8][chunk]
    assert packet == _u16_le(len(blob)) + bytes([0]) + blob


def test_encode_animation_large_image_splits_into_packets():
    """A 16x16 image with 200 unique colors per frame splits into multiple packets."""
    rgb = bytearray()
    for y in range(16):
        for x in range(16):
            r = (x * 5) & 0xFF
            g = (y * 7) & 0xFF
            b = (x * 11 + y * 13) & 0xFF
            rgb.extend([r, g, b])
    frames = [(bytes(rgb), 16, 16, 100)]
    packets = encode_animation(frames)
    assert len(packets) > 1
    for i, pkt in enumerate(packets):
        # Packet is 3-byte header (LE u16 + u8) + chunk
        assert len(pkt) <= 3 + 200
        # PACKET_NUM is 0-based, u8 (not u16)
        packet_num = pkt[2]
        assert packet_num == i
        # TOTAL_LEN is the same in every packet, LE u16
        total_len = int.from_bytes(pkt[0:2], byteorder="little")
        assert total_len > 200


def test_encode_animation_empty_returns_empty():
    """Empty frame list → no packets."""
    assert encode_animation([]) == []


def test_encode_animation_total_len_constant_across_packets():
    """TOTAL_LEN is the same in every packet of a multi-packet animation."""
    # Build an animation large enough to span multiple packets.
    # 16x16 RGB with 5 frames → ~2000+ bytes total.
    frames = []
    for f in range(5):
        rgb = bytearray()
        for y in range(16):
            for x in range(16):
                r = (x * 5 + f) & 0xFF
                g = (y * 7 + f) & 0xFF
                b = (x * 11 + y * 13 + f) & 0xFF
                rgb.extend([r, g, b])
        frames.append((bytes(rgb), 16, 16, 200))
    packets = encode_animation(frames)
    assert len(packets) > 1
    total_lens = {int.from_bytes(p[0:2], byteorder="little") for p in packets}
    assert len(total_lens) == 1, "TOTAL_LEN must be the same in every packet"
    payload_sum = sum(len(p) - 3 for p in packets)
    assert payload_sum == total_lens.pop()


# ───────────────────────── end-to-end: known round-trip ─────────────────────────


def test_encode_static_image_round_trip_known_romrider_example():
    """Smoke test: encoder produces non-empty output for a 16x16 2-color image.

    The full byte-by-byte match with the RomRider reference is
    verified by `tests/test_push_protocol_diagnostic.py` on real
    hardware. This test just verifies the encoder doesn't crash and
    produces a payload of the expected length.
    """
    rgb = bytearray()
    for y in range(16):
        for x in range(16):
            color = (0xFF, 0x00, 0x00) if (x + y) % 2 == 0 else (0x00, 0x00, 0x00)
            rgb.extend(color)
    payload = encode_static_image(bytes(rgb), 16, 16)
    # Header (7) + 2 colors (6) + 256 pixels @ 1 bit (32) = 45
    # LLLL = 7 + 6 + 32 = 45
    assert len(payload) == 7 + 6 + 32
    assert payload[0] == 0xAA
    assert payload[1:3] == bytes([45, 0])
    assert payload[6] == 2


def test_frame_dataclass_for_type_hint():
    """The Frame type alias is exported and usable as a type hint."""
    f: Frame = (bytes([0xFF, 0x00, 0x00]), 1, 1, 100)
    assert len(f) == 4
    assert f[3] == 100


# ── Round 11 (item 1b): u16 time clamp + length guard ───────────────────


def test_encode_animation_frame_clamps_oversized_time():
    """A frame time > 65535 must not raise 'int too big to convert' — it is
    clamped into the 2-byte TTTT field."""
    rgb = bytes([10, 20, 30]) * (16 * 16)
    payload = encode_animation_frame(rgb, 16, 16, 999999)  # previously crashed
    assert payload[3:5] == bytes([0xFF, 0xFF])  # TTTT clamped to 0xFFFF


def test_encode_animation_frame_rejects_oversized_body():
    """A body too large for the 2-byte length field raises a clear ValueError
    instead of the opaque 'int too big to convert'.

    Construct 256x256 = 65536 pixels using ~150 colors so nb_bits=8 (1 byte
    per pixel) → body ≈ 7 + 450 + 65536 > 65535.
    """
    rgb = bytearray()
    for i in range(256 * 256):
        c = i % 150  # 150 distinct colors → palette < 256, nb_bits = 8
        rgb.extend([c, c, c])
    with pytest.raises(ValueError, match="exceeds the 2-byte length"):
        encode_animation_frame(bytes(rgb), 256, 256, 100)
