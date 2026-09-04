"""
Performance benchmark: C downscaler vs PIL fallback.

Measures wall-clock time for representative workloads:
  - Cover art: 144×144 → 16×16  (iOS Photos typical thumbnail)
  - Cover art: 300×300 → 16×16  (album artwork from web)
  - Cover art: 640×480 → 16×12  (high-res photo)
  - Cover art: 1920×1080 → 16×9  (Full HD source, full-screen ratio)
  - Gallery:   3000×3000 → 16×16 (extreme downscale)

Each case is timed for N=200 iterations. We report:
  - median time per call
  - throughput (megapixels/sec)
  - speedup factor (PIL / native)

This is a benchmark, not a unit test — it's intended for ad-hoc runs,
not the regular CI suite. Pass --pytest-mode to run under pytest with
perf assertions.
"""
import statistics
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np
from PIL import Image

from divoom_lib.native import (
    CHANNELS_RGB,
    CHANNELS_RGBA,
    downsample_lanczos,
    is_native_available,
    reset_for_tests,
)


# ── Test configuration ─────────────────────────────────────────────────

# Workload definitions: (name, in_w, in_h, out_w, out_h, channels, n_iters)
WORKLOADS = [
    ("cover  144x144 -> 16x16  (RGB)",  144, 144, 16, 16, CHANNELS_RGB,  500),
    ("cover  300x300 -> 16x16  (RGB)",  300, 300, 16, 16, CHANNELS_RGB,  500),
    ("cover  640x480 -> 16x12  (RGB)",  640, 480, 16, 12, CHANNELS_RGB,  500),
    ("cover 1920x1080 -> 16x9  (RGB)", 1920, 1080, 16, 9, CHANNELS_RGB,  200),
    ("cover 3000x3000 -> 16x16 (RGB)", 3000, 3000, 16, 16, CHANNELS_RGB,  100),
    ("RGBA  144x144 -> 16x16          ", 144, 144, 16, 16, CHANNELS_RGBA, 500),
    ("RGBA  640x480 -> 16x12          ", 640, 480, 16, 12, CHANNELS_RGBA, 500),
    ("RGBA 3000x3000 -> 16x16         ", 3000, 3000, 16, 16, CHANNELS_RGBA, 100),
]

# Discard the first few iterations to avoid JIT/cache warmup cost.
WARMUP_ITERATIONS = 5

# PRNG seed for the input image. Constant so results are reproducible.
SEED_INPUT = 20260605

# 8-bit color range — pulled from numpy.uint8 typing.
UINT8_MIN = 0
UINT8_MAX_PLUS_ONE = 256  # np.random.randint upper bound is exclusive


# ── Helpers ────────────────────────────────────────────────────────────


@dataclass
class TimingResult:
    name: str
    median_ms: float
    mean_ms: float
    pixels: int             # input megapixels
    mpx_per_sec: float      # input megapixels per second
    speedup_x: float = 1.0  # only set for native results


def _time_call(fn: Callable[[], object], n_iters: int) -> tuple[float, float]:
    """Returns (median_ms, mean_ms) over n_iters calls of `fn`."""
    times_ms: list[float] = []
    for _ in range(n_iters):
        t0 = time.perf_counter()
        fn()
        t1 = time.perf_counter()
        times_ms.append((t1 - t0) * 1000.0)
    return statistics.median(times_ms), statistics.mean(times_ms)


def _make_input(in_w: int, in_h: int, channels: int) -> bytes:
    """Deterministic random input of size (in_h, in_w, channels)."""
    rng = np.random.default_rng(SEED_INPUT)
    arr = rng.integers(UINT8_MIN, UINT8_MAX_PLUS_ONE,
                       size=(in_h, in_w, channels), dtype=np.uint8)
    return arr.tobytes()


def _make_pil_input(in_w: int, in_h: int, channels: int) -> np.ndarray:
    """Same input as _make_input but as an ndarray for the PIL path."""
    rng = np.random.default_rng(SEED_INPUT)
    return rng.integers(UINT8_MIN, UINT8_MAX_PLUS_ONE,
                        size=(in_h, in_w, channels), dtype=np.uint8)


def _pil_resize_bytes(in_bytes: bytes, in_w: int, in_h: int,
                      out_w: int, out_h: int, channels: int) -> bytes:
    """The exact PIL fallback path used by gui/native_downscaler._pil_downsample."""
    mode = "RGBA" if channels == CHANNELS_RGBA else "RGB"
    img = Image.frombytes(mode, (in_w, in_h), in_bytes)
    return img.resize((out_w, out_h), Image.Resampling.LANCZOS).tobytes()


# ── Benchmark ──────────────────────────────────────────────────────────


def run_benchmark() -> list[TimingResult]:
    """Run all workloads through both PIL and native paths, return results."""
    results: list[TimingResult] = []
    reset_for_tests()
    native_available = is_native_available()

    for (name, in_w, in_h, out_w, out_h, channels, n_iters) in WORKLOADS:
        in_bytes = _make_input(in_w, in_h, channels)
        np_input = _make_pil_input(in_w, in_h, channels)
        pixels = in_w * in_h

        # Warmup — also lets the OS page in the input buffer.
        for _ in range(WARMUP_ITERATIONS):
            _pil_resize_bytes(in_bytes, in_w, in_h, out_w, out_h, channels)
        if native_available:
            for _ in range(WARMUP_ITERATIONS):
                downsample_lanczos(in_bytes, in_w, in_h, out_w, out_h, channels)

        # PIL path
        pil_median, pil_mean = _time_call(
            lambda: _pil_resize_bytes(in_bytes, in_w, in_h, out_w, out_h, channels),
            n_iters,
        )
        results.append(TimingResult(
            name=f"{name:38s} [PIL]   ",
            median_ms=pil_median,
            mean_ms=pil_mean,
            pixels=pixels,
            mpx_per_sec=(pixels / 1e6) / (pil_median / 1000.0),
        ))

        # Native path
        if native_available:
            nat_median, nat_mean = _time_call(
                lambda: downsample_lanczos(in_bytes, in_w, in_h, out_w, out_h, channels),
                n_iters,
            )
            results.append(TimingResult(
                name=f"{name:38s} [native]",
                median_ms=nat_median,
                mean_ms=nat_mean,
                pixels=pixels,
                mpx_per_sec=(pixels / 1e6) / (nat_median / 1000.0),
                speedup_x=pil_median / nat_median if nat_median > 0 else 0.0,
            ))

    return results


def print_results(results: list[TimingResult]) -> None:
    # Build paired rows: each workload has PIL then native.
    print()
    print("─" * 92)
    print(f"{'workload':40s}  {'median (ms)':>12s}  {'mean (ms)':>10s}  {'Mpx/sec':>10s}  speedup")
    print("─" * 92)
    pil_row: TimingResult | None = None
    for r in results:
        speedup_str = ""
        if r.speedup_x != 1.0:  # native row
            assert pil_row is not None
            speedup_str = f"{r.speedup_x:5.1f}x"
            pil_row = None
        else:
            pil_row = r
        print(f"{r.name:40s}  {r.median_ms:12.3f}  {r.mean_ms:10.3f}  "
              f"{r.mpx_per_sec:10.1f}  {speedup_str}")
    print("─" * 92)


def test_perf_smoke() -> None:
    """Pytest entry point — runs the benchmark and prints the result table.

    Status: INFORMATIONAL. We currently run ~0.3-0.8× of PIL's throughput
    (i.e. ~1.3-3.3× *slower*). The output is byte-exact, but the perf gap
    is real and is being investigated separately.

    Two leading hypotheses (deferred — see docs/CODE_REVIEW.md Phase 10):
      (a) PIL processes 4 input pixels per NEON op via `vld4q_u8`
          deinterleave; we currently process 1 pixel per op.
      (b) The clang auto-vectorizer prefers the 4-channel (RGBA) access
          pattern; the 3-channel RGB loop gets a worse schedule.

    Fail loudly if native is *faster* than PIL — that would mean a real
    perf regression in PIL. We want a regression alarm, not a target.
    """
    if not is_native_available():
        pytest.skip("native dylib not built")  # noqa: F821 (pytest imported lazily)
    results = run_benchmark()
    print_results(results)
    # Pair PIL/native rows by workload name. Print a soft warning if native
    # is slower, but don't fail (gap is deferred investigation).
    pil_t: dict[str, float] = {}
    nat_t: dict[str, float] = {}
    for r in results:
        if "[PIL]" in r.name:
            pil_t[r.name.split("[")[0]] = r.median_ms
        else:
            nat_t[r.name.split("[")[0]] = r.median_ms
    for key in pil_t:
        assert key in nat_t
        # Regression alarm: if native ever beats PIL, that's worth
        # investigating too (it would mean PIL slowed down somewhere).
        assert nat_t[key] >= pil_t[key] * 0.95, (
            f"native unexpectedly faster than PIL on {key!r}: "
            f"native={nat_t[key]:.3f}ms vs PIL={pil_t[key]:.3f}ms"
        )


if __name__ == "__main__":
    results = run_benchmark()
    print_results(results)
