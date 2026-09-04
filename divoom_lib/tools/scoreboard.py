
from divoom_lib.sender_protocol import CommandSender
from divoom_lib.models import (
    COMMANDS,
    TOOL_TYPE_SCORE,
    GTI_SCORE_ON_OFF, GTI_SCORE_RED_SCORE_START, GTI_SCORE_RED_SCORE_LENGTH,
    GTI_SCORE_BLUE_SCORE_START, GTI_SCORE_BLUE_SCORE_LENGTH,
    STI_SCORE_OFF, STI_SCORE_ON
)

class Scoreboard:
    """
    Provides functionality to control the scoreboard tool of a Divoom device.

    Usage::

        import asyncio
        from divoom_lib import Divoom

        async def main():
            device_address = "XX:XX:XX:XX:XX:XX"  # Replace with your device's address
            divoom = Divoom(mac=device_address)
            
            try:
                await divoom.connect()
                await divoom.scoreboard.set_scoreboard(1, 10, 20)
            finally:
                if divoom.is_connected:
                    await divoom.disconnect()

        if __name__ == "__main__":
            asyncio.run(main())
    """
    def __init__(self, divoom: CommandSender):
        self._divoom = divoom
        self.logger = divoom.logger

    async def get_scoreboard(self) -> dict | None:
        """
        Get information about the scoreboard tool.
        
        Returns:
            dict | None: A dictionary containing scoreboard information, or None if the command fails.
            
        Usage::
            
            scoreboard = await divoom.scoreboard.get_scoreboard()
            if scoreboard:
                print(f"Scoreboard: {scoreboard}")
        """
        self.logger.info("Getting scoreboard info (0x71)...")
        
        command_id = COMMANDS["get tool info"]
        args = [TOOL_TYPE_SCORE]
        
        # Set the command we are waiting for and send it with the correct protocol
        self._divoom._expected_response_command = command_id
        async with self._divoom._framing_context(use_ios=self._divoom.use_ios_le_protocol, escape=False):
            await self._divoom.send_command(command_id, args)

        # Wait for the response using the default (Basic) protocol
        response = await self._divoom.wait_for_response(command_id)
        
        if response and len(response) >= 5:
            return {
                "on_off": response[GTI_SCORE_ON_OFF],
                "red_score": int.from_bytes(response[GTI_SCORE_RED_SCORE_START:GTI_SCORE_RED_SCORE_START + GTI_SCORE_RED_SCORE_LENGTH], byteorder='little'),
                "blue_score": int.from_bytes(response[GTI_SCORE_BLUE_SCORE_START:GTI_SCORE_BLUE_SCORE_START + GTI_SCORE_BLUE_SCORE_LENGTH], byteorder='little'),
            }
        return None

    async def set_scoreboard(self, on_off: int, red_score: int = 0, blue_score: int = 0) -> bool:
        """
        Set information for the scoreboard tool.
        
        Args:
            on_off (int): 1 to turn on, 0 to turn off.
            red_score (int): The score for the red team.
            blue_score (int): The score for the blue team.
            
        Returns:
            bool: True if the command was sent successfully, False otherwise.
            
        Usage::
            
            # Set the scoreboard with red score 10 and blue score 20
            await divoom.scoreboard.set_scoreboard(1, 10, 20)
        """
        self.logger.info(
            f"Setting scoreboard info: on_off={on_off}, red_score={red_score}, blue_score={blue_score} (0x72)...")

        # Clamp/mask at the boundary: an out-of-range score (the GUI's number
        # input doesn't enforce max=999 for typed values) otherwise hit
        # red_score.to_bytes(2,...) → OverflowError, and an out-of-byte on_off hit
        # bytes() → ValueError — an uncaught crash for any direct lib/daemon/LAN
        # caller. 0–999 matches the documented range (ScoreBoardChannel clamps too).
        on_off = int(on_off) & 0xFF
        red_score = max(0, min(999, int(red_score)))
        blue_score = max(0, min(999, int(blue_score)))

        args = [TOOL_TYPE_SCORE]
        args.append(on_off)
        args.extend(red_score.to_bytes(2, byteorder='little'))
        args.extend(blue_score.to_bytes(2, byteorder='little'))

        return await self._divoom.send_command(COMMANDS["set tool"], args)
