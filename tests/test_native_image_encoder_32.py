"""
Round 4 parity tests for the C image encoder additions:
  - 32x32 frame encoder
  - 32x32 pre-frames
  - 0x8B 3-phase chunker

Mirrors test_native_image_encoder.py for the new C functions in
divoom_lib/native_src/image_encode_32.c. Skipped if the dylib is missing.
"""
import pytest

from divoom_lib.native import image_encoder
from divoom_lib.utils.divoom_image_encode_32 import (
    encode_animation_frame_32 as py_encode_frame_32,
    pre_frames as py_pre_frames,
)
from divoom_lib.display.animation_8b import build_8b_phases as py_build_8b


pytestmark = pytest.mark.skipif(
    not image_encoder.is_native_available(),
    reason="C dylib not available — 32x32/0x8B parity requires libdivoom_compact.dylib"
)


# ---- 32x32 pre-frames (DEPRECATED — APK does NOT use pre-frames) ----

def test_pre_frame_1_c_still_produces_classic_output():
    """C pre-frame functions remain for API backward compat but are unused."""
    p1 = image_encoder._c_write_pre_frame_1()
    assert p1 is not None
    # Layout: [AA][LLLL LE u16] + 5-byte body
    assert p1[0] == 0xAA
    assert p1[1:3] == (8).to_bytes(2, "little")
    assert p1[3:8] == bytes([0x00, 0x00, 0x05, 0x00, 0x00])


def test_pre_frame_2_c_still_produces_classic_output():
    p2 = image_encoder._c_write_pre_frame_2()
    assert p2 is not None
    assert p2[0] == 0xAA
    assert p2[1:3] == (9).to_bytes(2, "little")
    assert p2[3:9] == bytes([0x00, 0x00, 0x06, 0x00, 0x00, 0x00])


def test_pre_frames_32_wrapper_returns_empty_python():
    """Python pre_frames() returns empty list (APK has no pre-frames)."""
    assert py_pre_frames() == []


def test_pre_frames_32_wrapper_still_uses_c_when_available():
    """Wrapper uses C path when available (C still has the old functions)."""
    pf = image_encoder.pre_frames_32()
    # C path still returns the classic 2 pre-frames
    assert len(pf) == 2
    assert pf[0][0] == 0xAA
    assert pf[1][0] == 0xAA


# ---- 32x32 frame encoder ----

def test_32x32_single_color_frame_parity():
    """A 32x32 single-color frame encodes the same in C and Python."""
    w, h = 32, 32
    rgb = bytes((0x80, 0x40, 0x20)) * (w * h)
    py = py_encode_frame_32(rgb, w, h, 0)
    c = image_encoder._c_encode_animation_frame_32(rgb, w, h, 0)
    assert c is not None
    assert c == py


def test_32x32_4color_frame_parity():
    """A 32x32 4-color frame."""
    w, h = 32, 32
    quad = (
        bytes([0xFF, 0x00, 0x00]) * (w * h // 4)
        + bytes([0x00, 0xFF, 0x00]) * (w * h // 4)
        + bytes([0x00, 0x00, 0xFF]) * (w * h // 4)
        + bytes([0xFF, 0xFF, 0x00]) * (w * h // 4)
    )
    py = py_encode_frame_32(quad, w, h, 500)
    c = image_encoder._c_encode_animation_frame_32(quad, w, h, 500)
    assert c is not None
    assert c == py


def test_32x32_header_layout():
    """The 32x32 frame header now uses the standard AA format (RR=0x00, 1-byte NN)."""
    w, h = 32, 32
    rgb = bytes((0xAA, 0xBB, 0xCC)) * (w * h)
    out = image_encoder.encode_animation_frame_32(rgb, w, h, 100)
    assert out[0] == 0xAA
    # Standard LLLL = 7 (header) + 3 (palette 1 color) + 128 (1024 pixels / 8)
    expected_llll = 7 + 3 + 128
    assert out[1:3] == expected_llll.to_bytes(2, "little")
    # TTTT = 100 (LE)
    assert out[3:5] == (100).to_bytes(2, "little")
    # RR = 0x00 (standard format, matches APK)
    assert out[5] == 0x00
    # NN = 1 (u8) — one unique color
    assert out[6] == 1


def test_32x32_wrong_dimensions_rejected():
    """Encoder rejects non-32x32 inputs."""
    rgb = bytes((0, 0, 0)) * (16 * 16)
    c = image_encoder._c_encode_animation_frame_32(rgb, 16, 16, 0)
    assert c is None


# ---- 0x8B 3-phase chunker ----

def test_8b_empty_input_returns_empty():
    """No frames → empty list."""
    assert image_encoder.encode_animation_8b_phases([]) == []


def test_8b_single_frame_phases_layout():
    """A single small frame produces 2 phases: start(5) + data(7+chunk)."""
    w, h = 16, 16
    rgb = bytes((0x11, 0x22, 0x33)) * (w * h)
    frames = [(rgb, w, h, 100)]
    py_phases = py_build_8b(frames)
    c_phases = image_encoder.encode_animation_8b_phases(frames)
    assert len(c_phases) == len(py_phases)
    for cp, pp in zip(c_phases, py_phases):
        assert cp == pp
    # StartSeeding: 5 bytes
    assert len(c_phases[0]) == 5
    assert c_phases[0][0] == 0x00  # CTRL_START_SENDING
    # SendingData: 7 + chunk_size bytes
    assert c_phases[1][0] == 0x01  # CTRL_SENDING_DATA
    assert c_phases[1][5:7] == (0).to_bytes(2, "little")  # offset_id=0
    # No terminate phase (R35d — APK does not send CW=2)


def test_8b_multi_frame_phases_match_python():
    """A 3-frame animation matches Python output for both single + multi chunk."""
    w, h = 32, 32
    rgb = bytes((0x40, 0x50, 0x60)) * (w * h)
    frames = [(rgb, w, h, 100), (rgb, w, h, 200), (rgb, w, h, 300)]
    py_phases = py_build_8b(frames)
    c_phases = image_encoder.encode_animation_8b_phases(frames)
    assert len(c_phases) == len(py_phases)
    for cp, pp in zip(c_phases, py_phases):
        assert cp == pp
    # 3 × 139-byte frames = 417 bytes → 2 data chunks (256 + 161)
    data_phases = c_phases[1:-1]
    assert len(data_phases) == 2
    # offset_id is a chunk INDEX (futpib), not a byte offset.
    # First chunk: index 0
    assert data_phases[0][5:7] == (0).to_bytes(2, "little")
    # Second chunk: index 1
    assert data_phases[1][5:7] == (1).to_bytes(2, "little")


def test_8b_chunks_at_256_boundary():
    """Frames blob > 256 bytes produces multiple data phases."""
    w, h = 32, 32
    rgb = bytes((0xAB, 0xCD, 0xEF)) * (w * h)
    # 4 frames of 32x32 = ~1.5KB → 6+ chunks
    frames = [(rgb, w, h, 100 + i) for i in range(4)]
    py_phases = py_build_8b(frames)
    c_phases = image_encoder.encode_animation_8b_phases(frames)
    assert len(c_phases) == len(py_phases)
    for cp, pp in zip(c_phases, py_phases):
        assert cp == pp
    # Should be > 1 data phase
    assert len(c_phases) > 3
