"""Anti-drift correctness suite: run the SAME encoder tests against BOTH the
pure-Python encoder and the native C encoder.

Why this exists: the earlier native parity test only asserted ``C == Python``.
When the byte-spanning bit-packing bug existed in *both* implementations they
agreed, so the bug shipped. These tests instead assert **correctness** (the
encoded frame decodes back to the original image) and run independently on each
implementation — a bug present in both still fails here.

Both implementations must pass every case. The C parametrization skips when the
dylib isn't built; CI must build it so the C side actually runs.
"""
import math
from types import SimpleNamespace

import pytest

from divoom_lib.utils import divoom_image_encode as py
from divoom_lib.native import image_encoder as c


# ── implementation matrix ───────────────────────────────────────────────
_IMPLS = {
    "python": SimpleNamespace(
        frame=py.encode_animation_frame,
        static=py.encode_static_image,
        multiframe=py._py_encode_animation,
    ),
    "c": SimpleNamespace(
        frame=c.encode_animation_frame,
        static=c.encode_static_image,
        multiframe=c.encode_animation,
    ),
}


@pytest.fixture(params=["python", "c"])
def impl(request):
    if request.param == "c" and not c.is_native_available():
        pytest.skip("native dylib not built — run scripts/build_libdivoom.sh")
    return _IMPLS[request.param]


# ── helpers ─────────────────────────────────────────────────────────────
def _make_image(w: int, h: int, num_colors: int) -> tuple[bytes, list]:
    """Build a w*h RGB image using exactly `num_colors` distinct colors, every
    one of which appears. Returns (rgb_bytes, list_of_pixel_colors)."""
    assert num_colors <= w * h
    palette = [((i * 7) & 0xFF, (i * 13 + 3) & 0xFF, (i * 29 + 7) & 0xFF)
               for i in range(num_colors)]
    # de-dup defensively (the arithmetic above is distinct for num_colors<=256)
    assert len(set(palette)) == num_colors, "test palette not distinct"
    pixels = [palette[i % num_colors] for i in range(w * h)]
    rgb = bytes(b for px in pixels for b in px)
    return rgb, pixels


def _decode_pixels_lsb(data: bytes, nb_bits: int, count: int) -> list[int]:
    out, acc, acc_bits, pos, mask = [], 0, 0, 0, (1 << nb_bits) - 1
    for _ in range(count):
        while acc_bits < nb_bits:
            acc |= data[pos] << acc_bits
            acc_bits += 8
            pos += 1
        out.append(acc & mask)
        acc >>= nb_bits
        acc_bits -= nb_bits
    return out


def _decode_frame_body(body: bytes, w: int, h: int, *, animated: bool) -> list:
    """Decode one encoded frame/static body back into a list of pixel colors."""
    assert body[0] == 0xAA, "missing 0xAA start marker"
    llll = body[1] | (body[2] << 8)
    # LLLL counts the whole body INCLUDING the AA + the 2 LLLL bytes.
    assert llll == len(body), f"LLLL {llll} != body len {len(body)}"
    nn = body[6]
    num_colors = 256 if nn == 0 else nn
    nb_bits = max(1, math.ceil(math.log2(num_colors))) if num_colors else 1
    pal_start = 7
    pal_end = pal_start + 3 * num_colors
    palette = [tuple(body[i:i + 3]) for i in range(pal_start, pal_end, 3)]
    idxs = _decode_pixels_lsb(body[pal_end:], nb_bits, w * h)
    return [palette[i] for i in idxs]


# nb_bits boundaries: 1,1,2,3,4,5,6,7,8,8
_COLOR_COUNTS = [1, 2, 4, 5, 16, 17, 43, 100, 200, 256]


@pytest.mark.parametrize("num_colors", _COLOR_COUNTS)
def test_animation_frame_round_trip(impl, num_colors):
    """An encoded animation frame decodes back to the original image — on BOTH
    implementations, for every bit-width (the byte-spanning widths 3/5/6/7 are
    the ones the old shared bug corrupted)."""
    w = h = 16
    rgb, pixels = _make_image(w, h, num_colors)
    body = impl.frame(rgb, w, h, 1000)
    decoded = _decode_frame_body(body, w, h, animated=True)
    assert decoded == pixels, f"round-trip mismatch at {num_colors} colors"
    # time field (TTTT, LE u16) at [3:5]
    assert body[3] | (body[4] << 8) == 1000


@pytest.mark.parametrize("num_colors", _COLOR_COUNTS)
def test_static_image_round_trip(impl, num_colors):
    w = h = 16
    rgb, pixels = _make_image(w, h, num_colors)
    body = impl.static(rgb, w, h)
    decoded = _decode_frame_body(body, w, h, animated=False)
    assert decoded == pixels, f"static round-trip mismatch at {num_colors} colors"


def test_256_colors_uses_nn_zero(impl):
    """256 colors is encoded as NN=0 on both impls."""
    rgb, _ = _make_image(16, 16, 256)
    assert impl.frame(rgb, 16, 16, 100)[6] == 0
    assert impl.static(rgb, 16, 16)[6] == 0


@pytest.mark.parametrize("num_colors", [2, 6, 43, 100, 256])
def test_multiframe_round_trips(impl, num_colors):
    """A 3-frame animation: every frame body round-trips on both impls."""
    w = h = 16
    rgb, pixels = _make_image(w, h, num_colors)
    frames = [(rgb, w, h, 100), (rgb, w, h, 200), (rgb, w, h, 300)]
    packets = impl.multiframe(frames)
    # reassemble the frame blob from the 0x49 packets: [len LE u16][pkt# u8][chunk]
    blob = b"".join(bytes(p[3:]) for p in packets)
    # walk the concatenated AA-frames
    off = 0
    seen = 0
    while off < len(blob):
        assert blob[off] == 0xAA
        llll = blob[off + 1] | (blob[off + 2] << 8)  # full body length incl. AA
        body = blob[off:off + llll]
        assert _decode_frame_body(body, w, h, animated=True) == pixels
        off += llll
        seen += 1
    assert seen == 3
