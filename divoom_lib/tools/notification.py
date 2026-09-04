from divoom_lib.sender_protocol import CommandSender
from divoom_lib.models import COMMANDS, NOTIFICATION_APPS


class Notification:
    """Notification mirroring (SPP_SET_ANDROID_ANCS, cmd 0x50).

    Triggers the device's notification display for a given app type. Two wire
    forms, both confirmed against the decompiled APK (``CmdManager.a0`` and
    ``CmdManager.V``):

      * icon-only trigger      → ``[app_type']``         (a single byte)
      * icon + scrolling text  → ``[app_type, len, *utf8]`` (text ≤ 128 bytes)

    where ``app_type'`` skips wire slot 8: for ``app_type >= 8`` the byte sent is
    ``app_type + 1``. App-type values live in
    :data:`divoom_lib.models.NOTIFICATION_APPS` (KAKAO=1 … OK=14).

    Note: this is a *manual* trigger — it does not auto-source the host's real
    notifications (that needs OS-specific plumbing and is out of scope).

    Usage::

        await divoom.notification.show_notification(NOTIFICATION_APPS["WHATSAPP"])
        await divoom.notification.show_notification_text(7, "Hi!")
    """

    MAX_TEXT_BYTES = 128

    def __init__(self, divoom: CommandSender):
        self._divoom = divoom
        self.logger = divoom.logger

    @staticmethod
    def _wire_type(app_type: int) -> int:
        """Map an app type to its wire byte, replicating the >=8 skip."""
        t = int(app_type)
        return (t + 1 if t >= 8 else t) & 0xFF

    async def show_notification(self, app_type: int) -> bool:
        """Show the notification icon/blink for ``app_type`` (icon-only form)."""
        wire = self._wire_type(app_type)
        self.logger.info(
            f"Showing notification for app_type={app_type} (wire={wire}, 0x50)..."
        )
        return await self._divoom.send_command(
            COMMANDS["set android ancs"], [wire]
        )

    async def show_notification_text(self, app_type: int, text: str) -> bool:
        """Show ``app_type``'s icon plus ``text`` (truncated to 128 UTF-8 bytes).

        Uses the ``[app_type, len, *utf8]`` form (``CmdManager.V``), which sends
        the raw app type (no >=8 skip — the firmware text path indexes directly).
        """
        utf8 = (text or "").encode("utf-8")[: self.MAX_TEXT_BYTES]
        args = [int(app_type) & 0xFF, len(utf8)] + list(utf8)
        self.logger.info(
            f"Showing notification text for app_type={app_type} "
            f"({len(utf8)} bytes, 0x50)..."
        )
        return await self._divoom.send_command(
            COMMANDS["set android ancs"], args
        )
