"""R40 §2 — media_decoder.resolve_to_gif: one resolver for every CDN container.

The custom-art page push crashed with "cannot identify image file …gif" when a
slot held an 0xAA hot file (the old branching only knew magic 43 + 9/18/26).
"""
import importlib
import struct
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))

# Evict the shim test_gallery_cache_rebuild leaks into sys.modules.
sys.modules.pop("divoom_lib.media_decoder", None)
media_decoder = importlib.import_module("divoom_lib.media_decoder")
import divoom_lib
divoom_lib.media_decoder = media_decoder

pytest.importorskip("Crypto.Cipher")
from Crypto.Cipher import AES
from PIL import Image
import io


def _gif_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (1, 2, 3)).save(buf, format="GIF")
    return buf.getvalue()


def _magic9(frames: list[bytes], speed=120) -> bytes:
    raw = b"".join(frames)
    raw += bytes((16 - len(raw) % 16) % 16)
    enc = AES.new(b"78hrey23y28ogs89", AES.MODE_CBC, b"1234567890123456").encrypt(raw)
    return bytes([9, len(frames)]) + struct.pack(">H", speed) + enc


def _magic43(img: bytes) -> bytes:
    text = b"hi"
    return (bytes([43, 0, 0, 0, 0, 0]) + struct.pack("<I", len(text)) + text
            + struct.pack("<I", len(img)) + img)


def _aa_solid(rgb=(255, 0, 0), time_ms=100) -> bytes:
    # one keyframe, palette of 1 color, no pixel map (palette size 1 → bpp 0).
    # Frame layout: 0xAA len(u16 LE) time(u16 LE) flag n_colors [palette].
    body = bytes([0, 1]) + bytes(rgb)          # flag=0 keyframe, n_colors=1, palette
    # frame_len counts the whole frame: 0xAA(1) + len(2) + time(2) + body.
    return bytes([0xAA]) + struct.pack("<H", 5 + len(body)) + struct.pack("<H", time_ms) + body


def test_plain_gif_passthrough(tmp_path):
    gif = _gif_bytes()
    assert media_decoder.resolve_to_gif(gif, tmp_path / "s.gif") == gif


def test_magic43_extracts_embedded_image(tmp_path):
    gif = _gif_bytes()
    out = media_decoder.resolve_to_gif(_magic43(gif), tmp_path / "s.gif")
    assert out == gif


def test_magic9_decodes_to_gif(tmp_path):
    payload = _magic9([bytes([0, 255, 0]) * 256])
    out = media_decoder.resolve_to_gif(payload, tmp_path / "s.gif")
    assert out is not None
    with Image.open(io.BytesIO(out)) as img:
        assert img.size == (16, 16)


def test_aa_hot_file_decodes_to_gif(tmp_path):
    """THE R40 §2 regression: 0xAA must resolve, not crash Image.open."""
    payload = _aa_solid() + _aa_solid((0, 0, 255))
    out = media_decoder.resolve_to_gif(payload, tmp_path / "s.gif")
    assert out is not None
    with Image.open(io.BytesIO(out)) as img:
        # 0xAA decoder emits an upscaled preview GIF; owner_art resizes to 16.
        assert img.n_frames == 2
    # And PIL can re-open it the way owner_art does (write → open).
    p = tmp_path / "reopen.gif"
    p.write_bytes(out)
    with Image.open(p) as img:
        img.convert("RGB").resize((16, 16))


def test_png_and_jpg_pass_through(tmp_path):
    """Raw PNG/JPG (e.g. the custom-art unit fixtures) are PIL-openable as-is."""
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 64
    assert media_decoder.resolve_to_gif(png, tmp_path / "s.gif") == png
    assert media_decoder.resolve_to_gif(jpg, tmp_path / "s.gif") == jpg


def test_unknown_payload_returns_none(tmp_path):
    assert media_decoder.resolve_to_gif(b"\x77garbagegarbage", tmp_path / "s.gif") is None
    assert media_decoder.resolve_to_gif(b"", tmp_path / "s.gif") is None
    assert media_decoder.resolve_to_gif(b"\x2b", tmp_path / "s.gif") is None
