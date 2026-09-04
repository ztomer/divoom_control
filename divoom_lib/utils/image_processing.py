# divoom_api/utils/image_processing.py
from PIL import Image

from .divoom_image_encode import Frame

# Frame duration is encoded as a 2-byte (u16) field on the wire, so it must
# fit in [1, 65535] ms — see divoom_image_encode.encode_animation_frame (TTTT).
_MAX_FRAME_MS = 0xFFFF


def process_image(file, time: int | None = None, size: int | None = None):
    """Processes an image file (GIF or static image) into a format suitable for Divoom devices.

    Args:
        file: Path to the image file. Any format PIL supports.
        time: Optional default frame duration in milliseconds. Used for
            static images (where PIL doesn't provide a duration) and as
            a fallback for GIF frames with no per-frame duration set.
        size: Optional target device pixel size (e.g. 16 or 32). When set,
            every frame is resized to (size, size) with NEAREST resampling
            BEFORE encoding. This is required for correctness — the device
            renders at its native pixel grid, and encoding a full-resolution
            source overflows the 2-byte per-frame length field (the
            "int too big to convert" crash). When None, frames keep their
            native resolution (legacy behavior).

    Returns:
        (frames, frames_count, width, height):
          frames: list of (rgb_bytes, width, height, duration_ms) tuples,
              one per image frame. The rgb_bytes is in PIL's `tobytes()`
              order (left-to-right, top-to-bottom). width and height
              are the same for all frames in a single image.
          frames_count: number of frames (1 for static, n for GIF).
          width: image width in pixels.
          height: image height in pixels.

        On file error, returns ([], 0, 0, 0).
    """
    default_duration_ms = 1000 if time is None else int(time)

    try:
        img = Image.open(file)
    except FileNotFoundError:
        print(f"Error: Image file not found at {file}")
        return [], 0, 0, 0
    except Exception as e:
        print(f"Error opening image file {file}: {e}")
        return [], 0, 0, 0

    width, height = img.size
    frames: list[Frame] = []

    def _clamp_ms(ms: int) -> int:
        # u16 field; also avoid 0 (some firmware treats 0 as "no animation").
        return max(1, min(_MAX_FRAME_MS, int(ms)))

    def _to_rgb_bytes(frame_img):
        rgb_img = frame_img.convert("RGB")
        if size is not None and rgb_img.size != (size, size):
            rgb_img = rgb_img.resize((size, size), Image.Resampling.NEAREST)
        return rgb_img.tobytes()

    out_w = size if size is not None else width
    out_h = size if size is not None else height

    if hasattr(img, "is_animated") and img.is_animated:
        for frame_idx in range(img.n_frames):
            img.seek(frame_idx)
            rgb = _to_rgb_bytes(img)
            # PIL exposes per-frame duration in ms via .info.get("duration").
            # `or default`: a GIF frame often stores duration=0 ("as fast as
            # possible"); `.get(k, default)` only substitutes when the key is
            # ABSENT, so a present 0 fell through to _clamp_ms's 1ms floor → an
            # unviewable strobe on every frame after the first.
            duration = img.info.get("duration") or default_duration_ms
            frames.append((rgb, out_w, out_h, _clamp_ms(duration)))
    else:
        rgb = _to_rgb_bytes(img)
        frames.append((rgb, out_w, out_h, _clamp_ms(default_duration_ms)))

    return frames, len(frames), out_w, out_h
