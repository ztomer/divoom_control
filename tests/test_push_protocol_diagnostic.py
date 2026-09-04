"""Live-device diagnostic for the cover-art push bug.

User-reported symptom (2026-06-05):
  "push_music_cover_now returns success: true, log shows the
   bytes being sent, but the device screen does not update."

User observation:
  "Device was on a different channel" (e.g. clock or visualizer)
  when the push happened, and the new image wasn't shown.

Hypothesis being tested:
  The library's divoom_lib/display/show_image() *does* call
  show_design() first (which sends 0x45 0x05 ... channel switch),
  so the channel switch is on the wire. The real bug is either:

  A. The channel switch bytes arrive AFTER the image bytes
     (BLE write-without-response has no ordering guarantee).
  B. The image bytes are corrupted in transit (chunking /
     escape / chunksize issue).
  C. The device accepts the switch but the image push lands
     on a "design" sub-page that doesn't render.
  D. The device is on a different transport and we're writing
     to the wrong interface.

This test records every byte sent during a `show_image` call,
reads the work mode before/after, and reports its findings. It
makes no assertions about the *correct* behavior — it just
records the byte stream so we can compare against a known-good
push (e.g. one captured from the official Divoom app, or a
prior working session).

Run with::

    pytest --run-hardware tests/test_push_protocol_diagnostic.py -v -s
"""

import asyncio
import logging
import unittest

from PIL import Image

from divoom_lib import Divoom
from divoom_lib.utils.discovery import discover_device

# --- Configuration ---
# Pin to one device for reproducible captures. The user can change
# this to target a different MAC; the diagnostic just needs ONE
# device to talk to.
DEVICE_NAME_SUBSTRING = "Tivoo"
LOG_LEVEL = logging.INFO
TEST_IMAGE_SIDE = 16
TEST_IMAGE_COLOR = (255, 0, 0)  # solid red

# Write the diagnostic output to a file so it survives pytest's log
# capture and is easy to inspect post-run.
DIAGNOSTIC_LOG_PATH = "/tmp/divoom_push_diagnostic.log"

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("push_protocol_diagnostic")

# A separate file handler so the diagnostic output is always written
# to /tmp/divoom_push_diagnostic.log regardless of pytest's capture.
_file_handler = logging.FileHandler(DIAGNOSTIC_LOG_PATH, mode="w")
_file_handler.setLevel(LOG_LEVEL)
_file_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
logger.addHandler(_file_handler)


class TestPushProtocolDiagnostic(unittest.IsolatedAsyncioTestCase):
    """Diagnostic: capture the full protocol byte stream for show_image."""

    divoom: Divoom = None
    _original_send_payload = None
    _byte_log: list[tuple[str, bytes]] = []

    async def asyncSetUp(self):
        """Discover and connect to the device, install the byte logger."""
        ble_device, _ = await discover_device(name_substring=DEVICE_NAME_SUBSTRING)
        if not ble_device:
            self.fail(f"No device found with name containing '{DEVICE_NAME_SUBSTRING}'.")

        self.divoom = Divoom(
            mac=ble_device.address,
            logger=logger,
            use_ios_le_protocol=True,
        )
        await self.divoom.connect()
        self.divoom.escapePayload = False

        # Install a wrapper around send_payload that logs every byte.
        transport = self.divoom
        original = transport.send_payload

        async def logging_send_payload(payload_bytes, *args, **kwargs):
            self._byte_log.append(("send", bytes(payload_bytes)))
            logger.info(
                "TX  : %s (len=%d, write_with_response=%s)",
                " ".join(f"{b:02x}" for b in payload_bytes),
                len(payload_bytes),
                kwargs.get("write_with_response", False),
            )
            result = await original(payload_bytes, *args, **kwargs)
            return result

        transport.send_payload = logging_send_payload
        self._original_send_payload = original
        # Clear any log entries from the connection handshake.
        self._byte_log.clear()

    async def asyncTearDown(self):
        """Restore the original send_payload and disconnect."""
        if self._original_send_payload is not None:
            self.divoom.send_payload = self._original_send_payload
        if self.divoom and self.divoom.is_connected:
            await self.divoom.disconnect()

    async def test_capture_show_image_protocol_stream(self):
        """Record every byte sent during a show_image call.

        Captures the full protocol byte stream from a known-good
        16x16 solid-red image. Use the output to compare against
        a working push (e.g. from the official Divoom app).
        """
        # 1. Read initial work mode
        self._byte_log.clear()
        initial_mode = await self.divoom.system.get_work_mode()
        logger.info("=" * 70)
        logger.info("INITIAL WORK MODE: %s", f"0x{initial_mode:02x}" if initial_mode is not None else "None")
        self._byte_log.clear()  # discard the get-work-mode bytes

        # 2. Build a known-good 16x16 test image
        test_image_path = "/tmp/divoom_push_diag.png"
        img = Image.new("RGB", (TEST_IMAGE_SIDE, TEST_IMAGE_SIDE), TEST_IMAGE_COLOR)
        img.save(test_image_path)
        logger.info("=" * 70)
        logger.info("TEST IMAGE: %s (%dx%d, %s)",
                    test_image_path, TEST_IMAGE_SIDE, TEST_IMAGE_SIDE, TEST_IMAGE_COLOR)

        # 3. Push the image — every byte goes to the log
        logger.info("=" * 70)
        logger.info("PUSHING show_image()...")
        result = await self.divoom.display.show_image(test_image_path)
        logger.info("=" * 70)
        logger.info("show_image returned: %s", result)

        # 4. Wait for the device to process, then read work mode again
        await asyncio.sleep(2.0)
        self._byte_log.clear()  # discard any post-push retransmissions
        final_mode = await self.divoom.system.get_work_mode()
        self._byte_log.clear()
        logger.info("=" * 70)
        logger.info("FINAL WORK MODE: %s", f"0x{final_mode:02x}" if final_mode is not None else "None")

        # 5. Summarize the byte stream
        logger.info("=" * 70)
        logger.info("BYTE STREAM SUMMARY (%d packets sent):", len(self._byte_log))
        channel_switch_seen = False
        image_data_seen = False
        for direction, data in self._byte_log:
            label = "TX" if direction == "send" else "RX"
            hex_str = " ".join(f"{b:02x}" for b in data)
            if data and data[0] == 0x45 and len(data) >= 2 and data[1] == 0x05:
                channel_switch_seen = True
                logger.info("  %s  [CHANNEL-SWITCH 0x45 0x05]  %s", label, hex_str)
            elif data and data[0] == 0x44:
                image_data_seen = True
                logger.info("  %s  [IMAGE 0x44]            %s ... (%d bytes total)",
                            label, hex_str[:60], len(data))
            elif data and data[0] == 0x49:
                logger.info("  %s  [ANIM-FRAME 0x49]       %s ... (%d bytes total)",
                            label, hex_str[:60], len(data))
            else:
                logger.info("  %s  [cmd 0x%02x]            %s", label, data[0] if data else 0, hex_str[:60])

        # 6. Report findings (no hard assertions — this is a diagnostic)
        logger.info("=" * 70)
        logger.info("FINDINGS:")
        logger.info("  initial_mode : %s", f"0x{initial_mode:02x}" if initial_mode is not None else "None")
        logger.info("  final_mode   : %s", f"0x{final_mode:02x}" if final_mode is not None else "None")
        logger.info("  channel_switch_seen: %s", channel_switch_seen)
        logger.info("  image_data_seen:     %s", image_data_seen)
        if initial_mode is not None and final_mode is not None:
            if initial_mode == final_mode:
                logger.warning("   Work mode did NOT change after push. Device stayed on 0x%02x.", initial_mode)
            else:
                logger.info("   Work mode changed: 0x%02x -> 0x%02x", initial_mode, final_mode)
        if not channel_switch_seen:
            logger.error("   Channel switch (0x45 0x05) was NOT in the byte stream.")
        if not image_data_seen:
            logger.error("   Image data (0x44 or 0x49) was NOT in the byte stream.")
        logger.info("=" * 70)

        # The diagnostic doesn't assert success — it just records. Mark
        # it as a smoke test that always passes (so --run-hardware picks
        # it up without failing).
        self.assertTrue(True, "Diagnostic completed (see log output)")


if __name__ == "__main__":
    unittest.main()
