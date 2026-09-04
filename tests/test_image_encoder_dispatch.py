"""Coverage for the Python-side dispatch/fallback logic in
``divoom_lib.native.image_encoder`` (R61 coverage push).

The sibling parity suites (``test_native_image_encoder.py``,
``test_native_encoder_c_path.py``) drive the REAL dylib and assert
byte-parity. They never exercise the wrapper's own branches: dylib-missing,
dylib-load-failure, a native call returning an error code, a native call
raising, or a mid-pipeline native failure falling back to the pure-Python
path. Those branches only fire when the native boundary itself misbehaves,
so this suite mocks that boundary directly (``_load_lib`` / the internal
``_c_*`` helpers) rather than depending on a real dylib bug.

Every test resets the module's lazy-load cache before and after itself so
this file can't leave the real dylib "poisoned" for the parity suites that
run in the same session.
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from divoom_lib.native import image_encoder


@pytest.fixture(autouse=True)
def _reset_lib_cache():
    image_encoder.reset_for_tests()
    yield
    image_encoder.reset_for_tests()


# ── _load_lib() ──────────────────────────────────────────────────────────


def test_load_lib_dylib_missing_logs_and_caches(monkeypatch):
    monkeypatch.setattr(image_encoder, "_DYLIB_PATH", Path("/nonexistent/nope.dylib"))
    assert image_encoder._load_lib() is None
    assert "dylib not found" in image_encoder._lib_load_error
    # Second call must hit the cached-error early-return, not re-check the path.
    calls = {"n": 0}
    real_exists = Path.exists

    def counting_exists(self):
        calls["n"] += 1
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", counting_exists)
    assert image_encoder._load_lib() is None
    assert calls["n"] == 0


def test_load_lib_cdll_oserror_falls_back(monkeypatch, tmp_path):
    fake_path = tmp_path / "fake.dylib"
    fake_path.write_bytes(b"not a real dylib")
    monkeypatch.setattr(image_encoder, "_DYLIB_PATH", fake_path)
    monkeypatch.setattr(
        image_encoder.ctypes, "CDLL",
        MagicMock(side_effect=OSError("bad magic")),
    )
    assert image_encoder._load_lib() is None
    assert "failed to load" in image_encoder._lib_load_error


def test_is_native_available_false_when_lib_missing(monkeypatch):
    monkeypatch.setattr(image_encoder, "_DYLIB_PATH", Path("/nonexistent/nope.dylib"))
    assert image_encoder.is_native_available() is False


def test_reset_for_tests_clears_cache():
    image_encoder._lib = object()
    image_encoder._lib_load_error = "boom"
    image_encoder.reset_for_tests()
    assert image_encoder._lib is None
    assert image_encoder._lib_load_error is None


# ── _c_encode_* helpers: lib-None / rc<0 / exception ──────────────────────

_RGB_2x2 = bytes([10, 20, 30]) * 4


@pytest.mark.parametrize("helper,args", [
    ("_c_encode_animation_frame", (_RGB_2x2, 2, 2, 100)),
    ("_c_encode_animation_packets", (b"\x01\x02\x03",)),
    ("_c_encode_static_image", (_RGB_2x2, 2, 2)),
    ("_c_encode_animation_frame_32", (bytes([1, 2, 3]) * (32 * 32), 32, 32, 5)),
    ("_c_write_pre_frame_1", ()),
    ("_c_write_pre_frame_2", ()),
    ("_c_encode_animation_8b", (b"\x01" * 300,)),
])
def test_c_helper_returns_none_when_lib_unavailable(monkeypatch, helper, args):
    monkeypatch.setattr(image_encoder, "_load_lib", lambda: None)
    fn = getattr(image_encoder, helper)
    assert fn(*args) is None


def _fake_lib_with(method_name, **attrs):
    lib = MagicMock()
    method = getattr(lib, method_name)
    for k, v in attrs.items():
        setattr(method, k, v)
    return lib


@pytest.mark.parametrize("helper,c_func,args", [
    ("_c_encode_animation_frame", "divoom_encode_animation_frame", (_RGB_2x2, 2, 2, 100)),
    ("_c_encode_animation_packets", "divoom_encode_animation_packets", (b"\x01\x02\x03",)),
    ("_c_encode_static_image", "divoom_encode_static_image", (_RGB_2x2, 2, 2)),
    ("_c_encode_animation_frame_32", "divoom_encode_animation_frame_32",
     (bytes([1, 2, 3]) * (32 * 32), 32, 32, 5)),
    ("_c_write_pre_frame_1", "divoom_write_pre_frame_1", ()),
    ("_c_write_pre_frame_2", "divoom_write_pre_frame_2", ()),
    ("_c_encode_animation_8b", "divoom_encode_animation_8b", (b"\x01" * 300,)),
])
def test_c_helper_returns_none_on_negative_rc(monkeypatch, helper, c_func, args):
    fake_lib = _fake_lib_with(c_func, return_value=-1)
    getattr(fake_lib, c_func).return_value = -1
    monkeypatch.setattr(image_encoder, "_load_lib", lambda: fake_lib)
    fn = getattr(image_encoder, helper)
    assert fn(*args) is None


@pytest.mark.parametrize("helper,c_func,args", [
    ("_c_encode_animation_frame", "divoom_encode_animation_frame", (_RGB_2x2, 2, 2, 100)),
    ("_c_encode_animation_packets", "divoom_encode_animation_packets", (b"\x01\x02\x03",)),
    ("_c_encode_static_image", "divoom_encode_static_image", (_RGB_2x2, 2, 2)),
    ("_c_encode_animation_frame_32", "divoom_encode_animation_frame_32",
     (bytes([1, 2, 3]) * (32 * 32), 32, 32, 5)),
    ("_c_write_pre_frame_1", "divoom_write_pre_frame_1", ()),
    ("_c_write_pre_frame_2", "divoom_write_pre_frame_2", ()),
    ("_c_encode_animation_8b", "divoom_encode_animation_8b", (b"\x01" * 300,)),
])
def test_c_helper_returns_none_when_native_call_raises(monkeypatch, helper, c_func, args):
    fake_lib = MagicMock()
    getattr(fake_lib, c_func).side_effect = RuntimeError("native call blew up")
    monkeypatch.setattr(image_encoder, "_load_lib", lambda: fake_lib)
    fn = getattr(image_encoder, helper)
    assert fn(*args) is None


def test_c_encode_animation_8b_empty_blob_returns_none(monkeypatch):
    fake_lib = MagicMock()
    monkeypatch.setattr(image_encoder, "_load_lib", lambda: fake_lib)
    assert image_encoder._c_encode_animation_8b(b"") is None


def test_c_encode_animation_frame_32_wrong_size_returns_none(monkeypatch):
    fake_lib = MagicMock()
    monkeypatch.setattr(image_encoder, "_load_lib", lambda: fake_lib)
    # Not 32x32 -> immediate None, no native call attempted.
    assert image_encoder._c_encode_animation_frame_32(_RGB_2x2, 2, 2, 0) is None
    fake_lib.divoom_encode_animation_frame_32.assert_not_called()


# ── public wrapper dispatch: native failure falls back to Python ─────────


def test_encode_animation_frame_falls_back_to_python(monkeypatch):
    monkeypatch.setattr(image_encoder, "_c_encode_animation_frame", lambda *a, **k: None)
    result = image_encoder.encode_animation_frame(_RGB_2x2, 2, 2, 100)
    expected = image_encoder._py_encode_animation_frame(_RGB_2x2, 2, 2, 100)
    assert result == expected


def test_encode_static_image_falls_back_to_python(monkeypatch):
    monkeypatch.setattr(image_encoder, "_c_encode_static_image", lambda *a, **k: None)
    result = image_encoder.encode_static_image(_RGB_2x2, 2, 2)
    expected = image_encoder._py_encode_static_image(_RGB_2x2, 2, 2)
    assert result == expected


def test_encode_animation_frame_32_falls_back_to_python(monkeypatch):
    monkeypatch.setattr(image_encoder, "_c_encode_animation_frame_32", lambda *a, **k: None)
    rgb = bytes([4, 5, 6]) * (32 * 32)
    result = image_encoder.encode_animation_frame_32(rgb, 32, 32, 50)
    expected = image_encoder._py_encode_animation_frame_32(rgb, 32, 32, 50)
    assert result == expected


def test_pre_frames_32_p1_none_falls_back_to_python(monkeypatch):
    monkeypatch.setattr(image_encoder, "_c_write_pre_frame_1", lambda: None)
    assert image_encoder.pre_frames_32() == image_encoder._py_pre_frames_32()


def test_pre_frames_32_p2_none_falls_back_to_python(monkeypatch):
    monkeypatch.setattr(image_encoder, "_c_write_pre_frame_1", lambda: b"P1")
    monkeypatch.setattr(image_encoder, "_c_write_pre_frame_2", lambda: None)
    assert image_encoder.pre_frames_32() == image_encoder._py_pre_frames_32()


def test_pre_frames_32_both_native_ok(monkeypatch):
    monkeypatch.setattr(image_encoder, "_c_write_pre_frame_1", lambda: b"P1")
    monkeypatch.setattr(image_encoder, "_c_write_pre_frame_2", lambda: b"P2")
    assert image_encoder.pre_frames_32() == [b"P1", b"P2"]


# ── encode_animation(): multi-step native pipeline fallbacks ──────────────


def test_encode_animation_empty_frames():
    assert image_encoder.encode_animation([]) == []


def test_encode_animation_lib_unavailable_falls_back(monkeypatch):
    monkeypatch.setattr(image_encoder, "_load_lib", lambda: None)
    frames = [(_RGB_2x2, 2, 2, 10)]
    assert image_encoder.encode_animation(frames) == image_encoder._py_encode_animation(frames)


def test_encode_animation_frame_fails_mid_loop_falls_back_fully(monkeypatch):
    """Frame 2 of 2 fails native encoding -> the WHOLE animation (not just
    that frame) must fall back to the pure-Python path, for byte parity."""
    monkeypatch.setattr(image_encoder, "_load_lib", lambda: MagicMock())
    calls = {"n": 0}

    def fake_c_frame(rgb, w, h, t):
        calls["n"] += 1
        return b"native-bytes" if calls["n"] == 1 else None

    monkeypatch.setattr(image_encoder, "_c_encode_animation_frame", fake_c_frame)
    frames = [(_RGB_2x2, 2, 2, 10), (bytes([1, 1, 1]) * 4, 2, 2, 20)]
    result = image_encoder.encode_animation(frames)
    assert result == image_encoder._py_encode_animation(frames)


def test_encode_animation_packetizer_fails_falls_back_fully(monkeypatch):
    monkeypatch.setattr(image_encoder, "_load_lib", lambda: MagicMock())
    monkeypatch.setattr(image_encoder, "_c_encode_animation_frame",
                         lambda rgb, w, h, t: b"X" * 10)
    monkeypatch.setattr(image_encoder, "_c_encode_animation_packets", lambda blob: None)
    frames = [(_RGB_2x2, 2, 2, 10)]
    result = image_encoder.encode_animation(frames)
    assert result == image_encoder._py_encode_animation(frames)


# ── encode_animation_8b_phases(): per-frame + packetizer fallback ─────────


def test_encode_animation_8b_phases_empty():
    assert image_encoder.encode_animation_8b_phases([]) == []


def test_encode_animation_8b_phases_falls_back_per_frame_and_packetizer(monkeypatch):
    """Force every frame's native path (both the 32x32 and generic encoders)
    to fail, AND the native 0x8B packetizer to fail, so the module falls all
    the way back to ``display.animation_8b.build_8b_phases``."""
    monkeypatch.setattr(image_encoder, "_c_encode_animation_frame_32", lambda *a, **k: None)
    monkeypatch.setattr(image_encoder, "_c_encode_animation_frame", lambda *a, **k: None)
    monkeypatch.setattr(image_encoder, "_c_encode_animation_8b", lambda blob: None)

    captured = {}

    def fake_build_8b_phases(frames):
        captured["frames"] = frames
        return [b"phase0", b"phase1", b"phase2"]

    monkeypatch.setattr(
        "divoom_lib.display.animation_8b.build_8b_phases", fake_build_8b_phases)

    frame_32 = (bytes([5, 5, 5]) * (32 * 32), 32, 32, 111)
    frame_other = (bytes([9, 9, 9]) * (16 * 16), 16, 16, 222)
    result = image_encoder.encode_animation_8b_phases([frame_32, frame_other])

    assert result == [b"phase0", b"phase1", b"phase2"]
    assert captured["frames"] == [frame_32, frame_other]
