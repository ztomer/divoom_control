"""Constants + image helpers shared by the native-downscaler test modules."""
import numpy as np
from PIL import Image

from divoom_lib.native import CHANNELS_RGBA

# Deterministic PRNG seeds.
SEED_PARITY   = 42       # small/medium parity cases

# Test image dimensions.
SIDE_TINY     = 2
SIDE_SMALL    = 4
SIDE_EIGHT    = 8

# Target (output) dimensions.
TARGET_2      = 2

# 8-bit color range and fill values.
UINT8_MIN     = 0
UINT8_MAX     = 255


def _pil_resize(arr: np.ndarray, out_w: int, out_h: int) -> np.ndarray:
    """Reference LANCZOS3 downscale via PIL. Matches the production path
    that the native dylib must bit-match."""
    mode = "RGBA" if arr.shape[2] == CHANNELS_RGBA else "RGB"
    im = Image.fromarray(arr, mode=mode)
    return np.array(im.resize((out_w, out_h), Image.Resampling.LANCZOS), dtype=np.uint8)


def _new_arr(h: int, w: int, c: int, seed: int) -> np.ndarray:
    """Random uint8 array of shape (h, w, c) with a fixed seed."""
    rng = np.random.default_rng(seed)
    return rng.integers(UINT8_MIN, UINT8_MAX + 1, size=(h, w, c), dtype=np.uint8)
