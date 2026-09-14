"""divoom_legacy — the direct-to-device Python library, retired from the product.

Everything under this package used to be `divoom_lib.*`: the `Divoom` facade,
the BLE/LAN/SPP transports, the display/system/tools/scheduling command
groups, the Python encoders. Nothing the shipped product (the `divoomd`
daemon, `divoom_client`, the GUI, `nowplaying`) imports any of it; the daemon
owns those capabilities now. It lives here so `examples/` stays runnable and
the protocol knowledge stays readable, and it depends on the retained
`divoom_lib` core (framing, models, transport, auth, native_lib) — never the
other way round.

    PYTHONPATH=examples:. python3 examples/discover_and_connect.py
    python3 -m pytest examples/tests -q
"""
from divoom_lib.exceptions import (  # noqa: F401 — the names examples expect here
    CharacteristicConfigError,
    DeviceAddressMissingError,
    DeviceConnectionError,
    DivoomError,
)
from divoom_lib.transport import COMMAND_TRANSPORT_MAP, Transport, transport_for, via  # noqa: F401


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
