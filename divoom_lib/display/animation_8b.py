"""0x8B 3-phase animation protocol (App new send gif cmd 2020).

This is the newer / more robust animation protocol used by all modern
Divoom devices (Timoo, Tivoo Max, Ditoo, Pixoo Max). The 0x8B command
sends an animation in three SPP frames:

    StartSeeding   (control_word=0): [0x00] [file_size LE u32]
    SendingData    (control_word=1): [0x01] [file_size LE u32] [offset_id LE u16] [≤256 bytes data]
    TerminateSending (control_word=2): [0x02]

The animation payload (file_size bytes) is the concatenation of the
per-frame bodies in the 0x49 format:

    AA LLLL TTTT RR NN COLOR_DATA PIXEL_DATA

Each SendingData phase carries up to 256 bytes of that payload, with
an LE u16 offset_id starting from 0.

Source of truth:
  - https://github.com/futpib/divoom-ditoo-pro-controller
    src/protocol/animation.rs (Rust 3-phase encode)
  - https://docin.divoom-gz.com/web/#/5/293 (Divoom protocol doc;
    "App new send gif cmd 2020")

Round 3 finding: the 0x49 chunked protocol is ACK'd by Timoo but
doesn't cycle the animation — the device continues to display the
previously-stored custom animation. Round 4 hypothesis: Timoo
firmware expects 0x8B to actually play a multi-frame animation.

This module implements the encoder + a high-level send helper.
"""
from __future__ import annotations

import logging
from typing import List, Tuple

from divoom_lib.sender_protocol import CommandSender
from divoom_lib.models import COMMANDS
from divoom_lib.utils.divoom_image_encode import (
    encode_animation_frame,
    Frame,
)
from divoom_lib.utils.divoom_image_encode_32 import (
    encode_animation_frame_32,
)

logger = logging.getLogger("divoom_lib")

# Control words (per futpib animation.rs)
CONTROL_START_SENDING = 0x00
CONTROL_SENDING_DATA = 0x01
CONTROL_TERMINATE_SENDING = 0x02

# SPP SendingData phase max payload (per futpib animation.rs:38)
SENDING_DATA_CHUNK_SIZE = 256


def _build_animation_blob(frames: List[Frame]) -> bytes:
    """Concatenate the per-frame bodies into a single blob.

    The 0x8B protocol's file_size = sum of all encoded frame bodies.
    Each body uses the per-frame wire format:
        AA LLLL(LE) TTTT(LE) RR=0x00 NN COLOR_DATA PIXEL_DATA
    (RR=0x00, 1-byte NN for ALL screen sizes — APK confirmed R35d)
    Dispatches on (w, h) to pick the right encoder; 32×32 now uses
    the same standard format as 16×16.
    """
    out = bytearray()
    for (rgb, w, h, t) in frames:
        if w == 32 and h == 32:
            out += encode_animation_frame_32(rgb, w, h, t)
        else:
            out += encode_animation_frame(rgb, w, h, t)
    return bytes(out)


def _phase_start(file_size: int) -> bytes:
    """StartSeeding phase payload (5 bytes)."""
    return bytes([CONTROL_START_SENDING]) + file_size.to_bytes(4, "little")


def _phase_data(file_size: int, offset_id: int, data: bytes) -> bytes:
    """SendingData phase payload (7 + len(data) bytes).

    `offset_id` is the sequential chunk INDEX (0,1,2,...), not a byte offset —
    see build_8b_phases / futpib.
    """
    return (
        bytes([CONTROL_SENDING_DATA])
        + file_size.to_bytes(4, "little")
        + offset_id.to_bytes(2, "little")
        + data
    )


def _phase_terminate() -> bytes:
    """TerminateSending phase payload (1 byte)."""
    return bytes([CONTROL_TERMINATE_SENDING])


def build_8b_phases(frames: List[Frame]) -> List[bytes]:
    """Build the 3-phase SPP payloads for an animation.

    Returns:
        list of 3 byte strings — the raw args to pass to the 0x8B
        command via `send_command`. Each becomes one SPP Basic frame
        on the wire. Order is strict: start, [N x data], terminate.
    """
    if not frames:
        return []
    blob = _build_animation_blob(frames)
    file_size = len(blob)
    phases: List[bytes] = [_phase_start(file_size)]
    # offset_id is the chunk INDEX (0,1,2,...), matching futpib + the live
    # streamer Animation.stream_animation_8b. The device places chunk N at byte
    # N*SENDING_DATA_CHUNK_SIZE, so a byte offset here would leave gaps and stall.
    for index, offset in enumerate(range(0, file_size, SENDING_DATA_CHUNK_SIZE)):
        chunk = blob[offset : offset + SENDING_DATA_CHUNK_SIZE]
        phases.append(_phase_data(file_size, index, chunk))
    phases.append(_phase_terminate())
    return phases


class Animation8B:
    """High-level wrapper for the 0x8B 3-phase animation protocol.

    Usage::

        anim = Animation8B(divoom_instance)
        await anim.send(frames)   # frames from process_image()
    """

    def __init__(self, divoom: CommandSender):
        self.communicator = divoom
        self.logger = divoom.logger

    async def send(self, frames: List[Frame]) -> bool:
        """Send a multi-frame animation to the device via 0x8B.

        Sends:
          1. StartSeeding phase (1 SPP frame)
          2. SendingData phases (N SPP frames, one per 256-byte chunk)
          3. TerminateSending phase (1 SPP frame)
        """
        phases = build_8b_phases(frames)
        if not phases:
            return False
        self.logger.info(
            f"0x8B 3-phase animation: {len(phases)} SPP frames "
            f"({len(phases) - 2} data chunks)"
        )
        for args in phases:
            ok = await self.communicator.send_command(
                COMMANDS["app new send gif cmd"], list(args)
            )
            if not ok:
                self.logger.error(f"0x8B phase failed: args={args.hex()}")
                return False
        return True
