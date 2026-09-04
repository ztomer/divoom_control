"""
Performance tests for the C image encoder.

Compares the C encoder (via the dylib) against the pure-Python encoder
on a fixed set of workloads that mirror real-device usage:
  - 16x16 single frame (Timoo/Pixoo)
  - 32x32 single frame (Tivoo)
  - 64x64 single frame (Tivoo Max)
  - 160x140 single frame (Tivoo Max)
  - 200-frame animation at 16x16 (push to device)

Honest finding (2026-06-05, M4 Max, Apple clang -O3):
  The C encoder is AS FAST as the pure-Python encoder for typical
  workloads (within ±5%). The Python encoder already uses C-level
  dicts for palette dedup and C-level bytearray for bit packing,
  so the interpreter overhead is small for the hot path. ctypes
  overhead per call (~1-5µs) is comparable to the actual work for
  a 16x16 image (~30-50µs), which means ctypes overhead cancels
  the C speedup for small inputs.

  The value of the C encoder today is:
    1. A byte-exact reference implementation (40 parity tests pass).
    2. A foundation for SIMD/vectorization work that will pay off
       once the ctypes boundary is bypassed (e.g., via batch calls).

  This test serves as a *regression alarm*: it fails only if the C
  path becomes SIGNIFICANTLY slower than Python (≥2× slower), which
  would indicate a real problem (broken inlining, wrong build flags,
  accidental data copy in the hot path).
"""
import os
import random
import statistics
import time

import pytest

from divoom_lib.native import image_encoder
from divoom_lib.utils.divoom_image_encode import (
    encode_animation_frame as py_encode_animation_frame,
    _py_encode_animation,
)


pytestmark = pytest.mark.skipif(
    not image_encoder.is_native_available(),
    reason="C dylib not available — image encoder perf requires libdivoom_compact.dylib"
)


def _make_random_rgb(w: int, h: int, num_colors: int, seed: int = 0) -> bytes:
    """Build a w*h*3 byte string with `num_colors` distinct colors."""
    rng = random.Random(seed)
    palette = [(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(num_colors)]
    out = bytearray()
    for _ in range(w * h):
        r, g, b = palette[rng.randrange(num_colors)]
        out.extend((r, g, b))
    return bytes(out)


def _time_it(fn, n_iter: int = 5) -> float:
    """Return median time in seconds over `n_iter` calls."""
    samples = []
    for _ in range(n_iter):
        t0 = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t0)
    return statistics.median(samples)


# ---- single frame: regression alarm (C must not be >2× slower) ----

@pytest.mark.parametrize("w,h,num_colors", [
    (16, 16, 4),       # Timoo / Pixoo: 4 colors
    (16, 16, 256),     # Timoo / Pixoo: 256 colors
    (32, 32, 32),
    (64, 64, 64),
    (64, 64, 256),
    (160, 140, 64),    # Tivoo Max
    (160, 140, 256),
])
def test_perf_animation_frame_not_regressed(w, h, num_colors):
    """Regression alarm: C must not be >2× slower than Python for single frames.

    ctypes overhead is per-call (~1-5µs) and is comparable to the work
    for small images. C and Python are typically within ±5% for typical
    workloads. We allow C to be up to 2× slower; if it gets worse, the
    C path has regressed and needs investigation.
    """
    rgb = _make_random_rgb(w, h, num_colors)
    py_t = _time_it(lambda: py_encode_animation_frame(rgb, w, h, 1000))
    c_t = _time_it(lambda: image_encoder.encode_animation_frame(rgb, w, h, 1000))
    ratio = c_t / py_t if py_t > 0 else 1.0
    print(f"\n  {w}x{h} {num_colors}-color: py={py_t*1e6:.1f}us c={c_t*1e6:.1f}us  C/Py={ratio:.2f}")
    # C should not be more than 2× slower than Python. The ctypes overhead
    # for tiny inputs (16x16) is significant; the threshold is set to
    # accommodate that. Future SIMD work should push C well under 1.0×.
    assert ratio < 2.0, f"C encoder is {ratio:.2f}× of Python for {w}x{h} {num_colors}-color — REGRESSION"


# ---- animation: regression alarm ----

def test_perf_animation_200_frames_16x16_not_regressed():
    """200 frames of 16x16 is a typical 'push this animation' workload.

    The C path calls divoom_encode_animation_frame 200 times (once per
    frame), accumulating ctypes overhead. We accept up to 2× slower
    than the all-Python path.
    """
    w, h = 16, 16
    frames = []
    for i in range(200):
        rgb = _make_random_rgb(w, h, 8, seed=i)
        frames.append((rgb, w, h, 100))

    py_t = _time_it(lambda: _py_encode_animation(frames), n_iter=3)
    c_t = _time_it(lambda: image_encoder.encode_animation(frames), n_iter=3)
    ratio = c_t / py_t if py_t > 0 else 1.0
    print(f"\n  200-frame 16x16 animation: py={py_t*1000:.2f}ms c={c_t*1000:.2f}ms  C/Py={ratio:.2f}")
    assert ratio < 2.0, f"C animation encoder is {ratio:.2f}× of Python — REGRESSION"


def test_perf_animation_50_frames_64x64_not_regressed():
    """50 frames of 64x64 (≈ 50 * 2.6KB = 130KB; u16 truncation OK)."""
    w, h = 64, 64
    frames = []
    for i in range(50):
        rgb = _make_random_rgb(w, h, 32, seed=i)
        frames.append((rgb, w, h, 200))

    py_t = _time_it(lambda: _py_encode_animation(frames), n_iter=3)
    c_t = _time_it(lambda: image_encoder.encode_animation(frames), n_iter=3)
    ratio = c_t / py_t if py_t > 0 else 1.0
    print(f"\n  50-frame 64x64 animation: py={py_t*1000:.2f}ms c={c_t*1000:.2f}ms  C/Py={ratio:.2f}")
    assert ratio < 2.0, f"C animation encoder is {ratio:.2f}× of Python — REGRESSION"


# ---- smoke test: C call is byte-identical to Python on this workload ----

def test_perf_smoke_byte_identical():
    """Quick sanity that we're benchmarking the same operation."""
    rgb = _make_random_rgb(16, 16, 4)
    py = py_encode_animation_frame(rgb, 16, 16, 1000)
    cn = image_encoder.encode_animation_frame(rgb, 16, 16, 1000)
    assert py == cn
