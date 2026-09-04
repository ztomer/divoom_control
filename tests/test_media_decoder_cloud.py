"""R36 — cloud-container decode for the SEND path.

The hot-channel bug: magic 9/18/26 downloads are app-side AES-CBC ciphertext.
Raw-streaming them over 0x8B "succeeds" (every chunk ACKed) but the device
renders nothing. The APK decodes + re-encodes; so must we. These tests build a
synthetic magic-9 container with the published key/IV — no user cache data.
"""
import importlib
import struct
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))

# test_gallery_cache_rebuild installs a bare SHIM as
# sys.modules["divoom_lib.media_decoder"] (to dodge heavy imports) and leaks it
# for the rest of the session — evict it so we test the real module.
sys.modules.pop("divoom_lib.media_decoder", None)
media_decoder = importlib.import_module("divoom_lib.media_decoder")
import divoom_lib
divoom_lib.media_decoder = media_decoder

pytest.importorskip("Crypto.Cipher")
from Crypto.Cipher import AES
from PIL import Image


def _make_magic9(frames_rgb: list[bytes], speed: int = 150) -> bytes:
    """Build a magic-9 container the way the cloud does: header + AES-CBC."""
    raw = b"".join(frames_rgb)
    pad = (16 - len(raw) % 16) % 16
    raw += bytes(pad)
    enc = AES.new(b"78hrey23y28ogs89", AES.MODE_CBC,
                  b"1234567890123456").encrypt(raw)
    return bytes([9, len(frames_rgb)]) + struct.pack(">H", speed) + enc


def _solid_frame(r, g, b) -> bytes:
    return bytes([r, g, b]) * 256  # 16*16 RGB


def test_decode_cloud_frames_magic9_roundtrip():
    payload = _make_magic9([_solid_frame(255, 0, 0), _solid_frame(0, 255, 0)])
    frames, duration = media_decoder.decode_cloud_frames(payload)
    assert frames is not None and len(frames) == 2
    assert duration == 150
    assert frames[0].size == (16, 16)          # NATIVE size, not 128 preview
    assert frames[0].getpixel((0, 0)) == (255, 0, 0)
    assert frames[1].getpixel((8, 8)) == (0, 255, 0)


def test_decode_cloud_to_gif_writes_native_animation(tmp_path):
    payload = _make_magic9([_solid_frame(0, 0, 255), _solid_frame(255, 255, 0)])
    out = tmp_path / "decoded.gif"
    assert media_decoder.decode_cloud_to_gif(payload, out) is True
    with Image.open(out) as img:
        assert img.size == (16, 16)
        assert img.n_frames == 2


def test_decode_cloud_frames_rejects_non_container():
    assert media_decoder.decode_cloud_frames(b"GIF89a junk") == (None, 0)
    assert media_decoder.decode_cloud_frames(b"") == (None, 0)
    assert media_decoder.decode_cloud_to_gif(b"\x2bnope", Path("/tmp/x.gif")) is False


def test_cloud_magics_constant_covers_known_containers():
    assert set(media_decoder.CLOUD_CONTAINER_MAGICS) == {8, 9, 12, 18, 26}


def test_preview_wrapper_still_upscales(tmp_path):
    """decode_and_save_preview keeps its 128x128 preview contract."""
    payload = _make_magic9([_solid_frame(10, 20, 30)])
    png = tmp_path / "prev.png"
    assert media_decoder.decode_and_save_preview(payload, png) is True
    with Image.open(png) as img:
        assert img.size == (128, 128)


# R64 — magic 8 (static AES image) and magic 12 (scroll/marquee AES).
# Recorded live from the real Divoom CDN (no network in tests).
FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_magic8_static_aes_decodes():
    raw = (FIXTURE_DIR / "gallery_magic8.bin").read_bytes()
    assert raw[0] == 8
    frames, duration = media_decoder.decode_cloud_frames(raw)
    assert frames is not None and len(frames) == 1
    assert frames[0].size == (16, 16)
    assert duration == 100
    # Not a blank frame.
    extrema = frames[0].convert("RGB").getextrema()
    assert any(lo != hi for lo, hi in extrema)


def test_magic12_scroll_aes_decodes():
    raw = (FIXTURE_DIR / "gallery_magic12.bin").read_bytes()
    assert raw[0] == 12
    frames, duration = media_decoder.decode_cloud_frames(raw)
    assert frames is not None and len(frames) == 1
    # 3072-byte scroll buffer -> 64x16 RGB.
    assert frames[0].size == (64, 16)
    assert duration == 100
    extrema = frames[0].convert("RGB").getextrema()
    assert any(lo != hi for lo, hi in extrema)


def test_decode_and_save_preview_handles_magic8_and_12(tmp_path):
    for magic, fname in [(8, "gallery_magic8.bin"), (12, "gallery_magic12.bin")]:
        raw = (FIXTURE_DIR / fname).read_bytes()
        assert raw[0] == magic
        out = tmp_path / f"prev_{magic}.png"
        assert media_decoder.decode_and_save_preview(raw, out) is True
        assert out.exists()
        assert media_decoder.is_black_image(out) is False


def test_is_black_image(tmp_path):
    # A solid-black image is valid dark ART, not a broken preview.
    black = tmp_path / "black.png"
    Image.new("RGB", (16, 16), (0, 0, 0)).save(black)
    assert media_decoder.is_black_image(black) is False
    # An all-transparent PNG -> nothing drawn -> broken/blank.
    trans = tmp_path / "trans.png"
    Image.new("RGBA", (16, 16), (0, 0, 0, 0)).save(trans)
    assert media_decoder.is_black_image(trans) is True
    # A 0-byte / unreadable file -> broken.
    (tmp_path / "empty.png").write_bytes(b"")
    assert media_decoder.is_black_image(tmp_path / "empty.png") is True
    assert media_decoder.is_black_image(tmp_path / "nope.png") is True
