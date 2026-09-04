# divoom_lib/spp_connection.py

import logging
from typing import Any

logger = logging.getLogger("divoom_lib")

def resolve_classic_mac(name: str, mac_or_uuid: str, log=None) -> str | None:
    """Resolves Classic Bluetooth MAC address using IOBluetooth on macOS."""
    if log is None:
        log = logger
    if mac_or_uuid and len(mac_or_uuid) == 17 and ("-" in mac_or_uuid or ":" in mac_or_uuid):
        return mac_or_uuid.replace(":", "-")
    try:
        from IOBluetooth import IOBluetoothDevice
        paired = IOBluetoothDevice.pairedDevices() or []
        if name:
            for dev in paired:
                dev_name = dev.getName()
                if dev_name and dev_name.lower() == name.lower():
                    return dev.getAddressString()
        if name:
            for dev in paired:
                dev_name = dev.getName()
                if dev_name and (name.lower() in dev_name.lower() or dev_name.lower() in name.lower()):
                    return dev.getAddressString()
        if name:
            base_name = name.split("-")[0].split(" ")[0].lower()
            for dev in paired:
                dev_name = dev.getName()
                if dev_name and base_name in dev_name.lower():
                    return dev.getAddressString()
    except Exception as e:
        log.warning(f"Failed to resolve Classic MAC address via IOBluetooth: {e}")
    return None

# read_spp_notifications_loop / disconnect_spp were dead (superseded by
# BTSppTransport._rx_loop / .disconnect) — removed R53.12.
