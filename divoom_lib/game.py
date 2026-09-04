"""
Divoom Game Commands (Round 4 — Phase E.7).

Sourced from hass-divoom:619-625,627-647 (game 0xA0/0x17/0x21/0x88)
and futpib (game_id enum). Provides:

  show_game(value)              — 0xA0 (set game + select)
  hide_game()                   — 0xA0 (set game off)
  send_gamecontrol(value)       — 0x17/0x21/0x88 (key down/up/shark)
  set_key_down(key)             — 0x17 explicit key down
  set_key_up(key)               — 0x21 explicit key up
  set_magic_ball_answer(answer) — 0x88 (send "go" with answer bit)
  exit_game()                   — 0xA0 (game off + state 0)

Game IDs (per futpib, 1-indexed):
  0x01 = Dino
  0x02 = 2048
  0x03 = Box Jump
  0x04 = Slot Machine
  0x05 = Magic 8 Ball
  0x06 = Guessing
  0x07 = Shake Game
  0x08 = Push Box
  0x09 = Falling Block

Reference: https://github.com/d03n3rfr1tz3/hass-divoom
"""
import time
import asyncio
from . import models as constants
from .utils.converters import to_int_if_str
from .sender_protocol import CommandSender

# Game IDs (per futpib, 1-indexed).
GAME_ID_DINO = 0x01
GAME_ID_2048 = 0x02
GAME_ID_BOX_JUMP = 0x03
GAME_ID_SLOT_MACHINE = 0x04
GAME_ID_MAGIC_BALL = 0x05
GAME_ID_GUESSING = 0x06
GAME_ID_SHAKE = 0x07
GAME_ID_PUSH_BOX = 0x08
GAME_ID_FALLING_BLOCK = 0x09


class Game:
    """
    Provides functionality to control the game features of a Divoom device.

    Usage::

        import asyncio
        from divoom_lib import Divoom

        async def main():
            divoom = Divoom(mac="XX:XX:XX:XX:XX:XX")
            try:
                await divoom.connect()
                # Launch Dino game
                await divoom.game.show_game(value=0x01)
                # Move up
                await divoom.game.set_key_down(0x03)
                await divoom.game.set_key_up(0x03)
            finally:
                if divoom.is_connected:
                    await divoom.disconnect()

        asyncio.run(main())
    """
    def __init__(self, communicator: CommandSender):
        self.communicator = communicator
        self.logger = communicator.logger

    async def show_game(self, value: int | None = None) -> bool:
        """
        Show or hide a game on the Divoom device (0xA0).

        Args:
            value (int | None): The game ID to show (1-9). If None or 0, the
                game is hidden.

        Returns:
            bool: True if the command was sent successfully, False otherwise.
        """
        value = to_int_if_str(value) if value is not None else 0

        game_state = constants.SHOW_GAME_ON if value > 0 else constants.SHOW_GAME_OFF
        args = [game_state, value]
        return await self.communicator.send_command(constants.COMMANDS["set game"], args)

    async def hide_game(self) -> bool:
        """Convenience: hide the currently active game (0xA0 off)."""
        self.logger.info("Hiding game (0xA0)...")
        return await self.show_game(value=0)

    async def send_gamecontrol(self, value: str | int | None = None) -> bool:
        """
        Send a game control command to the Divoom device.

        Args:
            value (str | int | None): The control command to send.
                Can be a string ('up', 'down', 'left', 'right', 'go', 'ok')
                or an integer. If None, sends the 'go' command (0x88).

        Returns:
            bool: True if the command was sent successfully, False otherwise.
        """
        if value is None:
            control_value = constants.GAME_CONTROL_GO
        elif isinstance(value, str):
            control_value = constants.GAME_CONTROL_MAP.get(value.lower(), constants.GAME_CONTROL_GO)
        else:
            control_value = to_int_if_str(value)

        if control_value == constants.GAME_CONTROL_GO:
            return await self.communicator.send_command(constants.COMMANDS["send game shark"])
        else:
            args = [control_value]
            # Combine BOTH sends: the key-down result was previously overwritten
            # by the key-up result, so a failed key-down (the press never landed)
            # with a successful key-up reported True.
            down_ok = await self.communicator.send_command(constants.COMMANDS["set game ctrl info"], args)
            await asyncio.sleep(0.1)
            up_ok = await self.communicator.send_command(constants.COMMANDS["set game ctrl key up info"], args)
            return bool(down_ok) and bool(up_ok)

    async def set_key_down(self, key: int) -> bool:
        """
        Send an explicit key-down event to the active game (0x17).

        Args:
            key: 1=left, 2=right, 3=up, 4=down, 5=ok.
        """
        self.logger.info(f"Game key down {key} (0x17)...")
        return await self.communicator.send_command(
            constants.COMMANDS["set game ctrl info"], [key & 0xFF]
        )

    async def set_key_up(self, key: int) -> bool:
        """
        Send an explicit key-up event to the active game (0x21).

        Args:
            key: 1=left, 2=right, 3=up, 4=down, 5=ok.
        """
        self.logger.info(f"Game key up {key} (0x21)...")
        return await self.communicator.send_command(
            constants.COMMANDS["set game ctrl key up info"], [key & 0xFF]
        )

    async def set_magic_ball_answer(self, answer: int) -> bool:
        """
        Send a Magic 8 Ball "go" with a pre-selected answer (0x88).

        Args:
            answer: 0-19 (per Divoom firmware; answers are device-defined).
        """
        self.logger.info(f"Magic ball answer={answer} (0x88)...")
        return await self.communicator.send_command(
            constants.COMMANDS["send game shark"], [answer & 0xFF]
        )

    async def exit_game(self) -> bool:
        """
        Exit any active game and return to the design channel (0xA0 off + back).

        Sends 0xA0 with state=0, then triggers a channel switch to design.
        """
        self.logger.info("Exiting game (0xA0)...")
        return await self.hide_game()
