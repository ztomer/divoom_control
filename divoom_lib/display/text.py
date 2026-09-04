
from divoom_lib.sender_protocol import CommandSender
from divoom_lib.models import (
    COMMANDS,
    LPWA_CONTROL_SPEED, LPWA_CONTROL_EFFECTS, LPWA_CONTROL_DISPLAY_BOX,
    LPWA_CONTROL_FONT, LPWA_CONTROL_COLOR, LPWA_CONTROL_CONTENT, LPWA_CONTROL_IMAGE_EFFECTS
)

class Text:
    """
    Provides functionality to control the text display of a Divoom device.

    Usage::

        import asyncio
        from divoom_lib import Divoom

        async def main():
            device_address = "XX:XX:XX:XX:XX:XX"  # Replace with your device's address
            divoom = Divoom(mac=device_address)
            
            try:
                await divoom.connect()
                await divoom.text.set_text_content("Hello", text_box_id=1)
            finally:
                if divoom.is_connected:
                    await divoom.disconnect()

        if __name__ == "__main__":
            asyncio.run(main())
    """
    def __init__(self, divoom: CommandSender):
        """
        Initializes the Text controller.

        Args:
            divoom: The Divoom object to send commands to the device.
        """
        self.communicator = divoom
        self.logger = divoom.logger

    def _handle_lpwa_speed(self, kwargs: dict) -> list | None:
        speed = kwargs.get("speed")
        text_box_id = kwargs.get("text_box_id")
        if speed is not None and text_box_id is not None:
            return list(speed.to_bytes(2, byteorder='little')) + list(text_box_id.to_bytes(1, byteorder='big'))
        self.logger.error("Missing 'speed' or 'text_box_id' for Text Speed control.")
        return None

    def _handle_lpwa_effects(self, kwargs: dict) -> list | None:
        effect_style = kwargs.get("effect_style")
        if effect_style is not None:
            return list(effect_style.to_bytes(1, byteorder='big'))
        self.logger.error("Missing 'effect_style' for Text Effects control.")
        return None

    def _handle_lpwa_display_box(self, kwargs: dict) -> list | None:
        x = kwargs.get("x")
        y = kwargs.get("y")
        width = kwargs.get("width")
        height = kwargs.get("height")
        text_box_id = kwargs.get("text_box_id")
        if all(v is not None for v in [x, y, width, height, text_box_id]):
            return list(x.to_bytes(1, byteorder='big')) + \
                   list(y.to_bytes(1, byteorder='big')) + \
                   list(width.to_bytes(1, byteorder='big')) + \
                   list(height.to_bytes(1, byteorder='big')) + \
                   list(text_box_id.to_bytes(1, byteorder='big'))
        self.logger.error("Missing parameters for Text Display Box control.")
        return None

    def _handle_lpwa_font(self, kwargs: dict) -> list | None:
        font_size = kwargs.get("font_size")
        text_box_id = kwargs.get("text_box_id")
        if font_size is not None and text_box_id is not None:
            return list(font_size.to_bytes(1, byteorder='big')) + list(text_box_id.to_bytes(1, byteorder='big'))
        self.logger.error("Missing 'font_size' or 'text_box_id' for Text Font control.")
        return None

    def _handle_lpwa_color(self, kwargs: dict) -> list | None:
        color = kwargs.get("color")
        text_box_id = kwargs.get("text_box_id")
        if color is not None and text_box_id is not None:
            from ..utils.converters import color_to_rgb_list
            rgb_color = color_to_rgb_list(color)
            return rgb_color + list(text_box_id.to_bytes(1, byteorder='big'))
        self.logger.error("Missing 'color' (RGB list) or 'text_box_id' for Text Color control.")
        return None

    def _handle_lpwa_content(self, kwargs: dict) -> list | None:
        text_content = kwargs.get("text_content")
        text_box_id = kwargs.get("text_box_id")
        if text_content is not None and text_box_id is not None:
            content_bytes = text_content.encode('utf-8')
            return list(len(content_bytes).to_bytes(2, byteorder='little')) + \
                   list(content_bytes) + \
                   list(text_box_id.to_bytes(1, byteorder='big'))
        self.logger.error("Missing 'text_content' or 'text_box_id' for Text Content control.")
        return None

    def _handle_lpwa_image_effects(self, kwargs: dict) -> list | None:
        effect_style = kwargs.get("effect_style")
        text_box_id = kwargs.get("text_box_id")
        if effect_style is not None and text_box_id is not None:
            return list(effect_style.to_bytes(1, byteorder='big')) + list(text_box_id.to_bytes(1, byteorder='big'))
        self.logger.error("Missing 'effect_style' or 'text_box_id' for Image Effects control.")
        return None

    _lpwa_handlers = {
        LPWA_CONTROL_SPEED: _handle_lpwa_speed,
        LPWA_CONTROL_EFFECTS: _handle_lpwa_effects,
        LPWA_CONTROL_DISPLAY_BOX: _handle_lpwa_display_box,
        LPWA_CONTROL_FONT: _handle_lpwa_font,
        LPWA_CONTROL_COLOR: _handle_lpwa_color,
        LPWA_CONTROL_CONTENT: _handle_lpwa_content,
        LPWA_CONTROL_IMAGE_EFFECTS: _handle_lpwa_image_effects,
    }

    async def set_light_phone_word_attr(self, control: int, **kwargs):
        """
        Set various attributes of the animated text.

        This method sends a command (0x87) to control different aspects of
        animated text, such as speed, effects, color, and content.

        Args:
            control (int): The control word for the attribute to set.
                           (e.g., 1 for speed, 5 for color).
            **kwargs: The arguments for the control word.

        Returns:
            bool: True if the command was sent successfully, False otherwise.
        
        Usage::
            
            # Set the text color to red
            await divoom.text.set_light_phone_word_attr(5, color=(255, 0, 0), text_box_id=1)
        """
        self.logger.info(
            f"Setting light phone word attribute with control {control} (0x87)...")
        args = [control]

        handler = self._lpwa_handlers.get(control)
        if handler:
            control_args = handler(self, kwargs)
            if control_args is not None:
                args.extend(control_args)
            else:
                return False
        else:
            self.logger.warning(
                f"Unknown control word for set_light_phone_word_attr: {control}")
            return False

        return await self.communicator.send_command(COMMANDS["set light phone word attr"], args)

    async def set_text_content(self, text: str, **kwargs):
        """
        Set the text content of a text box.

        Args:
            text (str): The text to display.
            **kwargs: Additional arguments for the text box.

        Returns:
            bool: True if the command was sent successfully, False otherwise.
        
        Usage::
            
            # Set the text content to "Hello"
            await divoom.text.set_text_content("Hello", text_box_id=1)
        """
        return await self.set_light_phone_word_attr(LPWA_CONTROL_CONTENT, text_content=text, **kwargs)
