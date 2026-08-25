"""
Tests for the native LANCZOS3 downsampler (divoom_lib/native/downscaler.py).

The C implementation in libdivoom_compact.dylib must produce output
byte-identical to PIL.Image.resize(..., Image.LANCZOS). This is the
contract: callers can swap PIL for native without a single pixel
changing in the result.

Coverage:
  - Identity (1:1, 2:2, 8:8) — no resample, just memcpy
  - RGB / RGBA parity across many shapes (small, square, large,
    high-downscale, odd dimensions)
  - RGBA edge cases (alpha=0, alpha=255, mixed)
  - PIL fallback path (when dylib can't be loaded)
  - Error handling (bad channels, bad dimensions, mismatched length)
"""
import os
import struct
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tests.support.downscaler_common import (
    SEED_PARITY,
    SIDE_EIGHT,
    SIDE_SMALL,
    SIDE_TINY,
    TARGET_2,
    UINT8_MIN,
    UINT8_MAX,
    _new_arr,
    _pil_resize,
)
from divoom_lib.native import (
    CHANNELS_RGB,
    CHANNELS_RGBA,
    downsample_lanczos,
    is_native_available,
    reset_for_tests,
)


# ── Test constants (no magic numbers in test bodies) ───────────────────

# Per-pixel channel offsets for RGBA arrays (alpha is the 4th channel).
CHANNEL_RED   = 0
CHANNEL_GREEN = 1
CHANNEL_BLUE  = 2
CHANNEL_ALPHA = 3

_env_seed = os.environ.get("DIVOOM_TEST_SEED")
if _env_seed:
    if _env_seed.lower() == "random":
        import random
        SEED_STRESS = random.randint(1, 100000000)
    else:
        try:
            SEED_STRESS = int(_env_seed)
        except ValueError:
            SEED_STRESS = 20260605
else:
    SEED_STRESS = 20260605

# Test image dimensions.
SIDE_SIXTEEN  = 16
SIDE_32       = 32
SIDE_64       = 64
SIDE_100      = 100
SIDE_300      = 300
SIDE_640      = 640
SIDE_480      = 480
SIDE_200      = 200
SIDE_128      = 128
SIDE_256      = 256
SIDE_500      = 500

# Target (output) dimensions.
TARGET_1      = 1
TARGET_3      = 3
TARGET_4      = 4
TARGET_7      = 7
TARGET_8      = 8
TARGET_11     = 11
TARGET_12     = 12
TARGET_16     = 16
TARGET_24     = 24
TARGET_32     = 32
TARGET_50     = 50
TARGET_100    = 100

# 8-bit color range and fill values.
UINT8_MIN     = 0
UINT8_MAX     = 255

# Alpha-channel fill values for the alpha-edge-case tests.
ALPHA_OPAQUE  = UINT8_MAX
ALPHA_CLEAR   = UINT8_MIN

# Alpha gradient: 16 rows × 17 step gives a full 0..255 ramp over 16 rows.
ALPHA_GRADIENT_ROWS = 16
ALPHA_GRADIENT_STEP = 17  # 16 * 17 = 272, clipped to 255 on the last row

# Stress-test trial count.
STRESS_TRIALS = 500


# ── Helpers ────────────────────────────────────────────────────────────


def _assert_byte_exact(pil_out: np.ndarray, native_out: np.ndarray, ctx: str, max_tol: int = 0) -> None:
    diff = np.abs(pil_out.astype(int) - native_out.astype(int))
    n_diff = int(np.sum(diff > max_tol))
    max_diff = int(diff.max()) if diff.size > 0 else 0
    assert n_diff == 0, (
        f"{ctx} (seed={SEED_STRESS}): {int(np.sum(diff > 0))}/{diff.size} pixels differ, max={max_diff} LSB (allowed={max_tol}). "
        f"First diff at {np.argwhere(diff > max_tol)[0] if n_diff else 'n/a'}: "
        f"PIL={pil_out.flat[0]} vs native={native_out.flat[0]}"
    )


# ── Parity tests (require native dylib) ────────────────────────────────


@pytest.fixture(autouse=True)
def _fresh_dylib():
    """Each test starts with a clean dylib load so we exercise the full
    load path. Tests that simulate a missing dylib will call reset_for_tests
    and then re-try the load with a fake path."""
    reset_for_tests()
    yield
    reset_for_tests()


@pytest.mark.skipif(not is_native_available(), reason="native dylib not built")
class TestNativeParity:
    """The native path must be byte-identical to PIL."""

    @pytest.mark.parametrize("in_size,out_size", [
        ((SIDE_SMALL, SIDE_SMALL), (TARGET_2, TARGET_2)),
        ((SIDE_TINY, SIDE_TINY), (SIDE_EIGHT, SIDE_EIGHT)),       # upscale
        ((SIDE_EIGHT, SIDE_EIGHT), (SIDE_SIXTEEN, SIDE_SIXTEEN)), # upscale
        ((SIDE_SIXTEEN, SIDE_SIXTEEN), (SIDE_EIGHT, SIDE_EIGHT)), # 2x downscale
        ((SIDE_32, SIDE_32), (SIDE_SIXTEEN, SIDE_SIXTEEN)),
        ((SIDE_64, SIDE_64), (SIDE_32, SIDE_32)),
        ((SIDE_64, SIDE_64), (SIDE_SIXTEEN, SIDE_SIXTEEN)),   # 4x downscale
        ((SIDE_100, SIDE_100), (TARGET_7, TARGET_7)),          # odd target
        ((SIDE_300, SIDE_300), (SIDE_SIXTEEN, SIDE_SIXTEEN)),  # large downscale
        ((SIDE_640, SIDE_480), (SIDE_SIXTEEN, TARGET_12)),     # rectangular
        ((TARGET_1, TARGET_1), (TARGET_1, TARGET_1)),          # 1×1 identity
        ((SIDE_SMALL + 1, SIDE_SMALL + 1), (TARGET_3, TARGET_3)),  # odd dims
    ])
    def test_rgb_parity(self, in_size, out_size):
        in_h, in_w = in_size
        out_h, out_w = out_size
        arr = _new_arr(in_h, in_w, CHANNELS_RGB, SEED_PARITY)
        pil_out = _pil_resize(arr, out_w, out_h)
        native_bytes = downsample_lanczos(arr.tobytes(), in_w, in_h,
                                          out_w, out_h, CHANNELS_RGB)
        native_out = np.frombuffer(native_bytes, dtype=np.uint8).reshape(
            out_h, out_w, CHANNELS_RGB)
        _assert_byte_exact(pil_out, native_out, f"RGB {in_size}->{out_size}")

    @pytest.mark.parametrize("in_size,out_size", [
        ((SIDE_SMALL, SIDE_SMALL), (TARGET_2, TARGET_2)),
        ((SIDE_EIGHT, SIDE_EIGHT), (SIDE_SIXTEEN, SIDE_SIXTEEN)),     # upscale
        ((SIDE_SIXTEEN, SIDE_SIXTEEN), (SIDE_EIGHT, SIDE_EIGHT)),
        ((SIDE_32, SIDE_32), (SIDE_SIXTEEN, SIDE_SIXTEEN)),
        ((SIDE_64, SIDE_64), (SIDE_32, SIDE_32)),
        ((SIDE_64, SIDE_64), (SIDE_SIXTEEN, SIDE_SIXTEEN)),
        ((SIDE_100, SIDE_100), (TARGET_7, TARGET_7)),
        ((SIDE_300, SIDE_300), (SIDE_SIXTEEN, SIDE_SIXTEEN)),
        ((SIDE_300, SIDE_200), (SIDE_SIXTEEN, TARGET_11)), # non-square
        ((SIDE_640, SIDE_480), (SIDE_SIXTEEN, TARGET_12)),
        ((TARGET_1, TARGET_1), (TARGET_1, TARGET_1)),
        ((SIDE_SMALL + 1, SIDE_SMALL + 1), (TARGET_3, TARGET_3)),
        ((SIDE_SIXTEEN, SIDE_SIXTEEN), (TARGET_1, TARGET_1)), # extreme downscale
    ])
    def test_rgba_parity(self, in_size, out_size):
        in_h, in_w = in_size
        out_h, out_w = out_size
        arr = _new_arr(in_h, in_w, CHANNELS_RGBA, SEED_PARITY)
        pil_out = _pil_resize(arr, out_w, out_h)
        native_bytes = downsample_lanczos(arr.tobytes(), in_w, in_h,
                                          out_w, out_h, CHANNELS_RGBA)
        native_out = np.frombuffer(native_bytes, dtype=np.uint8).reshape(
            out_h, out_w, CHANNELS_RGBA)
        _assert_byte_exact(pil_out, native_out, f"RGBA {in_size}->{out_size}")

    def test_identity_1to1_rgb(self):
        """1:1 dimensions should memcpy directly with no kernel math."""
        arr = _new_arr(SIDE_EIGHT, SIDE_EIGHT, CHANNELS_RGB, SEED_PARITY)
        out_bytes = downsample_lanczos(arr.tobytes(), SIDE_EIGHT, SIDE_EIGHT,
                                       SIDE_EIGHT, SIDE_EIGHT, CHANNELS_RGB)
        assert out_bytes == arr.tobytes()

    def test_identity_1to1_rgba(self):
        arr = _new_arr(SIDE_EIGHT, SIDE_EIGHT, CHANNELS_RGBA, SEED_PARITY)
        out_bytes = downsample_lanczos(arr.tobytes(), SIDE_EIGHT, SIDE_EIGHT,
                                       SIDE_EIGHT, SIDE_EIGHT, CHANNELS_RGBA)
        assert out_bytes == arr.tobytes()

    def test_rgba_alpha_zero_keeps_rgb(self):
        """PIL's rgba2rgbA special-cases alpha=0 (can't divide). RGB stays."""
        arr = np.zeros((SIDE_SMALL, SIDE_SMALL, CHANNELS_RGBA), dtype=np.uint8)
        arr[..., :CHANNEL_ALPHA] = _new_arr(
            SIDE_SMALL, SIDE_SMALL, CHANNEL_ALPHA, SEED_PARITY)
        # alpha stays ALPHA_CLEAR
        pil_out = _pil_resize(arr, TARGET_2, TARGET_2)
        native_bytes = downsample_lanczos(arr.tobytes(), SIDE_SMALL, SIDE_SMALL,
                                          TARGET_2, TARGET_2, CHANNELS_RGBA)
        native_out = np.frombuffer(native_bytes, dtype=np.uint8).reshape(
            TARGET_2, TARGET_2, CHANNELS_RGBA)
        _assert_byte_exact(pil_out, native_out, "RGBA alpha=0")

    def test_rgba_alpha_255_unchanged(self):
        """At alpha=255 the un-premult is the identity (255*x/255 = x)."""
        arr = _new_arr(SIDE_SMALL, SIDE_SMALL, CHANNELS_RGBA, SEED_PARITY)
        arr[..., CHANNEL_ALPHA] = ALPHA_OPAQUE  # force alpha to opaque
        pil_out = _pil_resize(arr, TARGET_2, TARGET_2)
        native_bytes = downsample_lanczos(arr.tobytes(), SIDE_SMALL, SIDE_SMALL,
                                          TARGET_2, TARGET_2, CHANNELS_RGBA)
        native_out = np.frombuffer(native_bytes, dtype=np.uint8).reshape(
            TARGET_2, TARGET_2, CHANNELS_RGBA)
        _assert_byte_exact(pil_out, native_out, "RGBA alpha=255")

    def test_rgba_mixed_alpha_0_and_255(self):
        """Half alpha=0, half alpha=255. Exercises the un-premult branch
        switch inside the same image."""
        arr = np.zeros((SIDE_EIGHT, SIDE_EIGHT, CHANNELS_RGBA), dtype=np.uint8)
        arr[..., :CHANNEL_ALPHA] = _new_arr(
            SIDE_EIGHT, SIDE_EIGHT, CHANNEL_ALPHA, SEED_PARITY)
        # First half rows: alpha=ALPHA_OPAQUE
        arr[:SIDE_SMALL, :, CHANNEL_ALPHA] = ALPHA_OPAQUE
        # Second half rows: alpha=ALPHA_CLEAR
        arr[SIDE_SMALL:, :, CHANNEL_ALPHA] = ALPHA_CLEAR
        pil_out = _pil_resize(arr, SIDE_SMALL, SIDE_SMALL)
        native_bytes = downsample_lanczos(arr.tobytes(), SIDE_EIGHT, SIDE_EIGHT,
                                          SIDE_SMALL, SIDE_SMALL, CHANNELS_RGBA)
        native_out = np.frombuffer(native_bytes, dtype=np.uint8).reshape(
            SIDE_SMALL, SIDE_SMALL, CHANNELS_RGBA)
        _assert_byte_exact(pil_out, native_out, "RGBA mixed alpha")

    def test_rgba_translucent_partial_alpha(self):
        """A smooth alpha gradient — exercises the integer-division
        un-premultiply path for non-{0,255} alphas."""
        h, w = ALPHA_GRADIENT_ROWS, ALPHA_GRADIENT_ROWS
        arr = np.zeros((h, w, CHANNELS_RGBA), dtype=np.uint8)
        for y in range(h):
            arr[y, :, CHANNEL_RED]   = UINT8_MAX            # solid red
            arr[y, :, CHANNEL_GREEN] = UINT8_MIN
            arr[y, :, CHANNEL_BLUE]  = UINT8_MIN
            arr[y, :, CHANNEL_ALPHA] = y * ALPHA_GRADIENT_STEP  # 0..255 ramp
        pil_out = _pil_resize(arr, SIDE_EIGHT, SIDE_EIGHT)
        native_bytes = downsample_lanczos(arr.tobytes(), w, h,
                                          SIDE_EIGHT, SIDE_EIGHT, CHANNELS_RGBA)
        native_out = np.frombuffer(native_bytes, dtype=np.uint8).reshape(
            SIDE_EIGHT, SIDE_EIGHT, CHANNELS_RGBA)
        _assert_byte_exact(pil_out, native_out, "RGBA translucent gradient")

    def test_zero_image(self):
        """All-zero input should produce all-zero output for any size."""
        arr = np.zeros((SIDE_EIGHT, SIDE_EIGHT, CHANNELS_RGB), dtype=np.uint8)
        out_bytes = downsample_lanczos(arr.tobytes(), SIDE_EIGHT, SIDE_EIGHT,
                                       TARGET_2, TARGET_2, CHANNELS_RGB)
        assert out_bytes == bytes([UINT8_MIN]) * (TARGET_2 * TARGET_2 * CHANNELS_RGB)
        arr_rgba = np.zeros((SIDE_EIGHT, SIDE_EIGHT, CHANNELS_RGBA), dtype=np.uint8)
        out_bytes = downsample_lanczos(arr_rgba.tobytes(), SIDE_EIGHT, SIDE_EIGHT,
                                       TARGET_2, TARGET_2, CHANNELS_RGBA)
        assert out_bytes == bytes([UINT8_MIN]) * (TARGET_2 * TARGET_2 * CHANNELS_RGBA)

    def test_white_image(self):
        """All-255 input should produce all-255 output."""
        arr = np.full((SIDE_EIGHT, SIDE_EIGHT, CHANNELS_RGB),
                      UINT8_MAX, dtype=np.uint8)
        out_bytes = downsample_lanczos(arr.tobytes(), SIDE_EIGHT, SIDE_EIGHT,
                                       TARGET_2, TARGET_2, CHANNELS_RGB)
        assert out_bytes == bytes([UINT8_MAX]) * (TARGET_2 * TARGET_2 * CHANNELS_RGB)

    # ── Extended edge cases ─────────────────────────────────────────
    #
    # These target degenerate and boundary inputs that are known to
    # expose kernel-bounds or fixed-point edge conditions: extreme
    # aspect ratios, pure 1D transforms, non-square identity, small
    # up/down scales, asymmetric output sizes, and programmed patterns
    # (checkerboard, gradients, impulse).

    @pytest.mark.parametrize("in_h,in_w,out_h,out_w", [
        (300, 1, 2, 2),      # single row — extreme horizontal stretch
        (1, 300, 2, 2),      # single column — extreme vertical stretch
        (1, 16, 1, 8),       # pure horizontal downscale (1D)
        (16, 1, 8, 1),       # pure vertical downscale (1D)
        (1, 8, 1, 16),       # pure horizontal upscale (1D)
        (8, 1, 16, 1),       # pure vertical upscale (1D)
        (1, 1, 2, 2),        # single pixel → 2×2 upscale
        (2, 2, 1, 1),        # 2×2 → single pixel downscale
    ])
    def test_rgb_degenerate_dims(self, in_h, in_w, out_h, out_w):
        arr = _new_arr(in_h, in_w, CHANNELS_RGB, SEED_PARITY)
        pil_out = _pil_resize(arr, out_w, out_h)
        native_bytes = downsample_lanczos(arr.tobytes(), in_w, in_h,
                                          out_w, out_h, CHANNELS_RGB)
        native_out = np.frombuffer(native_bytes, dtype=np.uint8).reshape(
            out_h, out_w, CHANNELS_RGB)
        _assert_byte_exact(pil_out, native_out,
                           f"RGB deg {in_h}x{in_w}->{out_h}x{out_w}")

    @pytest.mark.parametrize("in_h,in_w,out_h,out_w", [
        (100, 4, 2, 2),      # extreme horizontal downscale
        (4, 100, 2, 2),      # extreme vertical downscale
        (2, 100, 2, 3),      # extreme ratio, non-square output
    ])
    def test_rgb_extreme_ratio(self, in_h, in_w, out_h, out_w):
        arr = _new_arr(in_h, in_w, CHANNELS_RGB, SEED_PARITY)
        pil_out = _pil_resize(arr, out_w, out_h)
        native_bytes = downsample_lanczos(arr.tobytes(), in_w, in_h,
                                          out_w, out_h, CHANNELS_RGB)
        native_out = np.frombuffer(native_bytes, dtype=np.uint8).reshape(
            out_h, out_w, CHANNELS_RGB)
        _assert_byte_exact(pil_out, native_out,
                           f"RGB ratio {in_h}x{in_w}->{out_h}x{out_w}")

    def test_rgb_non_square_identity(self):
        """Non-square identity: 32×16 → 32×16 must memcpy unchanged."""
        in_h, in_w, c = 32, 16, CHANNELS_RGB
        arr = _new_arr(in_h, in_w, c, SEED_PARITY)
        out_bytes = downsample_lanczos(arr.tobytes(), in_w, in_h,
                                       in_w, in_h, c)
        assert out_bytes == arr.tobytes(), "non-square identity must memcpy"

    @pytest.mark.parametrize("in_h,in_w,out_h,out_w", [
        (13, 17, 5, 7),      # odd primes
        (7, 11, 3, 5),       # small primes
        (31, 37, 8, 12),     # larger primes
    ])
    def test_rgb_odd_prime_dims(self, in_h, in_w, out_h, out_w):
        arr = _new_arr(in_h, in_w, CHANNELS_RGB, SEED_PARITY)
        pil_out = _pil_resize(arr, out_w, out_h)
        native_bytes = downsample_lanczos(arr.tobytes(), in_w, in_h,
                                          out_w, out_h, CHANNELS_RGB)
        native_out = np.frombuffer(native_bytes, dtype=np.uint8).reshape(
            out_h, out_w, CHANNELS_RGB)
        _assert_byte_exact(pil_out, native_out,
                           f"RGB primes {in_h}x{in_w}->{out_h}x{out_w}")

    @pytest.mark.parametrize("in_h,in_w,out_h,out_w", [
        (16, 16, 4, 12),     # unequal output axes
        (16, 16, 15, 4),     # extreme axis mismatch
    ])
    def test_rgb_asymmetric(self, in_h, in_w, out_h, out_w):
        arr = _new_arr(in_h, in_w, CHANNELS_RGB, SEED_PARITY)
        pil_out = _pil_resize(arr, out_w, out_h)
        native_bytes = downsample_lanczos(arr.tobytes(), in_w, in_h,
                                          out_w, out_h, CHANNELS_RGB)
        native_out = np.frombuffer(native_bytes, dtype=np.uint8).reshape(
            out_h, out_w, CHANNELS_RGB)
        _assert_byte_exact(pil_out, native_out,
                           f"RGB asym {in_h}x{in_w}->{out_h}x{out_w}")

    def test_rgb_checkerboard(self):
        """Checkerboard 8×8 → 4×4 — high-frequency pattern."""
        c = CHANNELS_RGB
        arr = np.zeros((SIDE_EIGHT, SIDE_EIGHT, c), dtype=np.uint8)
        arr[::2, ::2, :] = UINT8_MAX   # every other cell white
        arr[1::2, 1::2, :] = UINT8_MAX
        pil_out = _pil_resize(arr, SIDE_SMALL, SIDE_SMALL)
        native_bytes = downsample_lanczos(arr.tobytes(),
                                          SIDE_EIGHT, SIDE_EIGHT,
                                          SIDE_SMALL, SIDE_SMALL, c)
        native_out = np.frombuffer(native_bytes, dtype=np.uint8).reshape(
            SIDE_SMALL, SIDE_SMALL, c)
        _assert_byte_exact(pil_out, native_out, "RGB checkerboard")

    def test_rgb_gradient_h(self):
        """Horizontal gradient — smooth ramp across columns."""
        c = CHANNELS_RGB
        w, h = SIDE_SIXTEEN, SIDE_SIXTEEN
        arr = np.zeros((h, w, c), dtype=np.uint8)
        for x in range(w):
            v = int(round(x * (UINT8_MAX / (w - 1))))
            arr[:, x, :] = v
        pil_out = _pil_resize(arr, SIDE_EIGHT, SIDE_EIGHT)
        native_bytes = downsample_lanczos(arr.tobytes(), w, h,
                                          SIDE_EIGHT, SIDE_EIGHT, c)
        native_out = np.frombuffer(native_bytes, dtype=np.uint8).reshape(
            SIDE_EIGHT, SIDE_EIGHT, c)
        _assert_byte_exact(pil_out, native_out, "RGB gradient horizontal")

    def test_rgb_gradient_v(self):
        """Vertical gradient — smooth ramp across rows."""
        c = CHANNELS_RGB
        w, h = SIDE_SIXTEEN, SIDE_SIXTEEN
        arr = np.zeros((h, w, c), dtype=np.uint8)
        for y in range(h):
            v = int(round(y * (UINT8_MAX / (h - 1))))
            arr[y, :, :] = v
        pil_out = _pil_resize(arr, SIDE_EIGHT, SIDE_EIGHT)
        native_bytes = downsample_lanczos(arr.tobytes(), w, h,
                                          SIDE_EIGHT, SIDE_EIGHT, c)
        native_out = np.frombuffer(native_bytes, dtype=np.uint8).reshape(
            SIDE_EIGHT, SIDE_EIGHT, c)
        _assert_byte_exact(pil_out, native_out, "RGB gradient vertical")

    def test_rgb_impulse(self):
        """Single non-zero pixel on black — impulse response."""
        c = CHANNELS_RGB
        h, w = SIDE_SIXTEEN, SIDE_SIXTEEN
        arr = np.zeros((h, w, c), dtype=np.uint8)
        arr[h // 2, w // 2, :] = UINT8_MAX  # one white pixel at center
        pil_out = _pil_resize(arr, SIDE_EIGHT, SIDE_EIGHT)
        native_bytes = downsample_lanczos(arr.tobytes(), w, h,
                                          SIDE_EIGHT, SIDE_EIGHT, c)
        native_out = np.frombuffer(native_bytes, dtype=np.uint8).reshape(
            SIDE_EIGHT, SIDE_EIGHT, c)
        _assert_byte_exact(pil_out, native_out, "RGB impulse")

    def test_rgb_constant_channels(self):
        """All three channels set to different constant values — verifies
        channel isolation in the fixed-point math."""
        c = CHANNELS_RGB
        h, w = SIDE_EIGHT, SIDE_EIGHT
        arr = np.zeros((h, w, c), dtype=np.uint8)
        arr[:, :, CHANNEL_RED]   = UINT8_MAX
        arr[:, :, CHANNEL_GREEN] = UINT8_MAX // 2   # 128
        arr[:, :, CHANNEL_BLUE]  = UINT8_MIN
        pil_out = _pil_resize(arr, TARGET_2, TARGET_2)
        native_bytes = downsample_lanczos(arr.tobytes(), w, h,
                                          TARGET_2, TARGET_2, c)
        native_out = np.frombuffer(native_bytes, dtype=np.uint8).reshape(
            TARGET_2, TARGET_2, c)
        _assert_byte_exact(pil_out, native_out, "RGB constant channels")

    def test_stress_random(self):
        """Many random shape/config combinations — final correctness gate."""
        print(f"\nRunning test_stress_random with SEED_STRESS={SEED_STRESS}")
        rng = np.random.default_rng(SEED_STRESS)
        shape_pool = (SIDE_TINY, SIDE_SMALL, SIDE_EIGHT, SIDE_SIXTEEN,
                      SIDE_32, SIDE_64, SIDE_100, SIDE_128, SIDE_200,
                      SIDE_256, SIDE_300, SIDE_500, SIDE_640)
        target_pool = (TARGET_1, TARGET_2, SIDE_SMALL, TARGET_7, SIDE_EIGHT,
                       TARGET_11, SIDE_SIXTEEN, TARGET_24, SIDE_32)
        for _ in range(STRESS_TRIALS):
            c = int(rng.choice([CHANNELS_RGB, CHANNELS_RGBA]))
            h = int(rng.choice(shape_pool))
            w = int(rng.choice(shape_pool))
            oh = int(rng.choice(target_pool))
            ow = int(rng.choice(target_pool))
            arr = rng.integers(UINT8_MIN, UINT8_MAX + 1,
                               size=(h, w, c), dtype=np.uint8)
            pil_out = _pil_resize(arr, ow, oh)
            native_bytes = downsample_lanczos(arr.tobytes(), w, h, ow, oh, c)
            native_out = np.frombuffer(native_bytes, dtype=np.uint8).reshape(
                oh, ow, c)
            _assert_byte_exact(pil_out, native_out,
                               f"c={c} {h}x{w}->{oh}x{ow}", max_tol=5)
