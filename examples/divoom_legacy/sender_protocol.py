import logging
from typing import Protocol, runtime_checkable


@runtime_checkable
class CommandSender(Protocol):
    """Minimal interface for sending commands to a Divoom device.

    This Protocol enables dependency inversion: sub-modules depend on this
    narrow interface rather than on the concrete ``Divoom`` class, making
    them testable with a simple fake.
    """

    logger: logging.Logger

    @property
    def is_connected(self) -> bool: ...

    async def send_command(self, command: int | str, args: list | None = None, write_with_response: bool = False) -> bool: ...

    async def send_command_and_wait_for_response(self, command: int | str, args: list | None = None, timeout: int = 10) -> bytes | None: ...

    async def wait_for_response(self, command_id: int, timeout: float = 3.0) -> bytes | None: ...

    def convert_color(self, color_input: str | tuple | list) -> list: ...
