from typing import List, Tuple
import ctypes
from pathlib import Path

from . import models
from .native_lib import library_path

# Upper bound on a single basic-protocol RX frame (header + 2-byte length). Real
# device response frames are tiny; a larger decoded length means the length field
# is corrupt, used to resync the parser instead of stalling. See
# parse_basic_protocol_frames.
MAX_BASIC_FRAME = 8192

# Dynamically load native C shared library for fast payload escaping/framing if available
lib = None
try:
    lib_path = library_path()
    if lib_path.exists():
        lib = ctypes.CDLL(str(lib_path))
        lib.encode_basic_payload.argtypes = [
            ctypes.POINTER(ctypes.c_ubyte),  # const unsigned char* payload
            ctypes.c_int,                    # int payload_len
            ctypes.c_int,                    # int escape
            ctypes.POINTER(ctypes.c_ubyte)   # unsigned char* out_msg
        ]
        lib.encode_basic_payload.restype = ctypes.c_int

        lib.encode_ios_le_payload.argtypes = [
            ctypes.POINTER(ctypes.c_ubyte),  # const unsigned char* payload
            ctypes.c_int,                    # int payload_len
            ctypes.c_int,                    # int packet_number
            ctypes.POINTER(ctypes.c_ubyte)   # unsigned char* out_msg
        ]
        lib.encode_ios_le_payload.restype = ctypes.c_int

except Exception:
    pass


def int2hexlittle(value: int) -> str:
    byte1 = (value & 0xFF)
    byte2 = ((value >> 8) & 0xFF)
    return f"{byte1:02x}{byte2:02x}"


def escape_payload(payload_bytes: list) -> list:
    escaped = []
    for b in payload_bytes:
        if b == models.ESCAPE_BYTE_1:
            escaped.extend(models.ESCAPE_SEQUENCE_1)
        elif b == models.ESCAPE_BYTE_2:
            escaped.extend(models.ESCAPE_SEQUENCE_2)
        elif b == models.ESCAPE_BYTE_3:
            escaped.extend(models.ESCAPE_SEQUENCE_3)
        else:
            escaped.append(b)
    return escaped


def get_checksum(data_bytes: list) -> str:
    sum_val = sum(data_bytes)
    return int2hexlittle(sum_val)


def encode_basic_payload(payload_bytes: list, escape: bool = False) -> bytes:
    if lib is not None:
        try:
            payload_data = bytes(payload_bytes)
            n = len(payload_data)
            out_size = 2 * n + 6
            out_buf = (ctypes.c_ubyte * out_size)()
            in_buf = (ctypes.c_ubyte * n).from_buffer_copy(payload_data)
            
            written = lib.encode_basic_payload(in_buf, n, 1 if escape else 0, out_buf)
            if written > 0:
                return bytes(out_buf[:written])
        except Exception:
            pass

    n = len(payload_bytes)
    max_size = 6 + (2 * n if escape else n)
    buf = bytearray(max_size)
    mv = memoryview(buf)
    
    mv[0] = models.MESSAGE_START_BYTE
    
    idx = 3
    if escape:
        esc1, esc2, esc3 = models.ESCAPE_BYTE_1, models.ESCAPE_BYTE_2, models.ESCAPE_BYTE_3
        # bytes(), not list — assigning a list to a memoryview slice raises
        # TypeError (the C path normally masks this; see test_framing_both_impls).
        seq1 = bytes(models.ESCAPE_SEQUENCE_1)
        seq2 = bytes(models.ESCAPE_SEQUENCE_2)
        seq3 = bytes(models.ESCAPE_SEQUENCE_3)
        for b in payload_bytes:
            if b == esc1:
                mv[idx:idx+2] = seq1
                idx += 2
            elif b == esc2:
                mv[idx:idx+2] = seq2
                idx += 2
            elif b == esc3:
                mv[idx:idx+2] = seq3
                idx += 2
            else:
                mv[idx] = b
                idx += 1
    else:
        mv[idx:idx+n] = bytes(payload_bytes)
        idx += n
        
    working_payload_len = idx - 3
    length_value = working_payload_len + models.MESSAGE_CHECKSUM_LENGTH
    
    mv[1] = length_value & 0xFF
    mv[2] = (length_value >> 8) & 0xFF
    
    checksum = sum(mv[1:idx]) & 0xFFFF
    
    mv[idx] = checksum & 0xFF
    mv[idx+1] = (checksum >> 8) & 0xFF
    mv[idx+2] = models.MESSAGE_END_BYTE
    
    return bytes(mv[:idx+3])


def encode_ios_le_payload(payload_bytes: list, packet_number: int = 0x00000000) -> bytes:
    """
    Encode a command in the official Divoom iOS-LE protocol format.

    Layout (from the official APK ``com.divoom.Divoom.bluetooth.c#b``):
        [0xFE, 0xEF, 0xAA, 0x55]                 (4-byte header)
        [len_lo, len_hi]                          (len = total_bytes - 7, little-endian)
        [packet_number_byte]                      (1 byte — only the low byte is transmitted)
        [command_id]                              (1 byte, separate from the data payload)
        [data...]                                 (raw data WITHOUT the command id)
        [checksum_lo, checksum_hi]                (sum of bytes 4..end-3, little-endian)
        [0x02]                                    (end marker)
    """
    if not payload_bytes:
        raise ValueError("payload_bytes must contain at least the command id")

    if lib is not None:
        try:
            payload_data = bytes(payload_bytes)
            n = len(payload_data)
            out_size = n + 10
            out_buf = (ctypes.c_ubyte * out_size)()
            in_buf = (ctypes.c_ubyte * n).from_buffer_copy(payload_data)
            
            written = lib.encode_ios_le_payload(in_buf, n, packet_number, out_buf)
            if written > 0:
                return bytes(out_buf[:written])
        except Exception:
            pass

    n = len(payload_bytes)
    total_len = n + 10
    buf = bytearray(total_len)
    mv = memoryview(buf)
    
    mv[0:4] = bytes(models.IOS_LE_MESSAGE_HEADER)  # bytes(), not list (memoryview slice)
    
    length_field = total_len - 7
    mv[4] = length_field & 0xFF
    mv[5] = (length_field >> 8) & 0xFF
    
    packet_number_byte = packet_number & 0xFF
    mv[6] = packet_number_byte
    
    command_identifier = payload_bytes[0]
    mv[7] = command_identifier
    
    if n > 1:
        mv[8:8+n-1] = bytes(payload_bytes[1:])
        
    checksum = sum(mv[4:n+7]) & 0xFFFF
    
    idx = n + 7
    mv[idx] = checksum & 0xFF
    mv[idx+1] = (checksum >> 8) & 0xFF
    mv[idx+2] = models.MESSAGE_END_BYTE
    
    return bytes(mv)



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
