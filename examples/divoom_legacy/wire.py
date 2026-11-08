"""Write the two Divoom wire framings, for the retired library only.

`divoom_lib.framing` parses and no longer frames (L4c, ae43751): the daemon
frames with `divoomd::framing`, and `tests/test_no_native_encoder_chain.py`
keeps a Python encoder out of every shipped package. This retired library
talks to a device directly, so it needs one of its own. It lives here, outside
the wheel, and `examples/tests/test_legacy_wire.py` holds it byte for byte to
`divoomd/tests/framing_vectors.json`, the C library's recorded output that the
daemon asserts too, so the two cannot drift apart unnoticed.
"""

from divoom_lib import models


def int2hexlittle(value: int) -> str:
    return f"{value & 0xFF:02x}{(value >> 8) & 0xFF:02x}"


def escape_payload(payload_bytes: list) -> list:
    escapes = {
        models.ESCAPE_BYTE_1: models.ESCAPE_SEQUENCE_1,
        models.ESCAPE_BYTE_2: models.ESCAPE_SEQUENCE_2,
        models.ESCAPE_BYTE_3: models.ESCAPE_SEQUENCE_3,
    }
    out: list = []
    for b in payload_bytes:
        if b in escapes:
            out.extend(escapes[b])
        else:
            out.append(b)
    return out


def get_checksum(data_bytes: list) -> str:
    return int2hexlittle(sum(data_bytes))


def encode_basic_payload(payload_bytes: list, escape: bool = False) -> bytes:
    """`[01][len lo hi][body][cksum lo hi][02]`; len counts body + checksum."""
    body = bytes(escape_payload(payload_bytes) if escape else payload_bytes)
    length = len(body) + models.MESSAGE_CHECKSUM_LENGTH
    head = bytes([length & 0xFF, (length >> 8) & 0xFF]) + body
    checksum = sum(head) & 0xFFFF
    return bytes([models.MESSAGE_START_BYTE]) + head + bytes([checksum & 0xFF, checksum >> 8, models.MESSAGE_END_BYTE])


def encode_ios_le_payload(payload_bytes: list, packet_number: int = 0) -> bytes:
    """`[FE EF AA 55][len lo hi][pkt][cmd][data][cksum lo hi][02]`; len = total - 7."""
    if not payload_bytes:
        raise ValueError("payload must contain at least the command id")
    total = len(payload_bytes) + 10
    out = bytearray(models.IOS_LE_HEADER)
    out += bytes([(total - 7) & 0xFF, ((total - 7) >> 8) & 0xFF, packet_number & 0xFF])
    out += bytes(payload_bytes)
    checksum = sum(out[4:]) & 0xFFFF
    out += bytes([checksum & 0xFF, checksum >> 8, models.MESSAGE_END_BYTE])
    return bytes(out)
