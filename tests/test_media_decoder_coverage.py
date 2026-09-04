"""R61 coverage push: fill the gaps in divoom_lib/media_decoder.py itself.

Covers, with REAL decode math (no mocking of PIL/crypto/lzo internals):
  - extract_image_from_magic_43 / extract_gif_from_magic_43: PNG/JPG branches,
    the truncated-header short-circuit, the img_len overstate-clamp, and the
    defensive except (fault-injected via a corrupt-slice bytes subclass).
  - decode_cloud_frames magic 18/26 (LZO-compressed tiled cloud containers):
    happy path, declared-frame-count-exceeds-data, a lying frame_size prefix,
    and a genuinely corrupt LZO stream.
  - decode_cloud_to_gif / decode_and_save_preview: the animation (multi-frame)
    branch and the save-time exception branch (a directory as the out path).
  - decode_hot_file_format edge breaks: mid-stream non-0xAA garbage, starved
    palette bytes, an empty running palette on a delta frame, starved pixel
    bytes, and out-of-range palette indices.
  - decode_hot_file_to_gif: the single-frame (non save_all) branch.
  - resolve_to_gif: the "container recognized but decode failed" None paths
    for both cloud-container and hot-file magics.
  - _compact_tiles: native-lib path, pure-Python fallback (lib=None), and the
    native-call-raises-so-fall-back-to-python path — called directly so both
    branches run regardless of whether this machine has the compiled .dylib.
  - module-level native-lib loading: the "no lib found" and "lib found but
    fails to load" branches, exercised via a scoped reload of the real
    library_path() (always reloaded back to the real one afterward).

See tests/test_media_decoder_cloud.py, test_hot_file_decoder.py,
test_resolve_to_gif.py for the sibling-agent shim-eviction hazard this file
also works around: test_gallery_cache_rebuild installs a bare SHIM as
sys.modules["divoom_lib.media_decoder"] and leaks it for the rest of the
session — evict it up front so we exercise the real module.
"""
import importlib
import struct
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))

sys.modules.pop("divoom_lib.media_decoder", None)
media_decoder = importlib.import_module("divoom_lib.media_decoder")
import divoom_lib
divoom_lib.media_decoder = media_decoder

pytest.importorskip("Crypto.Cipher")
pytest.importorskip("lzallright")
from Crypto.Cipher import AES
from PIL import Image
import lzallright

_KEY = b"78hrey23y28ogs89"
_IV = b"1234567890123456"


# ── shared helpers ───────────────────────────────────────────────────────────

def _magic43(text_len_bytes: bytes, img_len_bytes: bytes, img: bytes) -> bytes:
    return bytes([43, 0, 0, 0, 0, 0]) + text_len_bytes + img_len_bytes + img


def _encrypt(plain: bytes) -> bytes:
    pad = (16 - len(plain) % 16) % 16
    return AES.new(_KEY, AES.MODE_CBC, _IV).encrypt(plain + bytes(pad))


def _magic9(frames_rgb: list[bytes], speed: int = 120) -> bytes:
    enc = _encrypt(b"".join(frames_rgb))
    return bytes([9, len(frames_rgb)]) + struct.pack(">H", speed) + enc


def _magic1826(magic: int, frame_blobs: list[bytes], *, row_count: int = 1,
               column_count: int = 1, speed: int = 100,
               total_frames: int | None = None) -> bytes:
    """Build a real magic-18/26 container: header + AES(LZO-per-frame)."""
    lzo = lzallright.LZOCompressor()
    plain = b""
    for blob in frame_blobs:
        comp = lzo.compress(blob)
        plain += struct.pack(">I", len(comp)) + comp
    enc = _encrypt(plain)
    n = total_frames if total_frames is not None else len(frame_blobs)
    header = bytes([magic]) + struct.pack(">BHBB", n, speed, row_count, column_count)
    return header + enc


def _pack_indices(indices: list[int], bpp: int) -> bytes:
    acc = 0
    for i, idx in enumerate(indices):
        acc |= idx << (i * bpp)
    n_bytes = (len(indices) * bpp + 7) // 8
    return acc.to_bytes(n_bytes, "little")


def _hot_frame(time_ms: int, flag: int, colors: list[bytes], pixels: bytes) -> bytes:
    body = bytes([flag, len(colors)]) + b"".join(colors) + pixels
    length = 7 + len(colors) * 3 + len(pixels)
    return bytes([0xAA]) + struct.pack("<HH", length, time_ms) + body


RED = b"\xff\x00\x00"
GREEN = b"\x00\xff\x00"
BLUE = b"\x00\x00\xff"


# ── extract_image_from_magic_43 / extract_gif_from_magic_43 ────────────────

class _CorruptSlice(bytes):
    """Raises when the text_len field (offset 6:10) is read — simulates a
    genuinely unexpected failure to exercise the function's defensive except,
    a path no amount of merely-malformed-but-well-typed input reaches (every
    other short-buffer case is explicitly guarded by a length check first)."""
    def __getitem__(self, item):
        if item == slice(6, 10):
            raise ValueError("simulated corruption")
        return super().__getitem__(item)


def test_magic43_rejects_when_img_len_field_is_truncated():
    # 10-byte buffer: header only, text_len=0 -> img_len_offset=10, and there
    # isn't room left for the 4-byte img_len field itself.
    data = _magic43(struct.pack("<I", 0), b"", b"")
    assert len(data) == 10
    assert media_decoder.extract_image_from_magic_43(data) is None


def test_magic43_clamps_overstated_img_len_to_buffer_end():
    gif = b"GIF89a" + bytes(10)
    overstated = struct.pack("<I", len(gif) + 500)
    data = _magic43(struct.pack("<I", 0), overstated, gif)
    res = media_decoder.extract_image_from_magic_43(data)
    assert res == (gif, ".gif")


def test_magic43_extracts_embedded_png():
    png = b"\x89PNG\r\n\x1a\n" + bytes(10)
    data = _magic43(struct.pack("<I", 0), struct.pack("<I", len(png)), png)
    assert media_decoder.extract_image_from_magic_43(data) == (png, ".png")


def test_magic43_extracts_embedded_jpg():
    jpg = b"\xff\xd8" + bytes(10)
    data = _magic43(struct.pack("<I", 0), struct.pack("<I", len(jpg)), jpg)
    assert media_decoder.extract_image_from_magic_43(data) == (jpg, ".jpg")


def test_magic43_unrecognized_embedded_format_returns_none():
    junk = b"NOTANIMAGE" + bytes(10)
    data = _magic43(struct.pack("<I", 0), struct.pack("<I", len(junk)), junk)
    assert media_decoder.extract_image_from_magic_43(data) is None


def test_magic43_except_branch_on_injected_corruption():
    corrupt = _CorruptSlice(bytes([43]) + bytes(9))
    assert len(corrupt) == 10
    assert media_decoder.extract_image_from_magic_43(corrupt) is None


def test_extract_gif_from_magic_43_returns_gif_bytes():
    gif = b"GIF89a" + bytes(10)
    data = _magic43(struct.pack("<I", 0), struct.pack("<I", len(gif)), gif)
    assert media_decoder.extract_gif_from_magic_43(data) == gif


def test_extract_gif_from_magic_43_none_when_embedded_is_not_gif():
    png = b"\x89PNG\r\n\x1a\n" + bytes(10)
    data = _magic43(struct.pack("<I", 0), struct.pack("<I", len(png)), png)
    assert media_decoder.extract_gif_from_magic_43(data) is None


def test_extract_gif_from_magic_43_none_on_unparseable_payload():
    assert media_decoder.extract_gif_from_magic_43(b"\x2bshort") is None


# ── decode_cloud_frames: magic 18/26 (LZO-tiled) ─────────────────────────────

def test_decode_cloud_frames_magic18_multi_tile_roundtrip():
    """2 frames, 1x2 tile grid (32x16 image) -> real LZO decompress + real
    tile compaction (whichever of native/pure-python _compact_tiles path this
    machine takes)."""
    tile_a = bytes([10, 20, 30]) * 256
    tile_b = bytes([40, 50, 60]) * 256
    frame0 = tile_a + tile_b
    frame1 = tile_b + tile_a
    payload = _magic1826(18, [frame0, frame1], row_count=1, column_count=2, speed=90)
    frames, speed = media_decoder.decode_cloud_frames(payload)
    assert frames is not None and len(frames) == 2
    assert speed == 90
    assert frames[0].size == (32, 16)
    assert frames[0].getpixel((0, 0)) == (10, 20, 30)
    assert frames[0].getpixel((16, 0)) == (40, 50, 60)
    assert frames[1].getpixel((0, 0)) == (40, 50, 60)


def test_decode_cloud_frames_magic26_single_tile():
    tile = bytes([1, 2, 3]) * 256
    payload = _magic1826(26, [tile], row_count=1, column_count=1)
    frames, speed = media_decoder.decode_cloud_frames(payload)
    assert frames is not None and len(frames) == 1
    assert frames[0].size == (16, 16)
    assert frames[0].getpixel((5, 5)) == (1, 2, 3)


def test_decode_cloud_frames_1826_declared_count_exceeds_data():
    """total_frames says 2 but only 1 frame's worth of bytes exist -> the
    second iteration breaks on the starved 4-byte frame_size header."""
    tile = bytes([9, 9, 9]) * 256
    payload = _magic1826(18, [tile], row_count=1, column_count=1,
                         total_frames=2)
    frames, _ = media_decoder.decode_cloud_frames(payload)
    assert frames is not None and len(frames) == 1


def test_decode_cloud_frames_1826_lying_frame_size_breaks():
    """frame_size prefix claims far more bytes than are actually present."""
    lzo = lzallright.LZOCompressor()
    comp = lzo.compress(bytes([1, 2, 3]) * 256)
    plain = struct.pack(">I", 99999) + comp  # lies about its own length
    enc = _encrypt(plain)
    header = bytes([18]) + struct.pack(">BHBB", 1, 100, 1, 1)
    frames, _ = media_decoder.decode_cloud_frames(header + enc)
    assert frames is None


def test_decode_cloud_frames_1826_corrupt_lzo_stream_returns_none():
    """frame_size is honest but the payload isn't valid LZO data at all."""
    garbage = b"not-a-valid-lzo-stream-at-all-x"
    plain = struct.pack(">I", len(garbage)) + garbage
    enc = _encrypt(plain)
    header = bytes([18]) + struct.pack(">BHBB", 1, 100, 1, 1)
    frames, _ = media_decoder.decode_cloud_frames(header + enc)
    assert frames is None


# ── decode_cloud_to_gif / decode_and_save_preview: animation + except ───────

def test_decode_cloud_to_gif_raises_inside_save_degrades_to_false(tmp_path):
    """A directory (no file extension) as out_path makes PIL's save() raise;
    the function must degrade to False, not propagate."""
    payload = _magic9([bytes([1, 2, 3]) * 256])
    assert media_decoder.decode_cloud_to_gif(payload, tmp_path) is False


def test_decode_and_save_preview_multi_frame_writes_animated_gif(tmp_path):
    payload = _magic9([bytes([1, 2, 3]) * 256, bytes([4, 5, 6]) * 256])
    png_out = tmp_path / "prev.png"
    assert media_decoder.decode_and_save_preview(payload, png_out) is True
    gif_out = png_out.with_suffix(".gif")
    assert gif_out.exists()
    with Image.open(gif_out) as img:
        assert img.n_frames == 2
    with Image.open(png_out) as img:
        assert img.size == (128, 128)


def test_decode_and_save_preview_raises_inside_save_degrades_to_false(tmp_path):
    payload = _magic9([bytes([1, 2, 3]) * 256])
    assert media_decoder.decode_and_save_preview(payload, tmp_path) is False


# ── decode_hot_file_format: the remaining break/return branches ─────────────

def test_hot_file_midstream_garbage_keeps_earlier_frames():
    good = _hot_frame(100, 0, [RED], b"")
    # 8 bytes, first byte isn't 0xAA -> the while-loop's mid-stream guard
    # breaks (distinct from a too-short/truncated *declared* frame).
    junk = bytes([0x00, 1, 2, 3, 4, 5, 6, 7])
    frames = media_decoder.decode_hot_file_format(good + junk)
    assert frames is not None and len(frames) == 1


def test_hot_file_starved_palette_bytes_breaks():
    # frame_len covers only the 7-byte header; n_colors=5 claims 15 palette
    # bytes that were never actually written.
    raw = bytes([0xAA]) + struct.pack("<HH", 7, 100) + bytes([0, 5])
    assert media_decoder.decode_hot_file_format(raw) is None


def test_hot_file_delta_frame_with_no_prior_palette_breaks():
    # First frame in the file is a delta (flag=1) contributing zero colors;
    # the running palette was never seeded, so it stays empty -> break.
    raw = _hot_frame(100, 1, [], b"")
    assert media_decoder.decode_hot_file_format(raw) is None


def test_hot_file_starved_pixel_bytes_breaks():
    # 2-color palette -> 1bpp -> needs 32 bytes of packed pixel data; only 10
    # are actually present.
    partial = bytes(10)
    body = bytes([0, 2]) + RED + GREEN + partial
    length = 7 + 2 * 3 + len(partial)
    raw = bytes([0xAA]) + struct.pack("<HH", length, 100) + body
    assert media_decoder.decode_hot_file_format(raw) is None


def test_hot_file_out_of_range_palette_index_returns_none():
    # 3-color palette -> 2bpp (max representable index 3); every pixel
    # points at index 3, one past the last valid palette entry (2).
    bad_indices = _pack_indices([3] * 256, 2)
    raw = _hot_frame(100, 0, [RED, GREEN, BLUE], bad_indices)
    assert media_decoder.decode_hot_file_format(raw) is None


def test_decode_hot_file_to_gif_single_frame_uses_non_animated_save(tmp_path):
    raw = _hot_frame(100, 0, [RED], b"")
    out = tmp_path / "single.gif"
    assert media_decoder.decode_hot_file_to_gif(raw, out) is True
    with Image.open(out) as img:
        assert getattr(img, "n_frames", 1) == 1
        assert img.size == (128, 128)


# ── resolve_to_gif: recognized-but-undecodable containers ──────────────────

def test_resolve_to_gif_none_when_cloud_container_fails_to_decode(tmp_path):
    # magic 9, but the "encrypted" tail isn't a multiple of the AES block
    # size -> decode_cloud_to_gif fails -> resolve_to_gif must return None.
    bad = bytes([9, 1, 0, 100]) + b"not-16-byte-aligned-x"
    assert media_decoder.resolve_to_gif(bad, tmp_path / "s.gif") is None


def test_resolve_to_gif_none_when_hot_file_fails_to_decode(tmp_path):
    # magic 0xAA but far too short for decode_hot_file_format to accept.
    bad = bytes([0xAA, 0, 0, 0, 0])
    assert media_decoder.resolve_to_gif(bad, tmp_path / "s.gif") is None


# ── _compact_tiles: native / pure-python / native-raises-so-fallback ────────

def test_compact_tiles_native_and_python_fallback_agree(monkeypatch):
    """Whatever this machine's default (lib present or not), directly force
    both the native-call path and the pure-Python fallback and check they
    produce identical pixel data."""
    tile_a = bytes([10, 20, 30]) * 256
    tile_b = bytes([40, 50, 60]) * 256
    blob = tile_a + tile_b  # row_count=1, column_count=2

    native_result = media_decoder._compact_tiles(blob, 1, 2)

    monkeypatch.setattr(media_decoder, "lib", None)
    fallback_result = media_decoder._compact_tiles(blob, 1, 2)

    assert native_result.size == fallback_result.size == (32, 16)
    assert list(native_result.getdata()) == list(fallback_result.getdata())
    assert fallback_result.getpixel((0, 0)) == (10, 20, 30)
    assert fallback_result.getpixel((16, 0)) == (40, 50, 60)


def test_compact_tiles_falls_back_when_native_call_raises(monkeypatch):
    class _ExplodingLib:
        def compact_tiles(self, *a, **k):
            raise RuntimeError("simulated native failure")

    tile = bytes([7, 8, 9]) * 256
    monkeypatch.setattr(media_decoder, "lib", _ExplodingLib())
    img = media_decoder._compact_tiles(tile, 1, 1)
    assert img.size == (16, 16)
    assert img.getpixel((0, 0)) == (7, 8, 9)


# ── module-level native-lib loading branches ────────────────────────────────

@pytest.fixture
def reload_with_fake_library_path():
    """Reload divoom_lib.media_decoder with native_lib.library_path patched,
    always reloading back to the REAL library_path afterward so we never
    leave a stubbed/broken module for other tests in this session (this
    module is a shared singleton across many test files).

    Guards against the documented cross-file shim-eviction hazard: a sibling
    test file's own evict-and-reimport (test_media_decoder_cloud.py,
    test_hot_file_decoder.py, test_resolve_to_gif.py all do this) may have
    replaced sys.modules["divoom_lib.media_decoder"] with a DIFFERENT module
    object after we captured ours at collection time. importlib.reload()
    requires identity with the currently-registered module, so re-register
    ours immediately before every reload call rather than trusting whatever
    is currently in sys.modules.
    """
    import divoom_lib.native_lib as native_lib
    orig = native_lib.library_path

    def _apply(fake_path):
        sys.modules["divoom_lib.media_decoder"] = media_decoder
        native_lib.library_path = lambda: fake_path
        importlib.reload(media_decoder)

    yield _apply

    native_lib.library_path = orig
    sys.modules["divoom_lib.media_decoder"] = media_decoder
    importlib.reload(media_decoder)


def test_module_load_skips_native_lib_when_path_missing(
        tmp_path, reload_with_fake_library_path):
    reload_with_fake_library_path(tmp_path / "does-not-exist.dylib")
    assert media_decoder.lib is None


def test_module_load_falls_back_when_native_lib_invalid(
        tmp_path, reload_with_fake_library_path):
    bad_lib = tmp_path / "bad.dylib"
    bad_lib.write_bytes(b"not a real mach-o/elf body")
    reload_with_fake_library_path(bad_lib)
    assert media_decoder.lib is None
