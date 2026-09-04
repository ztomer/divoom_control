"""Divoom device image encoder.

Pure-Python re-implementation of the protocol used by the official
Divoom APK to push images to Timebox-Evo / Pixoo / Tivoo / Timoo /
Ditoo devices over Bluetooth. The protocol is documented in
`references/divoom-timebox-evo/PROTOCOL.md` (RomRider) and verified
to work with real hardware by multiple independent users.

The key facts (vs. naive raw-RGB push):

  1. The device does NOT accept raw RGB. It expects a *palette-quantized*
     + *bit-packed* format.
  2. Static images use command 0x44 with a 10-byte fixed header followed
     by COLOR_DATA (palette, hex-encoded RRGGBB × num_colors) and
     PIXEL_DATA (bit-packed pixel indices, LSB first into LSB-first
     bytes).
  3. Animations use command 0x49 with one *frame block* per frame
     (`AA LLLL TTTT RR NN COLOR_DATA PIXEL_DATA`), concatenated, then
     split into 200-byte packets and sent as a sequence of 0x49
     messages.
  4. nbBits = ceil(log2(num_colors)) (minimum 1), so a 1-color image
     uses 1 bit/pixel and a 256-color image uses 8 bits/pixel.

This module is deliberately dependency-free (stdlib only) so it can
be used from any caller without pulling in NumPy. Performance is
acceptable for typical device sizes (16×16 to 160×140).
"""
import math
from typing import List, Tuple


Frame = Tuple[bytes, int, int, int]
"""(rgb_bytes, width, height, duration_ms) — one image frame."""


def build_palette_and_pixels(
    rgb_bytes: bytes, w: int, h: int,
) -> Tuple[List[Tuple[int, int, int]], List[int], int]:
    """Deduplicate colors and assign each pixel its palette index.

    Walks the image left-to-right, top-to-bottom (PIL's `tobytes()`
    order, which is what every caller will produce). Builds a
    palette of at most 256 colors. The palette is in *first-seen*
    order, which is important: the device renders pixels by their
    position in the palette, so first-seen order is the natural
    canonical ordering.

    Args:
        rgb_bytes: width*height*3 bytes, R,G,B per pixel.
        w: image width in pixels.
        h: image height in pixels.

    Returns:
        (palette, pixels, nbBits):
          palette: list of (R, G, B) tuples, deduplicated, first-seen order.
          pixels:  list of palette indices, length w*h.
          nbBits:  bits per pixel, ceil(log2(len(palette))) with a
                   minimum of 1 (so a 1-color image still uses 1 bit).

    Raises:
        ValueError: if the image has more than 256 unique colors.
    """
    if len(rgb_bytes) != w * h * 3:
        raise ValueError(
            f"rgb_bytes length {len(rgb_bytes)} != {w}*{h}*3 = {w*h*3}"
        )
    color_to_index: dict[tuple[int, int, int], int] = {}
    palette: List[Tuple[int, int, int]] = []
    pixels: List[int] = []
    for off in range(0, len(rgb_bytes), 3):
        color = (rgb_bytes[off], rgb_bytes[off + 1], rgb_bytes[off + 2])
        idx = color_to_index.get(color)
        if idx is None:
            if len(palette) == 256:
                raise ValueError(
                    f"image has more than 256 unique colors; the device "
                    f"protocol supports at most 256 (at pixel offset {off // 3})"
                )
            idx = len(palette)
            color_to_index[color] = idx
            palette.append(color)
        pixels.append(idx)
    nb_bits = max(1, math.ceil(math.log2(len(palette)))) if palette else 1
    return palette, pixels, nb_bits


def encode_palette(palette: List[Tuple[int, int, int]]) -> bytes:
    """Encode a color palette as a byte string of `RRGGBB` per color.

    Each color is encoded as 3 bytes (R, G, B). The device's parser
    reads the palette as a hex string, but at the byte level this
    is just three consecutive bytes per color.

    Returns:
        bytes of length 3 * len(palette).
    """
    out = bytearray()
    for r, g, b in palette:
        out.append(r)
        out.append(g)
        out.append(b)
    return bytes(out)


def encode_pixels(pixels: List[int], nb_bits: int) -> bytes:
    """Bit-pack pixel indices LSB-first, **continuously across byte boundaries**.

    This matches the device's parser and the futpib reference, which uses
    ``bitstream_io::LittleEndian`` (``frame.rs`` build_pixel_data /
    Frame::from_16x16): the first pixel occupies the lowest bits of byte 0, and
    a pixel whose bits cross a byte boundary continues into the next byte — its
    high bits are NOT dropped.

    The previous implementation reset the accumulator at each byte and masked to
    8 bits, which silently discarded the carry whenever ``nb_bits`` did not
    divide 8 (i.e. 3/5/6/7 bits per pixel). That corrupted any image with
    5–8, 17–32, 33–64, or 65–128 colours — e.g. a downsampled album cover with
    ~43 colours (nb_bits=6) rendered as garbage (R11 cover-art distortion).

    Args:
        pixels:  list of palette indices, length w*h.
        nb_bits: bits per pixel (1-8).

    Returns:
        bytes of length ceil(len(pixels) * nb_bits / 8).
    """
    if nb_bits < 1 or nb_bits > 8:
        raise ValueError(f"nb_bits must be in [1, 8], got {nb_bits}")
    max_val = (1 << nb_bits) - 1
    out = bytearray()
    acc = 0          # bit accumulator (LSB-first)
    acc_bits = 0     # number of valid bits currently in `acc`
    for idx in pixels:
        if idx < 0 or idx > max_val:
            raise ValueError(
                f"pixel index {idx} doesn't fit in {nb_bits} bits "
                f"(max value {max_val})"
            )
        acc |= (idx & max_val) << acc_bits
        acc_bits += nb_bits
        while acc_bits >= 8:
            out.append(acc & 0xFF)
            acc >>= 8
            acc_bits -= 8
    if acc_bits > 0:
        out.append(acc & 0xFF)
    return bytes(out)


def _u16_le(n: int) -> bytes:
    """Pack an integer as 2 little-endian bytes."""
    return n.to_bytes(2, byteorder="little", signed=False)


def _u16_be(n: int) -> bytes:
    """Pack an integer as 2 big-endian bytes."""
    return n.to_bytes(2, byteorder="big", signed=False)


def encode_static_image(rgb_bytes: bytes, w: int, h: int) -> bytes:
    """Encode a static image as the 0x44 command body.

    The 0x44 command is wrapped by the framing layer with the prefix
    `44 00 0A 0A 04` (1 byte command + 4 bytes fixed magic). The
    payload returned by this function is appended to that prefix.

    Layout of this function's output (the post-prefix payload):
        0xAA        (image data start marker)
        LLLL        (LE u16: byte count of (AA + LLLL + 000000 + NN +
                     COLOR_DATA + PIXEL_DATA), i.e. the entire payload
                     INCLUDING the 2 LLLL bytes themselves)
        0x00 0x00 0x00  (3-byte fixed padding)
        NN          (u8 num colors; 0 means 256 per the device protocol)
        COLOR_DATA  (palette: 3 bytes per color, R G B, first-seen order)
        PIXEL_DATA  (bit-packed pixel indices, LSB-first into LSB-first
                     bytes; ceil(log2(NN)) bits per pixel, min 1)

    Args:
        rgb_bytes: width*height*3 bytes, R,G,B per pixel.
        w: image width in pixels.
        h: image height in pixels.

    Returns:
        bytes ready to be sent as the payload of a 0x44 command.
    """
    palette, pixels, nb_bits = build_palette_and_pixels(rgb_bytes, w, h)
    color_data = encode_palette(palette)
    pixel_data = encode_pixels(pixels, nb_bits)
    # LLLL = 1 (AA) + 2 (LLLL) + 3 (000000) + 1 (NN) + 3N (colors) + p (pixels)
    # = 7 + 3N + p. Per RomRider reference: `int2hexlittle((('AA0000000000'
    #   + stringWithoutHeader).length) / 2)` where stringWithoutHeader =
    #   NN + COLOR + PIXEL. The 6 zero bytes in 'AA0000000000' represent
    #   the LLLL (2) + 000000 (3) + AA (1) = 6 byte placeholders.
    llll = 7 + len(color_data) + len(pixel_data)
    if llll > 0xFFFF:
        raise ValueError(
            f"encoded image body is {llll} bytes, exceeds the 2-byte length "
            f"field (max 65535). Resize the image to the device pixel grid "
            f"(e.g. 16x16/32x32) before encoding."
        )
    # NN is u8; 256 colors is encoded as 0 per the device's protocol.
    nn = len(palette) if len(palette) < 256 else 0
    header = bytes([0xAA]) + _u16_le(llll) + bytes([0x00, 0x00, 0x00, nn])
    return header + color_data + pixel_data


def encode_animation_frame(
    rgb_bytes: bytes, w: int, h: int, time_ms: int,
) -> bytes:
    """Encode a single animation frame.

    Layout per frame (per RomRider reference `DivoomJimpAnim.asDivoomMessage`):
        0xAA         (frame data start marker)
        LLLL         (LE u16: byte count of (AA + LLLL + TTTT + RR + NN
                      + COLOR_DATA + PIXEL_DATA), INCLUDING the 2 LLLL
                      bytes themselves)
        TTTT         (LE u16: frame duration in milliseconds)
        RR           (u8 reset palette flag; 0x00 = reset on each frame,
                      0x01 = keep cumulative palette; reference uses 0x00)
        NN           (u8 num colors; 0 means 256)
        COLOR_DATA   (palette: 3 bytes per color, first-seen order)
        PIXEL_DATA   (bit-packed pixel indices)

    Args:
        rgb_bytes: width*height*3 bytes, R,G,B per pixel.
        w: image width in pixels.
        h: image height in pixels.
        time_ms: how long to display this frame, in milliseconds.

    Returns:
        bytes of one frame, ready to be concatenated with other frames
        and chunked into 0x49 packets.
    """
    palette, pixels, nb_bits = build_palette_and_pixels(rgb_bytes, w, h)
    color_data = encode_palette(palette)
    pixel_data = encode_pixels(pixels, nb_bits)
    # Per reference: `int2hexlittle((stringWithoutHeader.length + 6) / 2)`
    # where stringWithoutHeader = TTTT + RR + NN + COLOR + PIXEL
    # (4 + 3N + p bytes; 2 hex chars each → 8 + 6N + 2p hex chars;
    # + 6 hex chars from "AA 00 00 00 00 00" placeholder = 14 + 6N + 2p
    # hex chars; / 2 = 7 + 3N + p bytes).
    llll = 7 + len(color_data) + len(pixel_data)
    if llll > 0xFFFF:
        raise ValueError(
            f"encoded frame body is {llll} bytes, exceeds the 2-byte length "
            f"field (max 65535). Resize the image to the device pixel grid "
            f"(e.g. 16x16/32x32) before encoding."
        )
    # Frame time is a u16 (TTTT); clamp to avoid 'int too big to convert'.
    t = max(0, min(0xFFFF, int(time_ms)))
    # NN is u8; 256 colors is encoded as 0 per the device's protocol.
    nn = len(palette) if len(palette) < 256 else 0
    header = (
        bytes([0xAA])
        + _u16_le(llll)
        + _u16_le(t)
        + bytes([0x00, nn])  # RR=0 (reset palette), NN
    )
    return header + color_data + pixel_data


_ANIMATION_PACKET_PAYLOAD_SIZE = 200


def encode_animation(frames: List[Frame]) -> List[bytes]:
    """Encode an animation as a list of 0x49 packet payloads.

    Each frame is encoded with `encode_animation_frame`, then all
    frames are concatenated. The concatenation is split into
    200-byte chunks; each chunk is wrapped in a 0x49 packet:

        TOTAL_LEN  (LE u16: total length of all concatenated frame data)
        PACKET_NUM (u8: 0-based packet index)
        200 bytes  (the chunk; the last chunk may be shorter)

    Routes through the C dylib (divoom_lib.native.image_encoder) when
    available; byte-identical to the pure-Python path. Falls back to
    pure-Python if the dylib is missing or returns an error.

    Args:
        frames: list of (rgb_bytes, w, h, time_ms) tuples.

    Returns:
        list of bytes, each ready to be sent as the payload of a 0x49
        command. One packet per 200-byte chunk of the concatenated
        frame data.
    """
    if not frames:
        return []
    try:
        from ..native import image_encoder
        if image_encoder.is_native_available():
            return image_encoder.encode_animation(frames)
    except Exception:
        pass
    return _py_encode_animation(frames)


def _py_encode_animation(frames: List[Frame]) -> List[bytes]:
    """Pure-Python animation encoder. Kept for parity tests + fallback.

    The protocol's TOTAL_LEN is a LE u16 (max 65535). Animations larger
    than that are silently truncated to the u16 value (matching the C
    encoder's uint16_t cast). Callers should validate their animation
    size; this function does not raise.

    Packet format (per RomRider reference — confirmed live 2026-06-05):
        [TOTAL_LEN LE u16][PACKET_NUM u8][chunk up to 200 bytes]
    PACKET_NUM is 1 byte (0-255), NOT 2. The earlier BE + 2-byte-counter
    format silently failed on the Timoo (device only displayed the first
    frame of a multi-frame animation).
    """
    if not frames:
        return []
    encoded_frames = [
        encode_animation_frame(rgb, w, h, t) for (rgb, w, h, t) in frames
    ]
    blob = b"".join(encoded_frames)
    total_len = len(blob) & 0xFFFF  # protocol u16 limit
    packets: List[bytes] = []
    packet_num = 0
    for offset in range(0, len(blob), _ANIMATION_PACKET_PAYLOAD_SIZE):
        chunk = blob[offset : offset + _ANIMATION_PACKET_PAYLOAD_SIZE]
        packet = _u16_le(total_len) + bytes([packet_num & 0xFF]) + chunk
        packets.append(packet)
        packet_num += 1
    return packets
