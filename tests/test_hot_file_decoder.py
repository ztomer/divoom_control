"""Tests for the hot channel (magic 0xAA) file decoder.

Format (empirically verified against 6 live CDN hot files, 2026-06-09):
each frame is ``0xAA len(u16 LE) time_ms(u16 LE) flag n_colors [palette]
[pixels]``. ``flag`` 0 resets the running palette, ``flag`` 1 appends new
colors (delta frame). Pixels are 256 indices into the cumulative palette,
packed LSB-first at ``ceil(log2(palette_size))`` bits per pixel, omitted
while the palette has a single color.
"""

import importlib
import struct
import sys

# test_gallery_cache_rebuild installs a bare SHIM as
# sys.modules["divoom_lib.media_decoder"] and leaks it for the rest of the
# session — evict it so we test the real module (same as test_media_decoder_cloud).
sys.modules.pop("divoom_lib.media_decoder", None)
media_decoder = importlib.import_module("divoom_lib.media_decoder")
import divoom_lib

divoom_lib.media_decoder = media_decoder


def _pack_indices(indices: list[int], bpp: int) -> bytes:
    acc = 0
    for i, idx in enumerate(indices):
        acc |= idx << (i * bpp)
    n_bytes = (len(indices) * bpp + 7) // 8
    return acc.to_bytes(n_bytes, "little")


def _frame(time_ms: int, flag: int, colors: list[bytes], pixels: bytes) -> bytes:
    body = bytes([flag, len(colors)]) + b"".join(colors) + pixels
    length = 7 + len(colors) * 3 + len(pixels)
    return bytes([0xAA]) + struct.pack("<HH", length, time_ms) + body


RED = b"\xff\x00\x00"
GREEN = b"\x00\xff\x00"
BLUE = b"\x00\x00\xff"


def test_solid_color_keyframe_has_no_pixel_data():
    # 1-color palette -> 0 bpp -> pixel map omitted entirely
    raw = _frame(200, 0, [RED], b"")
    frames = media_decoder.decode_hot_file_format(raw)
    assert frames is not None and len(frames) == 1
    rgb, duration = frames[0]
    assert rgb == RED * 256
    assert duration == 200


def test_keyframe_with_two_colors_1bpp_lsb_first():
    indices = [0, 1] * 128  # alternating
    raw = _frame(100, 0, [RED, GREEN], _pack_indices(indices, 1))
    frames = media_decoder.decode_hot_file_format(raw)
    assert frames is not None and len(frames) == 1
    rgb, _ = frames[0]
    assert rgb[:3] == RED and rgb[3:6] == GREEN
    assert rgb == (RED + GREEN) * 128


def test_delta_frame_appends_to_running_palette():
    key = _frame(100, 0, [RED, GREEN], _pack_indices([0] * 256, 1))
    # delta adds BLUE -> palette size 3 -> 2 bpp, full repaint with index 2
    delta = _frame(150, 1, [BLUE], _pack_indices([2] * 256, 2))
    frames = media_decoder.decode_hot_file_format(key + delta)
    assert frames is not None and len(frames) == 2
    assert frames[0][0] == RED * 256
    assert frames[1][0] == BLUE * 256
    assert frames[1][1] == 150


def test_delta_frame_with_no_new_colors():
    key = _frame(100, 0, [RED, GREEN], _pack_indices([0] * 256, 1))
    delta = _frame(100, 1, [], _pack_indices([1] * 256, 1))
    frames = media_decoder.decode_hot_file_format(key + delta)
    assert frames is not None and len(frames) == 2
    assert frames[1][0] == GREEN * 256


def test_keyframe_resets_palette():
    f1 = _frame(100, 0, [RED, GREEN], _pack_indices([1] * 256, 1))
    f2 = _frame(100, 0, [BLUE], b"")  # new animation: palette reset to 1 color
    frames = media_decoder.decode_hot_file_format(f1 + f2)
    assert frames is not None and len(frames) == 2
    assert frames[0][0] == GREEN * 256
    assert frames[1][0] == BLUE * 256


def test_zero_duration_defaults_to_100ms():
    raw = _frame(0, 0, [RED], b"")
    frames = media_decoder.decode_hot_file_format(raw)
    assert frames is not None
    assert frames[0][1] == 100


def test_max_frames_caps_output():
    raw = b"".join(_frame(100, 0, [RED], b"") for _ in range(10))
    frames = media_decoder.decode_hot_file_format(raw, max_frames=4)
    assert frames is not None and len(frames) == 4


def test_rejects_non_hot_payloads():
    assert media_decoder.decode_hot_file_format(b"") is None
    assert media_decoder.decode_hot_file_format(b"\x09\x2a\x00") is None
    assert media_decoder.decode_hot_file_format(b"GIF89a") is None
    # truncated header
    assert media_decoder.decode_hot_file_format(b"\xaa\x05") is None


def test_truncated_frame_is_dropped_but_earlier_frames_kept():
    good = _frame(100, 0, [RED], b"")
    truncated = _frame(100, 0, [RED, GREEN], _pack_indices([0] * 256, 1))[:-10]
    frames = media_decoder.decode_hot_file_format(good + truncated)
    assert frames is not None and len(frames) == 1


def test_decode_hot_file_to_gif(tmp_path):
    key = _frame(100, 0, [RED, GREEN], _pack_indices([0, 1] * 128, 1))
    delta = _frame(150, 1, [BLUE], _pack_indices([2] * 256, 2))
    out = tmp_path / "preview.gif"
    assert media_decoder.decode_hot_file_to_gif(key + delta, out) is True
    from PIL import Image
    img = Image.open(out)
    assert img.size == (128, 128)
    assert getattr(img, "n_frames", 1) == 2


def test_decode_hot_file_to_gif_rejects_garbage(tmp_path):
    out = tmp_path / "preview.gif"
    assert media_decoder.decode_hot_file_to_gif(b"\x00\x01\x02", out) is False
    assert not out.exists()
