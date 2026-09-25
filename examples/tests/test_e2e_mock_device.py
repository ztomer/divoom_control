"""Hardware-free end-to-end tests.

Inject the `MockBleakClient` (which records every frame the "device" receives)
into a real `Divoom`, drive the high-level Control Center commands, and assert
the exact wire bytes the library produces. This validates the full
bridge → Divoom → framing → GATT-write pipeline that real hardware would
otherwise be needed to confirm — without Bluetooth permission.
"""

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))

from divoom_legacy.divoom import Divoom
from divoom_lib import models, framing
from support.mock_device import MockBleakClient

MAC = "AA:BB:CC:DD:EE:FF"
WRITE_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"


async def _connected_divoom():
    mock = MockBleakClient(MAC)
    dev = Divoom(mac=MAC, client=mock, use_ios_le_protocol=False)
    await dev.connect()
    mock.written.clear()  # drop connection-time chatter
    return dev, mock


def _decoded_frames(mock):
    """Parse every recorded write with the library's own parser."""
    out = []
    for _char, data in mock.written:
        msgs, _ = framing.parse_basic_protocol_frames(bytearray(data))
        out.extend(msgs)
    return out


@pytest.mark.asyncio
async def test_connect_uses_injected_mock():
    dev, mock = await _connected_divoom()
    assert dev.is_connected is True
    assert dev.client is mock  # not replaced by a real BleakClient




@pytest.mark.asyncio
async def test_show_effects_lan_unsupported():
    """VJ effects should return False and warn on LAN devices."""
    mock = MockBleakClient(MAC)
    # Instantiate with a dummy lan_ip to simulate a Wi-Fi/LAN device
    dev = Divoom(mac=MAC, client=mock, lan_ip="192.168.1.100", use_ios_le_protocol=False)
    assert dev.display.communicator.lan is not None
    
    ok = await dev.display.show_effects(number=5)
    assert ok is False
    
    ok_switch = await dev.display.switch_channel("vj")
    assert ok_switch is False


















@pytest.mark.asyncio
async def test_weather_set_rejects_out_of_range():
    """Temps outside -127..128 raise ValueError."""
    dev, _ = await _connected_divoom()
    from divoom_legacy.system.weather import Weather
    w = Weather(dev)
    with pytest.raises(ValueError):
        await w.set(200, 1)






@pytest.mark.asyncio
async def test_watchface_roundtrip_script_e2e(monkeypatch):
    """Verify that verify_device in the watchface roundtrip script successfully
    interacts with the Divoom facade using MockBleakClient."""
    from test_watchface_roundtrip import verify_device
    
    original_divoom_init = Divoom.__init__
    
    def mock_divoom_init(self, *args, **kwargs):
        kwargs["client"] = MockBleakClient(kwargs.get("mac", "AA:BB:CC:DD:EE:FF"))
        original_divoom_init(self, *args, **kwargs)
        
    monkeypatch.setattr(Divoom, "__init__", mock_divoom_init)
    
    success = await verify_device("AA:BB:CC:DD:EE:FF", "MockDevice", dial=3)
    assert success is True


