# divoom_legacy/wall_broadcast.py
"""The whole-wall broadcast commands of ``DivoomWall``.

Each sends one command to every slot in ``self.devices`` in parallel and
reports whether all of them took it. The image path (splitting a picture or
animation into per-screen tiles) stays in ``wall.py``; ``DivoomWall`` inherits
this mixin.
"""

import asyncio


class WallBroadcastMixin:
    """Fan-out commands over ``self.devices``; see the module docstring."""

    async def set_light(self, color: str, brightness: int = 100) -> bool:
        """Sets a unified solid light color across all screens in the wall."""
        self.logger.info(f"Setting solid light {color} across all screens...")
        tasks = []
        for slot in self.devices:
            tasks.append(slot.device.display.show_light(color=color, brightness=brightness))
        # return_exceptions: one slot's BLE failure must yield an honest degraded
        # False, not raise out of the method and abandon the sibling pushes
        # (matches set_volume / switch_channel / set_brightness below).
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return all(res is True for res in results)

    async def show_clock(self, clock: int = 0) -> bool:
        """Displays clock style on all screens in the wall."""
        self.logger.info(f"Displaying clock style {clock} across all screens...")
        tasks = []
        for slot in self.devices:
            tasks.append(slot.device.display.show_clock(clock=clock))
        # return_exceptions: one slot's BLE failure must yield an honest degraded
        # False, not raise out of the method and abandon the sibling pushes
        # (matches set_volume / switch_channel / set_brightness below).
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return all(res is True for res in results)

    async def show_effects(self, number: int = 0) -> bool:
        """Displays VJ effect style on all screens in the wall."""
        self.logger.info(f"Displaying VJ effect {number} across all screens...")
        tasks = []
        for slot in self.devices:
            tasks.append(slot.device.display.show_effects(number=number))
        # return_exceptions: one slot's BLE failure must yield an honest degraded
        # False, not raise out of the method and abandon the sibling pushes
        # (matches set_volume / switch_channel / set_brightness below).
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return all(res is True for res in results)

    async def show_visualization(self, number: int = 0) -> bool:
        """Displays visualization EQ style on all screens in the wall."""
        self.logger.info(f"Displaying visualization EQ {number} across all screens...")
        tasks = []
        for slot in self.devices:
            tasks.append(slot.device.display.show_visualization(number=number))
        # return_exceptions: one slot's BLE failure must yield an honest degraded
        # False, not raise out of the method and abandon the sibling pushes
        # (matches set_volume / switch_channel / set_brightness below).
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return all(res is True for res in results)

    async def set_brightness(self, brightness: int) -> bool:
        """Sets brightness across all screens (LAN transport when available,
        else BLE), matching the GUI's per-device transport choice."""
        self.logger.info(f"Setting brightness {brightness} across all screens...")
        tasks = []
        for slot in self.devices:
            if getattr(slot.device, "lan", None):
                tasks.append(slot.device.lan.set_brightness(brightness))
            else:
                tasks.append(slot.device.device.set_brightness(brightness))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return all(res is True or isinstance(res, dict) for res in results)

    async def set_volume(self, volume: int) -> bool:
        """Sets volume across all screens in the wall."""
        self.logger.info(f"Setting volume {volume} across all screens...")
        tasks = []
        for slot in self.devices:
            tasks.append(slot.device.music.set_volume(volume))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return all(res is True for res in results)

    async def switch_channel(self, channel: str) -> bool:
        """Switches all screens in the wall to the same channel."""
        self.logger.info(f"Switching all screens to channel {channel}...")
        tasks = []
        for slot in self.devices:
            tasks.append(slot.device.display.switch_channel(channel))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return all(res is True or isinstance(res, dict) for res in results)

    async def push_text(
        self, text: str, color: str = "#FFFFFF", font_size: int = 1, speed: int = 50, effect_style: int = 1
    ) -> bool:
        """Pushes the same scrolling text to every screen, using each screen's
        own pixel size for the display box (the LPWA 0x87 sequence)."""
        from divoom_lib.models import (
            LPWA_CONTROL_DISPLAY_BOX,
            LPWA_CONTROL_FONT,
            LPWA_CONTROL_COLOR,
            LPWA_CONTROL_SPEED,
            LPWA_CONTROL_EFFECTS,
            LPWA_CONTROL_CONTENT,
        )

        self.logger.info(f"Pushing text {text!r} across all screens...")

        async def _push(divoom, size: int) -> bool:
            t = divoom.text
            box = 0
            await t.set_light_phone_word_attr(
                LPWA_CONTROL_DISPLAY_BOX, x=0, y=0, width=size, height=size, text_box_id=box
            )
            await t.set_light_phone_word_attr(LPWA_CONTROL_FONT, font_size=int(font_size), text_box_id=box)
            await t.set_light_phone_word_attr(LPWA_CONTROL_COLOR, color=color, text_box_id=box)
            await t.set_light_phone_word_attr(LPWA_CONTROL_SPEED, speed=int(speed), text_box_id=box)
            await t.set_light_phone_word_attr(LPWA_CONTROL_EFFECTS, effect_style=int(effect_style))
            res = await t.set_light_phone_word_attr(LPWA_CONTROL_CONTENT, text_content=str(text), text_box_id=box)
            return res is not False

        results = []
        for slot in self.devices:
            divoom = slot.device
            sz = slot.size
            results.append(await _push(divoom, int(sz)))
        return all(results)

    def get_last_previews(self) -> dict:
        """Return base64 Data URLs of the last images/GIFs pushed to the slots."""
        import base64

        res = {}
        for mac, data in self.last_previews.items():
            if not data:
                continue
            mime = "image/gif" if data.startswith(b"GIF8") else "image/png"
            res[mac] = f"data:{mime};base64,{base64.b64encode(data).decode('utf-8')}"
        return res
