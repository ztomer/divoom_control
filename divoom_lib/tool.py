"""
Divoom Tool Commands
"""
from .models import (
    COMMANDS,
    TOOL_TYPE_TIMER, TOOL_TYPE_SCORE, TOOL_TYPE_NOISE, TOOL_TYPE_COUNTDOWN, TOOL_TYPE_NOT_IN_GAME_MODE,
    GTI_TIMER_STATUS, GTI_SCORE_ON_OFF, GTI_SCORE_RED_SCORE_START, GTI_SCORE_RED_SCORE_LENGTH,
    GTI_SCORE_BLUE_SCORE_START, GTI_SCORE_BLUE_SCORE_LENGTH, GTI_NOISE_STATUS,
    GTI_COUNTDOWN_STATUS, GTI_COUNTDOWN_MINUTES, GTI_COUNTDOWN_SECONDS,
    STI_CTRL_FLAG_TIMER_PAUSED, STI_CTRL_FLAG_TIMER_STARTED, STI_CTRL_FLAG_TIMER_RESET,
    STI_CTRL_FLAG_TIMER_ENTERING_STOPWATCH, STI_CTRL_FLAG_NOISE_START, STI_CTRL_FLAG_NOISE_STOP,
    STI_CTRL_FLAG_COUNTDOWN_START, STI_CTRL_FLAG_COUNTDOWN_CANCEL, STI_SCORE_OFF, STI_SCORE_ON
)
from .sender_protocol import CommandSender

class Tool:
    def __init__(self, communicator: CommandSender):
        self.communicator = communicator
        self.logger = communicator.logger

    async def get_tool_info(self, tool_type: int) -> dict | None:
        """Get information about the tools available in the device (0x71)."""
        self.logger.info(f"Getting tool info for type {tool_type} (0x71)...")
        
        command_id = COMMANDS["get tool info"]
        args = [tool_type]
        
        # Set the command we are waiting for and send it with the correct protocol
        self.communicator._expected_response_command = command_id
        async with self.communicator._framing_context(use_ios=self.communicator.use_ios_le_protocol, escape=False):
            await self.communicator.send_command(command_id, args)

        # Wait for the response using the default (Basic) protocol
        response = await self.communicator.wait_for_response(command_id)
        
        if response:
            return self._parse_tool_info_response(tool_type, response)
        return None

    def _parse_tool_info_response(self, tool_type: int, response: list) -> dict | None:
        """Parses the response from get_tool_info based on the tool_type."""
        if tool_type == TOOL_TYPE_TIMER:  # DIVOOM_DISP_WATCH_MODE (Timer)
            if len(response) >= 1:
                return {"status": response[GTI_TIMER_STATUS]}
        elif tool_type == TOOL_TYPE_SCORE:  # DIVOOM_DISP_SCORE_MODE (Score)
            if len(response) >= 5:
                return {
                    "on_off": response[GTI_SCORE_ON_OFF],
                    "red_score": int.from_bytes(response[GTI_SCORE_RED_SCORE_START:GTI_SCORE_RED_SCORE_START + GTI_SCORE_RED_SCORE_LENGTH], byteorder='little'),
                    "blue_score": int.from_bytes(response[GTI_SCORE_BLUE_SCORE_START:GTI_SCORE_BLUE_SCORE_START + GTI_SCORE_BLUE_SCORE_LENGTH], byteorder='little'),
                }
        elif tool_type == TOOL_TYPE_NOISE:  # DIVOOM_DISP_NOISE_MODE (Noise)
            if len(response) >= 1:
                return {"status": response[GTI_NOISE_STATUS]}
        elif tool_type == TOOL_TYPE_COUNTDOWN:  # DIVOOM_DISP_COUNT_TIME_DOWN (Countdown)
            if len(response) >= 3:
                return {
                    "status": response[GTI_COUNTDOWN_STATUS],
                    "minutes": response[GTI_COUNTDOWN_MINUTES],
                    "seconds": response[GTI_COUNTDOWN_SECONDS],
                }
        elif tool_type == TOOL_TYPE_NOT_IN_GAME_MODE:  # Not in any game mode
            return {"status": "not in game mode"}
        return None

    def _set_timer_tool(self, **kwargs) -> list:
        ctrl_flag = kwargs.get("ctrl_flag")
        if ctrl_flag is None:
            raise ValueError("Missing 'ctrl_flag' for Timer mode.")
        return [ctrl_flag]

    def _set_score_tool(self, **kwargs) -> list:
        on_off = kwargs.get("on_off")
        red_score = kwargs.get("red_score", 0)
        blue_score = kwargs.get("blue_score", 0)
        if on_off is None:
            raise ValueError("Missing 'on_off' for Score mode.")
        args = [on_off]
        args.extend(red_score.to_bytes(2, byteorder='little'))
        args.extend(blue_score.to_bytes(2, byteorder='little'))
        return args

    def _set_noise_tool(self, **kwargs) -> list:
        ctrl_flag = kwargs.get("ctrl_flag")
        if ctrl_flag is None:
            raise ValueError("Missing 'ctrl_flag' for Noise mode.")
        return [ctrl_flag]

    def _set_countdown_tool(self, **kwargs) -> list:
        ctrl_flag = kwargs.get("ctrl_flag")
        minutes = kwargs.get("minutes")
        seconds = kwargs.get("seconds")
        if not all(v is not None for v in [ctrl_flag, minutes, seconds]):
            raise ValueError(
                "Missing 'ctrl_flag', 'minutes', or 'seconds' for Countdown mode.")
        return [ctrl_flag, minutes, seconds]

    async def set_tool_info(self, game_mode_index: int, **kwargs) -> bool:
        """Set information for the tools (games) available in the device (0x72).
        Handles different data structures based on game_mode_index."""
        self.logger.info(
            f"Setting tool info for game mode {game_mode_index} (0x72)...")

        _set_tool_handlers = {
            TOOL_TYPE_TIMER: self._set_timer_tool,
            TOOL_TYPE_SCORE: self._set_score_tool,
            TOOL_TYPE_NOISE: self._set_noise_tool,
            TOOL_TYPE_COUNTDOWN: self._set_countdown_tool,
        }

        handler = _set_tool_handlers.get(game_mode_index)
        if not handler:
            self.logger.warning(f"Unknown game_mode_index: {game_mode_index}")
            return False

        try:
            args = [game_mode_index]
            args.extend(handler(**kwargs))
        except ValueError as e:
            self.logger.error(f"Error setting tool info: {e}")
            return False

        return await self.communicator.send_command(COMMANDS["set tool"], args)