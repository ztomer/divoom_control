# divoom_lib/__init__.py

from .exceptions import (
    DivoomError,
    DeviceAddressMissingError,
    CharacteristicConfigError,
    DeviceConnectionError,
)
from .transport import Transport, via, COMMAND_TRANSPORT_MAP, transport_for

def __getattr__(name):
    if name == "Divoom":
        from .divoom import Divoom
        return Divoom
    if name == "LanTransport":
        from .lan_transport import LanTransport
        return LanTransport
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "Divoom",
    "LanTransport",
    "Transport",
    "via",
    "COMMAND_TRANSPORT_MAP",
    "transport_for",
    "DivoomError",
    "DeviceAddressMissingError",
    "CharacteristicConfigError",
    "DeviceConnectionError",
]
