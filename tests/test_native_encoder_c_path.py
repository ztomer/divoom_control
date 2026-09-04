"""REAL C-path parity tests for the native image encoder.

Why this exists (R53 round 28): the sibling `test_native_image_encoder.py`
calls the public wrappers (`image_encoder.encode_animation_frame` etc.), which
size the output buffer at 1bpp. The C functions reject an undersize buffer and
the wrapper silently falls back to pure-Python — so those "parity" tests compare
Python-against-Python and NEVER execute the C packer. They were false positives.

A buffer-aliasing bug (the C encoders aliased the per-pixel index scratch array
onto out_buf, so the pixel packer overwrote not-yet-consumed indices) corrupted
the C output and went undetected for exactly that reason. These tests drive the
C functions DIRECTLY with a worst-case (8bpp) buffer so the C packer actually
runs, and assert byte-identical output against the pure-Python reference.

Teeth: against the pre-fix dylib these tests FAIL (the C output diverges from
Python, e.g. 32x32 nc=2 diverges at byte 14); against the fixed + rebuilt dylib
they pass. If the dylib is missing they SKIP.
"""
import ctypes
import random

import pytest

from divoom_lib.native import image_encoder
from divoom_lib.utils.divoom_image_encode import (
    encode_animation_frame as py_encode_animation_frame,
    encode_static_image as py_encode_static_image,
)
from divoom_lib.utils.divoom_image_encode_32 import (
    encode_animation_frame_32 as py_encode_animation_frame_32,
)

pytestmark = pytest.mark.skipif(
    not image_encoder.is_native_available(),
    reason="C dylib not available — native parity requires libdivoom_compact.dylib",
)


def _patterned_rgb(w: int, h: int, num_colors: int, seed: int) -> bytes:
    """A deterministic NON-uniform pixel-index pattern. The aliasing bug only
    manifests when the packed-byte write cursor overtakes unread index bytes,
    which depends on the index *pattern* — a flat top/bottom split can hide it,
    so we interleave colors across the whole frame."""
    rng = random.Random(seed)
    palette = [
        (rng.randrange(256), rng.randrange(256), rng.randrange(256))
        for _ in range(num_colors)
    ]
    out = bytearray()
    for y in range(h):
        for x in range(w):
            out.extend(palette[(x * 7 + y * 13) % num_colors])
    return bytes(out)


def _c_frame_worstcase(rgb: bytes, w: int, h: int, time_ms: int) -> bytes:
    """Call the C `divoom_encode_animation_frame` with a worst-case (8bpp)
    buffer so the C packer runs (the public wrapper would undersize → reject →
    Python fallback). Returns the C-produced bytes."""
    lib = image_encoder._load_lib()
    assert lib is not None
    worst = 7 + 256 * 3 + (w * h * 8 + 7) // 8
    out = (ctypes.c_uint8 * worst)()
    src = (ctypes.c_uint8 * len(rgb)).from_buffer_copy(rgb)
    rc = lib.divoom_encode_animation_frame(src, w, h, time_ms, out, worst)
    assert rc > 0, f"C encoder rejected a worst-case buffer (rc={rc})"
    return bytes(out[:rc])


# ── 32x32 encoder (the confirmed-diverging path: reachable via its own wrapper) ──

@pytest.mark.parametrize("num_colors", [1, 2, 3, 4, 7, 16, 17, 64, 200, 256])
def test_c_frame_32_matches_python(num_colors):
    rgb = _patterned_rgb(32, 32, num_colors, seed=num_colors)
    py = bytes(py_encode_animation_frame_32(rgb, 32, 32, 123))
    cn = bytes(image_encoder._c_encode_animation_frame_32(rgb, 32, 32, 123))
    assert cn == py, (
        f"32x32 nc={num_colors}: C diverges from Python — len(py)={len(py)} "
        f"len(c)={len(cn)}, first diff at "
        f"{[i for i, (a, b) in enumerate(zip(py, cn)) if a != b][:3]}"
    )


# ── arbitrary-size frame encoder (image_encode.c) driven directly ──

@pytest.mark.parametrize("w,h", [(8, 8), (16, 16), (32, 32), (16, 32), (5, 7)])
@pytest.mark.parametrize("num_colors", [1, 2, 5, 16, 64, 256])
def test_c_frame_arbitrary_matches_python(w, h, num_colors):
    if num_colors > w * h:
        pytest.skip("more colors than pixels")
    rgb = _patterned_rgb(w, h, num_colors, seed=w * 100 + h + num_colors)
    py = bytes(py_encode_animation_frame(rgb, w, h, 77))
    cn = _c_frame_worstcase(rgb, w, h, 77)
    assert cn == py, (
        f"{w}x{h} nc={num_colors}: C diverges from Python — len(py)={len(py)} "
        f"len(c)={len(cn)}, first diff at "
        f"{[i for i, (a, b) in enumerate(zip(py, cn)) if a != b][:3]}"
    )


def _c_static_worstcase(rgb: bytes, w: int, h: int) -> bytes:
    """Call the C `divoom_encode_static_image` directly with a worst-case buffer
    so the C packer runs (bypassing the wrapper's Python fallback)."""
    lib = image_encoder._load_lib()
    assert lib is not None
    worst = 7 + 256 * 3 + (w * h * 8 + 7) // 8
    out = (ctypes.c_uint8 * worst)()
    src = (ctypes.c_uint8 * len(rgb)).from_buffer_copy(rgb)
    rc = lib.divoom_encode_static_image(src, w, h, out, worst)
    assert rc > 0, f"C static encoder rejected a worst-case buffer (rc={rc})"
    return bytes(out[:rc])


@pytest.mark.parametrize("w,h", [(1, 1), (2, 2), (8, 8), (16, 16), (5, 7)])
@pytest.mark.parametrize("num_colors", [1, 2, 5, 16, 256])
def test_c_static_matches_python(w, h, num_colors):
    """Direct C-path teeth for divoom_encode_static_image. The C header was 6
    bytes (the NN palette-count byte at out_buf[6] was clobbered by the palette
    memcpy), diverging from Python's correct 7-byte header. Against the pre-fix
    dylib this FAILS (C is 1 byte short, NN missing); fixed + rebuilt it passes."""
    if num_colors > w * h:
        pytest.skip("more colors than pixels")
    rgb = _patterned_rgb(w, h, num_colors, seed=w * 100 + h + num_colors)
    py = bytes(py_encode_static_image(rgb, w, h))
    cn = _c_static_worstcase(rgb, w, h)
    assert cn == py, (
        f"{w}x{h} nc={num_colors}: C static diverges from Python — "
        f"len(py)={len(py)} len(c)={len(cn)}"
    )


def test_c_static_header_is_7_bytes_with_nn():
    """Pin the exact fix: a 4-colour 16x16 must emit the 7-byte header AA + LLLL +
    000000 + NN with NN=4 (the pre-fix 6-byte header dropped NN)."""
    rgb = _patterned_rgb(16, 16, 4, seed=1)
    cn = _c_static_worstcase(rgb, 16, 16)
    assert cn[0] == 0xAA
    assert cn[6] == 4, "NN palette-count byte must survive at offset 6"
    assert cn[3:6] == b"\x00\x00\x00"


def test_c_frame_uniform_image_is_not_corrupted():
    """A solid (1-color) frame is the degenerate case; with the aliasing bug an
    all-zero index region could coincidentally survive, so pair it with the
    interleaved patterns above rather than relying on it alone."""
    rgb = bytes((0xAB, 0xCD, 0xEF)) * (32 * 32)
    py = bytes(py_encode_animation_frame_32(rgb, 32, 32, 1000))
    cn = bytes(image_encoder._c_encode_animation_frame_32(rgb, 32, 32, 1000))
    assert cn == py
