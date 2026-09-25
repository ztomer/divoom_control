"""Reading the two Divoom wire framings.

This module used to also WRITE them, through `libdivoom_compact.dylib` — a C
library whose sources and compiled binary were committed to this repository and
rebuilt by `scripts/build_libdivoom.sh`. Both are gone as of 2026-09-25
(phase L4): the daemon frames with `divoomd::framing`, the same encoder the
BLE path uses, and `divoom_client/spp_bridge.py` writes the exact bytes it is
handed. The C library's recorded behaviour survives as 550 vectors in
`divoomd/tests/framing_vectors.json`, which the Rust side asserts byte for
byte — including a dense length sweep, because that is where a framing bug
lives.

So what is left here is the half Python genuinely still owns: PARSING what the
device sends. The co-process reads notifications over the same link, and there
is no reason for a second implementation of that to be written in Rust for a
process whose entire job is to move bytes.

`tests/test_no_native_encoder_chain.py` fails the build if any of this comes
back: a tracked `.dylib`/`.so`/`.c`, a `native_lib` import, or a
`pyproject.toml` glob that ships native binaries.
"""

from typing import List, Tuple

from . import models

# Upper bound on a single basic-protocol RX frame (header + 2-byte length). Real
# device response frames are tiny; a larger decoded length means the length field
# is corrupt, used to resync the parser instead of stalling. See
# parse_basic_protocol_frames.
MAX_BASIC_FRAME = 8192


def parse_ios_le_notification(data: bytes) -> dict | None:
    """
    Parse a notification sent in the official Divoom iOS-LE protocol format.

    Layout matches ``encode_ios_le_payload``. The data section begins at
    ``IOS_LE_DATA_OFFSET`` (8) and runs up to ``-IOS_LE_CHECKSUM_LENGTH``;
    the command id lives at ``IOS_LE_COMMAND_IDENTIFIER`` (7) — *not* 6 as
    the previous constants claimed. The packet number is a single byte at
    offset 6.
    """
    if len(data) < models.IOS_LE_MIN_DATA_LENGTH:
        return None
    if data[0:4] != bytes(models.IOS_LE_HEADER):
        return None
    if data[-1] != models.MESSAGE_END_BYTE:
        return None
    command_id = data[models.IOS_LE_COMMAND_IDENTIFIER]
    packet_number = data[models.IOS_LE_PACKET_NUMBER]
    # Payload sits between the data offset and the (checksum + end marker).
    payload = bytes(
        data[models.IOS_LE_DATA_OFFSET : -models.IOS_LE_CHECKSUM_LENGTH - 1]
    )
    checksum = int.from_bytes(
        data[-models.IOS_LE_CHECKSUM_LENGTH - 1:-1], byteorder="little"
    )
    return {
        "command_id": command_id,
        "payload": payload,
        "packet_number": packet_number,
        "checksum": checksum,
    }


def parse_basic_protocol_frames(buf: bytearray) -> Tuple[list, bytearray]:
    messages = []

    while len(buf) >= 7:
        try:
            start_index = buf.index(models.MESSAGE_START_BYTE)
        except ValueError:
            buf.clear()
            break

        if start_index > 0:
            del buf[:start_index]

        if len(buf) < 4:
            break

        length = int.from_bytes(buf[1:3], byteorder='little')
        total_message_len = 4 + length

        # A corrupt 2-byte length (line noise / firmware glitch) would otherwise
        # make us wait for up to ~64KB before the end-byte/checksum check could
        # reject it — stalling all RX behind the bogus frame. Real response frames
        # are tiny; anything over the bound is a bad header, so resync past this
        # start byte instead of waiting. (Shared by BLE + SPP basic-protocol RX.)
        if total_message_len > MAX_BASIC_FRAME:
            del buf[0]
            continue

        if len(buf) < total_message_len:
            break

        message = bytes(buf[:total_message_len])
        del buf[:total_message_len]

        if message[-1] != models.MESSAGE_END_BYTE:
            continue

        if len(message) > 5 and message[3] == models.ACK_PATTERN_BYTE_1 and message[5] == models.ACK_PATTERN_BYTE_3:
            command_id = message[4]
            payload = message[6:-3]
        else:
            command_id = message[3]
            payload = message[4:-3]

        checksum_input = message[1:-3]
        # Mask to 16 bits to match the encoder (encode_basic_payload uses
        # `& 0xFFFF`); without this, large frames (e.g. images) whose checksum
        # overflows 16 bits were wrongly rejected.
        calculated_checksum = sum(checksum_input) & 0xFFFF
        received_checksum = int.from_bytes(bytes(message[-3:-1]), byteorder='little')
        if received_checksum != calculated_checksum:
            continue

        messages.append({'command_id': command_id, 'payload': bytearray(payload)})

    return messages, buf
