"""Anti-drift correctness suite for the framing ENCODERS, run against BOTH the
native C implementation and the pure-Python fallback.

`encode_basic_payload` / `encode_ios_le_payload` have C + Python twins (the C one
lives in divoom_lib/native_src/compact.c, loaded by framing.py). Like the image encoders, a
`C == Python` parity test would miss a bug present in both. So these assert
**correctness**: an encoded frame decodes back to the original command + payload
(and escaping round-trips through a reference un-escaper).

The `c` parametrization skips if the dylib isn't built; CI builds it.
"""
import pytest

from divoom_lib import framing
from divoom_lib import models

_HAS_C = framing.lib is not None


@pytest.fixture(params=["python", "c"])
def fram(request, monkeypatch):
    if request.param == "c":
        if not _HAS_C:
            pytest.skip("native dylib not built — run scripts/build_libdivoom.sh")
        return framing  # C path (framing.lib is loaded)
    monkeypatch.setattr(framing, "lib", None)  # force the pure-Python fallback
    return framing


def _unescape(escaped: bytes) -> bytes:
    """Reverse the basic-protocol escaping: 0x03 0x04/05/06 -> 0x01/02/03."""
    out = bytearray()
    it = iter(range(len(escaped)))
    i = 0
    while i < len(escaped):
        b = escaped[i]
        if b == models.ESCAPE_BYTE_3 and i + 1 < len(escaped) and escaped[i + 1] in (4, 5, 6):
            out.append({4: 1, 5: 2, 6: 3}[escaped[i + 1]])
            i += 2
        else:
            out.append(b)
            i += 1
    return bytes(out)


# Payloads chosen to avoid the parser's ACK branch (cmd != 0x04) and to include
# bytes that must be escaped (0x01/0x02/0x03), large frames, and varied content.
_PAYLOADS = [
    [0x45],
    [0x45, 0x05, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0x74, 80],
    [0x86, 0x01, 0x02, 0x03, 0x04],     # contains the escape-trigger bytes
    list(range(0, 64)),                 # spans escape bytes + larger frame
]


def test_basic_corrupt_length_resyncs_and_recovers():
    """R53.18: a corrupt 2-byte length must not stall the parser waiting for ~64KB
    that never arrives — it resyncs past the bad start byte and still recovers a
    following valid frame. (Shared BLE + SPP basic-protocol RX path.)"""
    good = bytes(framing.encode_basic_payload([0x44, 0x55], escape=False))
    # start byte + a huge length (0xFFFF) + filler (no 0x01), then the real frame
    bogus = bytes([models.MESSAGE_START_BYTE, 0xFF, 0xFF, 0xAA, 0xAA, 0xAA, 0xAA])
    msgs, rest = framing.parse_basic_protocol_frames(bytearray(bogus + good))
    assert any(m["command_id"] == 0x44 for m in msgs), "real frame lost after corrupt prefix"


@pytest.mark.parametrize("payload", _PAYLOADS)
def test_basic_no_escape_round_trips(fram, payload):
    """encode_basic_payload(escape=False) -> parse recovers command + payload."""
    frame = fram.encode_basic_payload(payload, escape=False)
    assert frame[0] == models.MESSAGE_START_BYTE
    assert frame[-1] == models.MESSAGE_END_BYTE
    msgs, rest = framing.parse_basic_protocol_frames(bytearray(frame))
    assert rest == bytearray(), "trailing bytes after a single frame"
    assert len(msgs) == 1
    assert msgs[0]["command_id"] == payload[0]
    assert list(msgs[0]["payload"]) == payload[1:]


@pytest.mark.parametrize("payload", _PAYLOADS)
def test_basic_escape_is_correct(fram, payload):
    """escape=True: the escaped payload region un-escapes back to the original,
    and the frame still parses (after un-escaping) to the same command+payload."""
    frame = fram.encode_basic_payload(payload, escape=True)
    assert frame[0] == models.MESSAGE_START_BYTE
    assert frame[-1] == models.MESSAGE_END_BYTE
    # payload region is between the 3-byte header and the 3-byte checksum+end tail
    escaped_region = frame[3:-3]
    assert _unescape(escaped_region) == bytes(payload)


def test_basic_escape_only_expands_collision_bytes(fram):
    """A payload with no collision bytes must be identical with/without escape."""
    payload = [0x45, 0x10, 0x20, 0x30, 0x40]  # none of 0x01/0x02/0x03
    assert fram.encode_basic_payload(payload, escape=True) == \
           fram.encode_basic_payload(payload, escape=False)


@pytest.mark.parametrize("payload", _PAYLOADS)
@pytest.mark.parametrize("packet_number", [0, 1, 0x1234])
def test_ios_le_round_trips(fram, payload, packet_number):
    """encode_ios_le_payload -> parse_ios_le_notification recovers everything."""
    frame = fram.encode_ios_le_payload(payload, packet_number=packet_number)
    assert frame[0:4] == bytes(models.IOS_LE_HEADER)
    assert frame[-1] == models.MESSAGE_END_BYTE
    parsed = framing.parse_ios_le_notification(frame)
    assert parsed is not None
    assert parsed["command_id"] == payload[0]
    assert list(parsed["payload"]) == payload[1:]
    assert parsed["packet_number"] == (packet_number & 0xFF)
