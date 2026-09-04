#!/usr/bin/env python3
"""Generate image-encoder parity vectors from the Python reference so the Rust FFI
(divoomd src/native_encode.rs) can assert byte-for-byte parity against
libdivoom_compact. The Rust FFI calls the SAME C functions, so a match confirms the
FFI marshalling (pointers, out-buffer sizing, return-length truncation) is correct.

    PYTHONPATH=<repo root> python3 scripts/codegen/gen_image_vectors.py
"""
import json
import random
from pathlib import Path

from divoom_lib.native import image_encoder as IE
from divoom_lib.utils.divoom_image_encode_32 import encode_animation_frame_32 as py_frame32


def rgb_n(w, h, nc, seed):
    rng = random.Random(seed)
    pal = [bytes((rng.randrange(256), rng.randrange(256), rng.randrange(256))) for _ in range(nc)]
    return b"".join(pal[(x * 7 + y * 13) % nc] for y in range(h) for x in range(w))


def main():
    frame, static, frame32 = [], [], []
    cases = [(1, 1, 1), (2, 2, 4), (16, 16, 1), (16, 16, 2), (16, 16, 17),
             (16, 16, 200), (16, 16, 256), (5, 7, 5)]
    for (w, h, nc) in cases:
        rgb = rgb_n(w, h, nc, w * 1000 + h * 10 + nc)
        f = IE.encode_animation_frame(rgb, w, h, 500)
        s = IE.encode_static_image(rgb, w, h)
        frame.append({"w": w, "h": h, "time": 500, "rgb": rgb.hex(), "out": bytes(f).hex()})
        static.append({"w": w, "h": h, "rgb": rgb.hex(), "out": bytes(s).hex()})
    for nc in [1, 2, 4, 16, 256]:
        rgb = rgb_n(32, 32, nc, nc + 9999)
        f32 = py_frame32(rgb, 32, 32, 500)
        frame32.append({"w": 32, "h": 32, "time": 500, "rgb": rgb.hex(), "out": bytes(f32).hex()})

    out = {"frame": frame, "static": static, "frame32": frame32}
    dest = Path(__file__).parent / "divoomd" / "tests" / "image_vectors.json"
    dest.write_text(json.dumps(out, indent=2))
    print(f"wrote {len(frame)+len(static)+len(frame32)} vectors -> {dest}")


if __name__ == "__main__":
    main()
