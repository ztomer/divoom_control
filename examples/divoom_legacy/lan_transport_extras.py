"""
lan_transport_extras.py — Channel extras (5-LCD multi-panel, night preview)
and Voice/SendText, split out of lan_transport.py to stay under the
500-line house limit.

All in HttpCommand.DeviceAndServerCmd (LAN-routed on WiFi). See
docs/cloud_api/channel_b.md / playlist_voice_timeplan.md.

NOT GUI-wired: the 5-LCD commands need real "Times Gate" multi-panel
hardware this project doesn't have reason to own. Voice/SendText needs the
same real-hardware confirmation push_text's known-working bitmap-render
path already learned the hard way (R32 SS D: a superficially-similar "set
light phone word" command ACKed cleanly but did not render on Pixoo-class
matrices) -- implemented at the plumbing layer only, not surfaced until
confirmed.
"""

from divoom_lib.transport import Transport, via


class LanExtrasMixin:
    """Channel extras + Voice/SendText mixed into LanTransport — relies on
    the host class's ``self.post()``."""

    @via(Transport.LAN)
    async def set_5lcd_channel_type(self, channel_type: int, lcd_independence: int = 0) -> dict:
        """Set which channel/mode type is shown on a panel of a 5-LCD
        multi-panel device. Transport: LAN."""
        return await self.post("Channel/Set5LcdChannelType", {
            "ChannelType": channel_type, "LcdIndependence": lcd_independence,
        })

    @via(Transport.LAN)
    async def set_5lcd_whole_clock_id(self, clock_id: int) -> dict:
        """Apply one clock face across an entire 5-LCD panel array.
        Transport: LAN."""
        return await self.post("Channel/Set5LcdWholeClockId", {"ClockId": clock_id})

    @via(Transport.LAN)
    async def set_produce_time(self, produce_time: int) -> dict:
        """Push a schedule/production timestamp for the active channel
        config to the cloud. Transport: LAN."""
        return await self.post("Channel/SetProduceTime", {"ProduceTime": produce_time})

    @via(Transport.LAN)
    async def set_night_preview(self, brightness: int) -> dict:
        """Preview the brightness used for "night mode". Transport: LAN."""
        return await self.post("Channel/SetNightPreview", {"Brightness": brightness})

    @via(Transport.LAN)
    async def exit_night_preview(self) -> dict:
        """Exit/cancel the night-mode brightness preview. Transport: LAN."""
        return await self.post("Channel/ExitNightPreview")

    @via(Transport.LAN)
    async def send_voice_text(
        self, text: str, *, nickname: str = "", background: str = "",
        text_color: str = "#FFFFFF", speed: int = 50,
    ) -> dict:
        """Send a text-to-speech-style greeting/banner. Transport: LAN.
        NOT confirmed to render on this project's target devices — see the
        module docstring."""
        return await self.post("Voice/SendText", {
            "Text": text, "NickName": nickname, "Background": background,
            "TextColor": text_color, "Speed": speed,
        })

    @via(Transport.LAN)
    async def send_danmaku_text(self, text: str, *, text_color: str = "#FFFFFF") -> dict:
        """Push scrolling bullet-chat text to the device. Transport: LAN.
        NOT confirmed to render — see the module docstring."""
        return await self.post("Danmaku/SendText", {"Text": text, "TextColor": text_color})

    @via(Transport.LAN)
    async def danmaku_random_face(self) -> dict:
        """Request a random emoji "face" in the bullet-chat overlay.
        Transport: LAN. No confirmed caller exists anywhere in the
        decompiled app — may be dead/unused server-side."""
        return await self.post("Danmaku/RandomFace")
