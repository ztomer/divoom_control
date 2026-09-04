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

    async def send_command(
        self, command: int | str, args: list | None = None, write_with_response: bool = False
    ) -> bool:
        """ Format and send command to the device. """
        ...

    async def send_payload(self, payload_bytes: list, max_retries: int = 3, **kwargs) -> bool:
        """ Sends a framed command payload. """
        ...

    async def send_command_and_wait_for_response(
        self, command: int | str, args: list | None = None, timeout: float = 10.0
    ) -> Optional[bytes]:
        """ Send command and await notification response from the device. """
        ...

    async def wait_for_response(self, command_id: int, timeout: float = 10.0) -> Optional[bytes]:
        """ Await notification response for a command ID. """
        ...
