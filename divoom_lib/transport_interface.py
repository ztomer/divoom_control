# divoom_lib/transport_interface.py

import logging
from typing import Protocol, runtime_checkable, Optional, Any

@runtime_checkable
class DeviceTransport(Protocol):
    """ Authoritative interface representing Divoom connection & transport layers. """

    logger: logging.Logger

    @property
    def is_connected(self) -> bool:
        """ Returns True if the transport link is active. """
        ...

    async def connect(self) -> None:
        """ Establishes connection over this transport. """
        ...

    async def disconnect(self) -> None:
        """ Terminates connection and clean up resources. """
        ...

    async def send_frame(self, frame: bytes) -> None:
        """ Write an ALREADY-FRAMED message to the device.

        Deliberately not `send_command(command, args)`: framing is the daemon's
        job (`divoomd::spp_bridge_protocol`, the same encoder the BLE path
        uses, pinned against the C library's own bytes by 550 vectors in
        `divoomd/tests/framing_vectors.json`). A transport interface whose send
        takes a command name and args has to own a second encoder to honour it,
        and two encoders for one protocol is a device that behaves differently
        depending on which radio reached it. This one moves bytes.
        """
        ...

    async def wait_for_response(self, command_id: int, timeout: float = 10.0) -> Optional[bytes]:
        """ Await notification response for a command ID. """
        ...
