"""The retired library's SEND path frames bytes the device accepts (D.LEGACY).

L4c (ae43751) took the Python encoder out of `divoom_lib/framing.py` and
`tests/test_no_native_encoder_chain.py` keeps it out of every SHIPPED package.
`examples/divoom_legacy` still called `divoom_lib.framing.encode_*`, so every
live send from the retired library (and the example scripts that drive it)
raised AttributeError, and no test noticed because every legacy test mocked
the send. The retired library now frames through its own `divoom_legacy.wire`,
held here byte for byte to the vectors recorded from the C library
(`divoomd/tests/framing_vectors.json`, the same ones the daemon asserts) and
driven end to end through a fake BLE client, not a mock of the encoder.
"""

import asyncio
import json
import logging
from pathlib import Path

import pytest

from divoom_lib import models
from divoom_legacy import wire
from divoom_legacy.ble_transport import BLETransport

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "divoomd/tests/framing_vectors.json").read_text())


class FakeClient:
    """A BLE client that records what was written and is always connected."""

    is_connected = True
    address = "AA:BB:CC:DD:EE:FF"

    def __init__(self) -> None:
        self.writes: list[bytes] = []

    async def write_gatt_char(self, _uuid, data, response=False) -> None:
        self.writes.append(bytes(data))


def transport(escape: bool = False) -> tuple[BLETransport, FakeClient]:
    client = FakeClient()
    cfg = models.DivoomConfig(mac="AA:BB:CC:DD:EE:FF", client=client, escapePayload=escape)
    return BLETransport(cfg, logging.getLogger(__name__)), client


@pytest.mark.parametrize("vec", VECTORS["encode_basic"], ids=lambda v: f"basic-{len(v['payload'])}-{v['escape']}")
def test_basic_encoder_matches_the_recorded_vectors(vec) -> None:
    assert wire.encode_basic_payload(vec["payload"], escape=vec["escape"]).hex() == vec["out"]


@pytest.mark.parametrize("vec", VECTORS["encode_ios_le"], ids=lambda v: f"ios-{len(v['payload'])}-{v['packet']}")
def test_ios_le_encoder_matches_the_recorded_vectors(vec) -> None:
    assert wire.encode_ios_le_payload(vec["payload"], packet_number=vec["packet"]).hex() == vec["out"]


def test_ios_le_send_writes_the_framed_bytes() -> None:
    vec = next(v for v in VECTORS["encode_ios_le"] if v["packet"] == 0 and len(v["payload"]) > 3)
    t, client = transport()
    assert asyncio.run(t._send_ios_le_payload(vec["payload"], False)) is True
    assert b"".join(client.writes).hex() == vec["out"]


@pytest.mark.parametrize("escape", [False, True])
def test_basic_send_writes_the_framed_bytes_chunked(escape: bool) -> None:
    vec = max((v for v in VECTORS["encode_basic"] if v["escape"] == escape), key=lambda v: len(v["payload"]))
    t, client = transport(escape)
    assert asyncio.run(t._send_basic_protocol_payload(vec["payload"], False)) is True
    assert b"".join(client.writes).hex() == vec["out"]


def test_facade_helpers_resolve() -> None:
    from divoom_legacy.divoom import Divoom

    from types import SimpleNamespace

    d = Divoom.__new__(Divoom)
    d._conn = SimpleNamespace(escapePayload=False)
    assert d._int2hexlittle(0x1234) == "3412"
    assert d._getCRC([0xFF, 0x02]) == "0101"
    assert d._escape_payload([0x01, 0x05]) == list(models.ESCAPE_SEQUENCE_1) + [0x05]
    vec = VECTORS["encode_basic"][3]
    d.escapePayload = vec["escape"]
    assert d._make_message(vec["payload"]).hex() == vec["out"]
    ios = VECTORS["encode_ios_le"][0]
    assert d._make_message_ios_le(ios["payload"], ios["packet"]).hex() == ios["out"]
