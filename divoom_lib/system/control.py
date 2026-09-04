"""Misc system control helpers (Round 4 — Phase E.1).

Sourced from:
  - hass-divoom/devices/ditoo.py:18-32 (keyboard 0x23)
  - hass-divoom custom_components (hot 0x26)
  - futpib (light_mode 0x45)

Provides:
  set_keyboard(key)         — 0x23 (Ditoo single-key press)
  set_hot(enabled)          — 0x26
  set_light_mode(channel)   — 0x45 (show_lyrics alias)

Reference: https://github.com/d03n3rfr1tz3/hass-divoom
"""
from __future__ import annotations

import logging

from divoom_lib.sender_protocol import CommandSender
from divoom_lib.models import COMMANDS

logger = logging.getLogger("divoom_lib")


class Control:
    """High-level system control helpers.

    Usage::

        await divoom.control.set_keyboard(key=0x01)
        await divoom.control.set_hot(enabled=True)
    """

    def __init__(self, divoom: CommandSender):
        self.communicator = divoom
        self.logger = divoom.logger

    async def set_keyboard(self, key: int) -> bool:
        """Send a single key press to the Ditoo keyboard (0x23).

        Args:
            key: Key code (per Ditoo firmware: 0x00=up, 0x01=down, 0x02=back, 0x03=ok).
        """
        self.logger.info(f"Setting keyboard key={key} (0x23)...")
        return await self.communicator.send_command(
            COMMANDS["set keyboard"], [key & 0xFF]
        )

    async def set_hot(self, enabled: bool) -> bool:
        """Enable/disable hot mode (0x26).

        Args:
            enabled: True to enable, False to disable.
        """
        v = 0x01 if enabled else 0x00
        self.logger.info(f"Setting hot to {v} (0x26)...")
        return await self.communicator.send_command(
            COMMANDS["set hot"], [v]
        )

    async def set_light_mode(self, channel: int) -> bool:
        """Set the light / show-lyrics mode (0x45).

        This is the same command used to display lyrics on the device.
        The "channel" parameter selects which visualization is active.

        Args:
            channel: 0-15 (per Divoom firmware; see models.constants).
        """
        self.logger.info(f"Setting light mode channel={channel} (0x45)...")
        return await self.communicator.send_command(
            COMMANDS["set light mode"], [channel & 0xFF]
        )
