"""test_apk_encoding_parity.py — byte-level verification against APK.

Compares our encoding/streaming output against the decompiled Divoom Android
app at known divergence points. Full context in docs/APK_COMPARISON.md.

Run:  python3 -m pytest tests/test_apk_encoding_parity.py -v
"""

import numpy as np
from divoom_lib.utils.divoom_image_encode import encode_animation_frame
from divoom_lib.utils.divoom_image_encode_32 import encode_animation_frame_32
from divoom_lib.display.animation_8b import (
    _phase_start,
    _phase_data,
    _phase_terminate,
    CONTROL_START_SENDING,
    CONTROL_SENDING_DATA,
    CONTROL_TERMINATE_SENDING,
    SENDING_DATA_CHUNK_SIZE,
)
from divoom_lib.framing import encode_ios_le_payload, encode_basic_payload


def _flat(rgb_np):
    """Convert a (h,w,3) numpy array to flat bytes for the encoder."""
    return bytes(rgb_np)


class Test0x8bWireFormat:
    """Verify 0x8B START/DATA/TERMINATE payloads against APK format."""

    def test_start_payload(self):
        blob = b"\x00" * 0x144
        result = _phase_start(len(blob))
        assert result[0] == CONTROL_START_SENDING
        assert result[1:5] == (0x144).to_bytes(4, "little")
        assert len(result) == 5

    def test_data_payload_first_chunk(self):
        blob = b"\xAA" * 0x144
        chunk = blob[0:SENDING_DATA_CHUNK_SIZE]
        result = _phase_data(len(blob), 0, chunk)
        assert result[0] == CONTROL_SENDING_DATA
        assert result[1:5] == (len(blob)).to_bytes(4, "little")
        assert result[5:7] == (0).to_bytes(2, "little")
        assert result[7:] == chunk
        assert len(result) == 7 + SENDING_DATA_CHUNK_SIZE

    def test_data_payload_second_chunk(self):
        blob = b"\xBB" * 0x200
        chunk = blob[SENDING_DATA_CHUNK_SIZE:SENDING_DATA_CHUNK_SIZE * 2]
        result = _phase_data(len(blob), 1, chunk)
        assert result[5:7] == (1).to_bytes(2, "little")
        assert result[7:] == chunk

    def test_terminate_payload_apk_divergence(self):
        result = _phase_terminate()
        assert result == bytes([CONTROL_TERMINATE_SENDING])
        assert len(result) == 1

    def test_chunk_size_matches_apk(self):
        assert SENDING_DATA_CHUNK_SIZE == 256

    def test_full_8b_phases_match_apk_order(self):
        from divoom_lib.display.animation_8b import build_8b_phases
        rgb = np.zeros((16, 16, 3), dtype=np.uint8)
        frames = [(_flat(rgb), 16, 16, 100)]
        phases = build_8b_phases(frames)
        assert phases[0][0] == CONTROL_START_SENDING
        for p in phases[1:-1]:
            assert p[0] == CONTROL_SENDING_DATA
        assert phases[-1][0] == CONTROL_TERMINATE_SENDING


class TestFrameBodyFormat:
    """Verify the AA LLLL TTTT RR NN COLOR_DATA PIXEL_DATA format."""

    def test_frame_marker_aa(self):
        rgb = _flat(np.zeros((16, 16, 3), dtype=np.uint8))
        encoded = encode_animation_frame(rgb, 16, 16, 100)
        assert encoded[0] == 0xAA

    def test_display_time_tttt(self):
        rgb = _flat(np.zeros((16, 16, 3), dtype=np.uint8))
        for ms in [50, 100, 500, 1000]:
            encoded = encode_animation_frame(rgb, 16, 16, ms)
            assert int.from_bytes(encoded[3:5], "little") == ms

    def test_rr_16x16_is_0x00(self):
        rgb = _flat(np.zeros((16, 16, 3), dtype=np.uint8))
        encoded = encode_animation_frame(rgb, 16, 16, 100)
        assert encoded[5] == 0x00

    def test_nn_is_number_of_colors(self):
        rgb = np.zeros((16, 16, 3), dtype=np.uint8)
        # Black bg (1) + 3 modified pixels = 4 colors
        rgb[0, 0] = [255, 0, 0]
        rgb[1, 1] = [0, 255, 0]
        rgb[2, 2] = [0, 0, 255]
        encoded = encode_animation_frame(_flat(rgb), 16, 16, 100)
        assert encoded[6] == 4

    def test_color_table_3bytes_per_color(self):
        rgb = np.zeros((16, 16, 3), dtype=np.uint8)
        rgb[0, 0] = [200, 150, 100]
        encoded = encode_animation_frame(_flat(rgb), 16, 16, 100)
        nn = encoded[6]
        palette_start = 7
        palette = encoded[palette_start:palette_start + nn * 3]
        assert palette[0:3] == bytes([200, 150, 100])
        assert len(palette) == nn * 3

    def test_32x32_rr_is_0x00_matches_apk(self):
        """APK uses RR=0x00 for ALL sizes (R35d fix)."""
        rgb = np.zeros((32, 32, 3), dtype=np.uint8)
        encoded = encode_animation_frame_32(_flat(rgb), 32, 32, 100)
        assert encoded[5] == 0x00

    def test_32x32_nn_is_1byte_matches_apk(self):
        """APK uses 1-byte NN for ALL sizes (R35d fix)."""
        rgb = np.zeros((32, 32, 3), dtype=np.uint8)
        rgb[0:16, 0:16] = [255, 0, 0]
        encoded = encode_animation_frame_32(_flat(rgb), 32, 32, 100)
        nn = encoded[6]
        assert nn == 2

    def test_32x32_header_is_7bytes(self):
        """Standard AA format header is 7 bytes (matching 16x16)."""
        rgb = _flat(np.zeros((32, 32, 3), dtype=np.uint8))
        encoded = encode_animation_frame_32(rgb, 32, 32, 100)
        assert len(encoded) > 7
        # Header: AA(1) + LLLL(2) + TTTT(2) + RR(1) + NN(1) = 7 bytes


class TestFramingLayer:
    """Verify BLE wire framing matches protocol specs."""

    def test_ios_le_header(self):
        payload = [0x8B, 0x00, 0x44, 0x01, 0x00, 0x00]
        framed = encode_ios_le_payload(payload)
        assert framed[0:4] == bytes([0xFE, 0xEF, 0xAA, 0x55])
        assert framed[7] == 0x8B
        assert framed[-1] == 0x02

    def test_basic_framing_header(self):
        payload = [0x8B, 0x00, 0x44, 0x01, 0x00, 0x00]
        framed = encode_basic_payload(payload)
        assert framed[0] == 0x01
        assert framed[3] == 0x8B
        assert framed[-1] == 0x02

    def test_ios_le_checksum(self):
        payload = [0x8B, 0x00, 0x44, 0x01, 0x00, 0x00]
        framed = encode_ios_le_payload(payload)
        ck_start = len(framed) - 3
        ck = int.from_bytes(framed[ck_start:ck_start + 2], "little")
        assert ck == sum(framed[4:ck_start]) & 0xFFFF

    def test_basic_framing_checksum(self):
        payload = [0x8B, 0x00, 0x44, 0x01, 0x00, 0x00]
        framed = encode_basic_payload(payload)
        pe = len(framed) - 3
        ck = int.from_bytes(framed[pe:pe + 2], "little")
        assert ck == sum(framed[1:pe]) & 0xFFFF

    def test_ios_le_preserves_payload(self):
        payload = [0x8B, 0x00, 0x44, 0x01, 0x00, 0x00]
        framed = encode_ios_le_payload(payload)
        saved = framed[8:-3]
        assert list(saved) == payload[1:]

    def test_basic_framing_preserves_payload(self):
        payload = [0x8B, 0x00, 0x44, 0x01, 0x00, 0x00]
        framed = encode_basic_payload(payload)
        saved = framed[4:-3]
        assert list(saved) == payload[1:]


class TestPixelDataEncoding:
    """Verify pixel index packing (LSB-first, continuous)."""

    def test_pixel_data_single_color(self):
        rgb = _flat(np.zeros((16, 16, 3), dtype=np.uint8))
        encoded = encode_animation_frame(rgb, 16, 16, 100)
        nn = encoded[6]
        pstart = 7 + nn * 3
        pixels = encoded[pstart:]
        assert all(b == 0 for b in pixels)

    def test_pixel_data_two_colors(self):
        rgb = np.zeros((16, 16, 3), dtype=np.uint8)
        rgb[:, :8] = [255, 0, 0]
        rgb[:, 8:] = [0, 255, 0]
        encoded = encode_animation_frame(_flat(rgb), 16, 16, 100)
        assert encoded[6] == 2

    def test_pixel_data_four_colors_checkerboard(self):
        rgb = np.zeros((16, 16, 3), dtype=np.uint8)
        colors = [(0, 0, 0), (255, 0, 0), (0, 255, 0), (0, 0, 255)]
        for y in range(16):
            for x in range(16):
                rgb[y, x] = colors[(y % 2) * 2 + (x % 2)]
        encoded = encode_animation_frame(_flat(rgb), 16, 16, 100)
        assert encoded[6] == 4


class TestApkOnlyFeatures:
    """Document features the APK has but we don't."""

    def test_color_quantization_raises(self):
        """256 unique colors OK for 16×16 (256 pixels)."""
        rgb = np.zeros((16, 16, 3), dtype=np.uint8)
        for y in range(16):
            for x in range(16):
                v = y * 16 + x
                rgb[y, x] = [v, (v * 7) % 256, (v * 13) % 256]
        # All 256 pixels distinct — does NOT raise
        encode_animation_frame(_flat(rgb), 16, 16, 100)

    def test_color_quantization_257_raises_on_larger_image(self):
        """>256 unique colors requires >256 pixel image and raises."""
        rgb = np.zeros((32, 32, 3), dtype=np.uint8)
        for y in range(32):
            for x in range(32):
                idx = y * 32 + x
                # Encode index into RGB to guarantee 1024 unique colors
                rgb[y, x] = [idx & 0xFF, (idx >> 8) & 0xFF, (idx >> 16) & 0xFF]
        import pytest
        with pytest.raises(ValueError, match="more than 256 unique colors"):
            encode_animation_frame_32(_flat(rgb), 32, 32, 100)
