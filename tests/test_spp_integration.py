import sys
from unittest.mock import MagicMock, AsyncMock, patch

# Mock the entire IOBluetooth module to bypass PyObjC limitations
mock_iobluetooth = MagicMock()
sys.modules["IOBluetooth"] = mock_iobluetooth

import pytest
from divoom_lib.divoom import Divoom
from divoom_lib.exceptions import DeviceConnectionError

@pytest.mark.asyncio
async def test_spp_not_routed_for_unknown_protocol():
    """SPP routing does NOT fire when use_ios_le_protocol=None (unknown).
    The autoprobe in BLETransport.connect() determines the protocol dynamically;
    don't pre-empt it with an SPP redirect for a BLE-only device."""
    mock_paired_device = MagicMock()
    mock_paired_device.getName.return_value = "Timoo-audio-4"
    mock_paired_device.getAddressString.return_value = "11-75-58-54-b9-13"
    
    mock_iobluetooth.IOBluetoothDevice.pairedDevices.return_value = [mock_paired_device]

    # BLETransport.__init__ resolves BleakClient via a call-time `from .divoom
    # import BleakClient` (not the ble_transport module-level name), so the
    # patch target is divoom_lib.divoom.BleakClient. Without this, connect()
    # awaits a REAL BleakClient.connect() before any SPP-routing check runs,
    # which on macOS invokes CoreBluetooth directly and SIGABRTs under a shell
    # without Bluetooth TCC authorization (no such device exists at this
    # address anyway — the test wants a clean raise, not a real radio probe).
    # Matching `.address` keeps BLETransport.connect() from discarding this
    # mock and re-instantiating a real client (ble_transport.py only replaces
    # self.client when the address doesn't match).
    with patch("divoom_lib.bt_spp_transport.BTSppTransport") as MockTransport, \
            patch("divoom_lib.divoom.BleakClient") as MockBleakClient:
        mock_ble_client = MockBleakClient.return_value
        mock_ble_client.address = "11-75-58-54-b9-13"
        mock_ble_client.is_connected = False
        mock_ble_client.connect = AsyncMock(side_effect=RuntimeError("no such device"))

        # Construct Divoom with name Timoo, protocol unset (None = autodetect)
        divoom = Divoom(mac="11-75-58-54-b9-13", device_name="Timoo",
                         use_ios_le_protocol=None)

        # BLE connect will be attempted (no SPP routing for unknown protocol)
        # and simulated to fail. The important check: SPP transport was NEVER
        # instantiated.
        with pytest.raises(DeviceConnectionError):
            await divoom.connect()
        MockTransport.assert_not_called()
        assert divoom._conn._use_spp is False

@pytest.mark.asyncio
async def test_spp_connection_resolution():
    """A device with explicit use_ios_le_protocol=False AND a matching classic
    name still routes to SPP transport for legacy Bluetooth Classic devices."""
    mock_paired_device = MagicMock()
    mock_paired_device.getName.return_value = "Timoo-audio-4"
    mock_paired_device.getAddressString.return_value = "11-75-58-54-b9-13"
    
    mock_iobluetooth.IOBluetoothDevice.pairedDevices.return_value = [mock_paired_device]
    
    # Explicitly set use_ios_le_protocol=False (Basic protocol → SPP routing)
    divoom = Divoom(mac="11-75-58-54-b9-13", device_name="Timoo",
                     use_ios_le_protocol=False)
    
    # Mock BTSppTransport connect & properties
    with patch("divoom_lib.bt_spp_transport.BTSppTransport") as MockTransport:
        mock_spp = AsyncMock()
        mock_spp.is_connected = False
        mock_spp.mac_address = "11-75-58-54-b9-13"
        
        async def mock_connect():
            mock_spp.is_connected = True
        mock_spp.connect.side_effect = mock_connect

        MockTransport.return_value = mock_spp
        
        await divoom.connect()
        
        assert divoom._conn._use_spp is True
        assert divoom._conn._spp_client is mock_spp
        mock_spp.connect.assert_called_once()
        
        # Disconnect
        mock_spp.is_connected = False
        await divoom.disconnect()
        mock_spp.disconnect.assert_called_once()

@pytest.mark.asyncio
async def test_spp_send_payload():
    """Verify that sending a command on an active SPP connection routes through the SPP client using basic framing."""
    mock_paired_device = MagicMock()
    mock_paired_device.getName.return_value = "Timoo-audio-4"
    mock_paired_device.getAddressString.return_value = "11-75-58-54-b9-13"
    
    mock_iobluetooth.IOBluetoothDevice.pairedDevices.return_value = [mock_paired_device]
    
    with patch("divoom_lib.bt_spp_transport.BTSppTransport") as MockTransport:
        mock_spp = AsyncMock()
        mock_spp.is_connected = True
        mock_spp.mac_address = "11-75-58-54-b9-13"
        mock_spp.FRAMING_BASIC = "basic"
        mock_spp.FRAMING_IOS_LE = "ios_le"
        MockTransport.return_value = mock_spp
        
        divoom = Divoom(mac="11-75-58-54-b9-13", device_name="Timoo")
        # Connect manually to trigger setup
        divoom._conn._use_spp = True
        divoom._conn._spp_client = mock_spp
        
        # Send a light mode change command (0x45)
        await divoom.display.show_light(color="00FF00", brightness=100)
        
        # Verify it used SPP send
        mock_spp.send.assert_called_once()
        called_args, called_kwargs = mock_spp.send.call_args
        assert called_args[0][0] == 0x45 # set channel light command
        assert called_kwargs.get("framing") == "basic"
