
from divoom_lib.sender_protocol import CommandSender
from divoom_lib.models import (
    COMMANDS,
    GLM_CURRENT_LIGHT_EFFECT_MODE, GLM_TEMPERATURE_DISPLAY_MODE, GLM_VJ_SELECTION_OPTION,
    GLM_RGB_COLOR_VALUES_START, GLM_BRIGHTNESS_LEVEL, GLM_LIGHTING_MODE_SELECTION_OPTION,
    GLM_ON_OFF_SWITCH, GLM_MUSIC_MODE_SELECTION_OPTION, GLM_SYSTEM_BRIGHTNESS,
    GLM_TIME_DISPLAY_FORMAT_SELECTION_OPTION, GLM_TIME_DISPLAY_RGB_COLOR_VALUES_START,
    GLM_TIME_DISPLAY_MODE, GLM_TIME_CHECKBOX_MODES_START
)

class Light:
    """
    Provides functionality to control the light of a Divoom device.

    Usage::

        import asyncio
        from divoom_lib import Divoom

        async def main():
            device_address = "XX:XX:XX:XX:XX:XX"  # Replace with your device's address
            divoom = Divoom(mac=device_address)
            
            try:
                await divoom.connect()
                light_mode = await divoom.light.get_light_mode()
                print(f"Current light mode: {light_mode}")
            finally:
                if divoom.is_connected:
                    await divoom.disconnect()

        if __name__ == "__main__":
            asyncio.run(main())
    """
    def __init__(self, divoom: CommandSender):
        """
        Initializes the Light controller.

        Args:
            divoom: The Divoom object to send commands to the device.
        """
        self.communicator = divoom
        self.logger = divoom.logger

    async def get_light_mode(self):
        """
        Get the current light mode settings from the device.

        This method sends a command (0x46) to the device to retrieve the current
        light mode settings and returns them as a dictionary.

        Returns:
            dict | None: A dictionary containing the light mode settings,
                         or None if the command fails.
        
        Usage::
            
            light_mode = await divoom.light.get_light_mode()
            if light_mode:
                print(f"Brightness: {light_mode['brightness_level']}")
        """
        self.logger.info("Getting light mode (0x46)...")
        
        command_id = COMMANDS["get light mode"]

        # Drain stale/unsolicited frames (the device emits a 0x46 on light-state
        # change) so we read THIS query's fresh response, not a leftover that
        # lags one step behind — HW-confirmed. See Divoom.drain_notifications.
        self.communicator.drain_notifications()
        # Set the command we are waiting for and send it with the correct protocol
        self.communicator._expected_response_command = command_id
        async with self.communicator._framing_context(use_ios=self.communicator.use_ios_le_protocol, escape=False):
            await self.communicator.send_command(command_id, [])

        # Wait for the response using the default (Basic) protocol
        response = await self.communicator.wait_for_response(command_id)
        
        # Based on documentation, response has 20 bytes
        if response and len(response) >= 20:
            return {
                "current_light_effect_mode": response[GLM_CURRENT_LIGHT_EFFECT_MODE],
                "temperature_display_mode": response[GLM_TEMPERATURE_DISPLAY_MODE],
                "vj_selection_option": response[GLM_VJ_SELECTION_OPTION],
                "rgb_color_values": [response[GLM_RGB_COLOR_VALUES_START], response[GLM_RGB_COLOR_VALUES_START + 1], response[GLM_RGB_COLOR_VALUES_START + 2]],
                "brightness_level": response[GLM_BRIGHTNESS_LEVEL],
                "lighting_mode_selection_option": response[GLM_LIGHTING_MODE_SELECTION_OPTION],
                "on_off_switch": response[GLM_ON_OFF_SWITCH],
                "music_mode_selection_option": response[GLM_MUSIC_MODE_SELECTION_OPTION],
                "system_brightness": response[GLM_SYSTEM_BRIGHTNESS],
                "time_display_format_selection_option": response[GLM_TIME_DISPLAY_FORMAT_SELECTION_OPTION],
                "time_display_rgb_color_values": [response[GLM_TIME_DISPLAY_RGB_COLOR_VALUES_START], response[GLM_TIME_DISPLAY_RGB_COLOR_VALUES_START + 1], response[GLM_TIME_DISPLAY_RGB_COLOR_VALUES_START + 2]],
                "time_display_mode": response[GLM_TIME_DISPLAY_MODE],
                "time_checkbox_modes": [response[GLM_TIME_CHECKBOX_MODES_START], response[GLM_TIME_CHECKBOX_MODES_START + 1], response[GLM_TIME_CHECKBOX_MODES_START + 2], response[GLM_TIME_CHECKBOX_MODES_START + 3]],
            }
        return None

    async def show_light(self, color, brightness, power):
        """
        Sets a solid color light.

        Args:
            color (tuple | list | str): The color to display. Can be a tuple or list of (R, G, B) values, or a hex string.
            brightness (int): The brightness of the light (0-100).
            power (bool): Whether to turn the light on or off.

        Usage::

            # Set the light to red at 50% brightness
            await divoom.light.show_light(color=(255, 0, 0), brightness=50, power=True)
        """
        from ..utils.converters import color_to_rgb_list
        rgb = color_to_rgb_list(color)
        # Divoom Light mode command (0x45) expects a strict 10-byte payload format:
        # [0x01 (Light Mode), R, G, B, Brightness, Effect Mode, On/Off Switch, 0x00, 0x00, 0x00]
        payload = [0x01] + rgb + [brightness, 0x00, 0x01 if power else 0x00, 0x00, 0x00, 0x00]
        await self.communicator.send_command("set light mode", payload)
