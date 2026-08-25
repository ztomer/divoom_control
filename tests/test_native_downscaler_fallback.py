"""PIL-fallback + error-handling coverage for divoom_lib.native.downscaler
(split from test_native_downscaler.py)."""
import pytest

from divoom_lib.native import (
    CHANNELS_RGB,
    downsample_lanczos,
    is_native_available,
    reset_for_tests,
)
from tests.support.downscaler_common import (
    SEED_PARITY,
    SIDE_EIGHT,
    SIDE_SMALL,
    SIDE_TINY,
    TARGET_2,
    UINT8_MIN,
    _new_arr,
    _pil_resize,
)


# ── PIL fallback path ──────────────────────────────────────────────────


class TestPILFallback:
    """When the dylib can't be loaded, the wrapper must fall back to PIL
    and produce the same bytes. The two paths are intentionally independent
    so the fallback can be tested by simulating a missing dylib."""

    def test_fallback_when_dylib_missing(self, monkeypatch):
        """Force ctypes.CDLL to raise OSError so the loader fails. The
        wrapper should then fall back to PIL and produce the same bytes."""
        # Reset cached state from any prior test, then make CDLL blow up.
        reset_for_tests()
        def _cdll_fails(*args, **kwargs):
            raise OSError("simulated dylib load failure")
        monkeypatch.setattr("divoom_lib.native.downscaler.ctypes.CDLL", _cdll_fails)
        reset_for_tests()
        # The dylib won't load — wrapper should fall back to PIL.
        assert is_native_available() is False

        arr = _new_arr(SIDE_EIGHT, SIDE_EIGHT, CHANNELS_RGB, SEED_PARITY)
        out_bytes = downsample_lanczos(arr.tobytes(), SIDE_EIGHT, SIDE_EIGHT,
                                       TARGET_2, TARGET_2, CHANNELS_RGB)
        expected = _pil_resize(arr, TARGET_2, TARGET_2).tobytes()
        assert out_bytes == expected

# ── Error handling ─────────────────────────────────────────────────────


class TestErrorHandling:
    """Invalid inputs must raise clear errors, not silently produce garbage."""

    def test_invalid_channels(self):
        bad_channels = 2  # not in {CHANNELS_RGB, CHANNELS_RGBA}
        with pytest.raises(ValueError, match="channels must be"):
            downsample_lanczos(bytes(SIDE_SMALL * SIDE_SMALL * bad_channels),
                               SIDE_TINY, SIDE_TINY, SIDE_TINY, SIDE_TINY,
                               channels=bad_channels)

    def test_zero_dimensions(self):
        with pytest.raises(ValueError, match="dimensions must be positive"):
            downsample_lanczos(bytes(SIDE_SMALL * SIDE_SMALL * CHANNELS_RGB),
                               UINT8_MIN, SIDE_SMALL, SIDE_TINY, SIDE_TINY,
                               CHANNELS_RGB)

    def test_mismatched_length(self):
        # buffer length is for a 2x2 RGB, but we pass 2x2 dimensions
        # (length 12 expected, give 3)
        short_len = 3
        with pytest.raises(ValueError, match="in_bytes length"):
            downsample_lanczos(bytes(short_len), SIDE_TINY, SIDE_TINY,
                               SIDE_TINY, SIDE_TINY, CHANNELS_RGB)
