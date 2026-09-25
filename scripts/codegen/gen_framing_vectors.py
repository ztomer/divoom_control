#!/usr/bin/env python3
"""Generate ground-truth framing vectors from the Python implementation, so the
Rust daemon (divoomd) can assert byte-for-byte parity in its tests.

    PYTHONPATH=<repo root> python3 scripts/codegen/gen_framing_vectors.py

Writes divoomd/tests/framing_vectors.json. Re-run whenever the Python
framing changes; the Rust tests then pin the new behavior. The Python framing is
the AUTHORITATIVE source (parallel-build strategy — see docs/ROADMAP.md).
"""
import json
from pathlib import Path

from divoom_lib import framing


def _h(b) -> str:
    return bytes(b).hex()


def encode_basic_cases():
    cases = []
    inputs = [
        ([], False), ([], True),
        ([0x46], False), ([0x46], True),
        ([0x44, 0x00, 0x0A], False),
        # payloads that hit every escape byte (0x01/0x02/0x03), escape on AND off
        ([0x01, 0x02, 0x03], False), ([0x01, 0x02, 0x03], True),
        ([0x74, 0x01, 0x02, 0x03, 0xFF], True),
        (list(range(0, 16)), False), (list(range(0, 16)), True),
        # a larger payload whose checksum overflows 16 bits (mask path)
        ([0xFF] * 600, False),
    ]
    # A DENSE length sweep, added when the C library was about to be deleted
    # (L4) and these vectors became the only surviving evidence of what the C
    # produced. The ten hand-picked cases above say what someone thought to try;
    # the sweep says what the encoder does at EVERY length up to a full escape
    # window, which is where a length-dependent bug would live -- an off-by-one
    # in the 16-bit length field, a checksum that wraps at 255/256, an escape
    # that fires one byte early. It is 81 more cases per direction, cheap to
    # assert forever, and it is generated from the same C bytes as the rest.
    for length in range(0, 81):
        payload = [(i * 7 + length) % 256 for i in range(length)]
        for escape in (False, True):
            inputs.append((payload, escape))
    # And the escape bytes at EVERY position in a short payload, because escape
    # framing is position-sensitive: 0x01/0x02/0x03 become 0x01 0x01 / 0x02 0x02
    # / 0x03 0x03, and an off-by-one there corrupts a frame silently.
    for pos in range(0, 12):
        for trigger in (0x01, 0x02, 0x03):
            payload = [0x46] * 12
            payload[pos] = trigger
            inputs.append((payload, True))
    for payload, escape in inputs:
        out = framing.encode_basic_payload(payload, escape=escape)
        cases.append({"payload": payload, "escape": escape, "out": _h(out)})
    return cases


def encode_ios_le_cases():
    cases = []
    inputs = [
        ([0x46], 0),
        ([0x46], 1),
        ([0x46, 0x00], 0),
        ([0x8B, 0x01, 0x02, 0x03], 0),
        ([0x46, 0xAA, 0xBB, 0xCC], 0x1234),   # only low byte (0x34) is transmitted
        ([0x46], 0xFF),
        (list(range(0x40, 0x60)), 7),
    ]
    # The same dense length sweep as `encode_basic_cases`, for the same reason:
    # the length field is computed from the payload and the packet number rides
    # in one byte of it, so length and packet interact. Every length 0..=80 with
    # a packet number that is deliberately awkward (0, 1, 0xFF, and one that
    # forces a length-byte carry) rather than a single lucky value.
    for length in range(1, 81):
        # From 1, not 0: this encoder REFUSES an empty payload (no command id to
        # frame), which is a refusal rather than a byte string and so cannot be a
        # vector. The refusal itself is pinned in the Rust test.
        payload = [(i * 11 + length) % 256 for i in range(length)]
        for packet in (0, 1, 0xFF, 0x1234):
            inputs.append((payload, packet))
    for payload, packet in inputs:
        out = framing.encode_ios_le_payload(payload, packet_number=packet)
        cases.append({"payload": payload, "packet": packet, "out": _h(out)})
    return cases


def parse_ios_le_cases():
    cases = []
    raws = []
    # round-trips of valid frames
    for payload, packet in [([0x46], 0), ([0x46, 0xAA, 0xBB], 3), ([0x8B, 0x01], 0xFF)]:
        raws.append(framing.encode_ios_le_payload(payload, packet_number=packet))
    # edge cases: too short, bad header, bad end byte
    raws.append(b"\xfe\xef\xaa\x55\x00\x00")                       # < min len
    raws.append(b"\x00\x00\x00\x00\x04\x00\x00\x46\x49\x00\x02")   # bad header
    valid = framing.encode_ios_le_payload([0x46], packet_number=0)
    raws.append(bytes(valid[:-1]) + b"\x99")                       # bad end byte
    for raw in raws:
        res = framing.parse_ios_le_notification(bytes(raw))
        if res is not None:
            res = {
                "command_id": res["command_id"],
                "payload": _h(res["payload"]),
                "packet_number": res["packet_number"],
                "checksum": res["checksum"],
            }
        cases.append({"in": _h(raw), "result": res})
    return cases


def parse_basic_cases():
    cases = []
    raws = []
    # single valid frames (round-trips)
    raws.append(bytes(framing.encode_basic_payload([0x46])))
    raws.append(bytes(framing.encode_basic_payload([0x44, 0x01, 0x02, 0x03], escape=True)))
    # two frames concatenated in one buffer
    raws.append(bytes(framing.encode_basic_payload([0x46]))
                + bytes(framing.encode_basic_payload([0x74, 0x3C])))
    # leading garbage before a valid frame (resync on start byte)
    raws.append(b"\xaa\xbb\xcc" + bytes(framing.encode_basic_payload([0x46])))
    # an incomplete trailing frame (kept as remainder)
    full = bytes(framing.encode_basic_payload([0x46, 0x11, 0x22, 0x33]))
    raws.append(full[:-2])
    # corrupt 2-byte length (huge) → resync past the start byte
    raws.append(b"\x01\xff\xff\x00\x00\x00\x00")
    # ACK-pattern frame: byte[3]==0x04 and byte[5]==0x55, valid checksum
    body = [0x04, 0x46, 0x55, 0xDE, 0xAD]   # -> command_id=message[4]=0x46
    length = len(body) + 2
    frame = bytearray([0x01, length & 0xFF, (length >> 8) & 0xFF]) + bytes(body)
    cks = sum(frame[1:]) & 0xFFFF
    frame += bytes([cks & 0xFF, (cks >> 8) & 0xFF, 0x02])
    raws.append(bytes(frame))
    # garbage with no start byte at all → cleared, empty remainder
    raws.append(b"\x00\xaa\xbb\xcc\xdd\xee\xff")
    for raw in raws:
        buf = bytearray(raw)
        msgs, remainder = framing.parse_basic_protocol_frames(buf)
        cases.append({
            "in": _h(raw),
            "messages": [{"command_id": m["command_id"], "payload": _h(m["payload"])} for m in msgs],
            "remainder": _h(remainder),
        })
    return cases


def main():
    out = {
        "encode_basic": encode_basic_cases(),
        "encode_ios_le": encode_ios_le_cases(),
        "parse_ios_le": parse_ios_le_cases(),
        "parse_basic": parse_basic_cases(),
    }
    # scripts/codegen/gen_framing_vectors.py -> repo root is three parents up.
    # It was two, which resolved to scripts/divoomd/ -- a directory that does
    # not exist, created by mkdir and written into: the generator printed a
    # success line and produced a file no test has ever read. Same bug and the
    # same fix as gen_commands.py; a generator whose output path is wrong is
    # indistinguishable from one that is not being run.
    dest = (
        Path(__file__).resolve().parent.parent.parent
        / "divoomd" / "tests" / "framing_vectors.json"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2))
    n = sum(len(v) for v in out.values())
    print(f"wrote {n} vectors -> {dest}")


if __name__ == "__main__":
    main()
