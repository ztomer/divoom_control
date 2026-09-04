"""Inbound-notification parsing + response correlation for BLETransport.

Split out of ble_transport.py (R53.11): the GATT notification callback, the
iOS-LE / basic-protocol frame parsers, and the response-wait helpers. These share
the ``notification_queue`` + the ``_expected_response_command`` scalar, now
serialized by ``_response_lock`` so a concurrent waiter can't drain another op's
frames or clobber the scalar mid-flight (cross-talk). Mixed into BLETransport;
relies on its attributes (``logger``, ``notification_queue``,
``_expected_response_command``, ``_response_lock``, ``message_buf``,
``use_ios_le_protocol``, ``_listen_commands``, ``is_connected``) and its
``send_command()``.
"""
from __future__ import annotations

import asyncio
import logging

from . import models, framing


class BleNotifyMixin:
    def notification_handler(self, sender: int, data: bytearray) -> None:
        if self.logger.isEnabledFor(logging.DEBUG):
            expected_cmd_str = f"0x{self._expected_response_command:02x}" if self._expected_response_command is not None else "None"
            self.logger.debug(
                "Notification from %s: use_ios_le=%s expected=%s data=%s",
                sender, self.use_ios_le_protocol, expected_cmd_str, data.hex())
        elif self.logger.isEnabledFor(logging.INFO):
            self.logger.info("Raw notification data: %s", data.hex())

        if len(data) >= 4 and data[0:4] == bytes(models.IOS_LE_HEADER):
            self._handle_ios_le_notification(data)
        else:
            self._handle_basic_protocol_notification(data)

    def _handle_ios_le_notification(self, data: bytes) -> bool:
        parsed = framing.parse_ios_le_notification(data)
        if parsed is not None:
            command_identifier = parsed['command_id']
            response_data = parsed['payload']

            if self.logger.isEnabledFor(logging.INFO):
                self.logger.info(
                    "Parsed iOS LE response: Cmd ID: 0x%02x, Packet Num: %s, Data: %s, Checksum: 0x%04x",
                    command_identifier, parsed['packet_number'], response_data.hex(), parsed['checksum'])

            response_payload = {'command_id': command_identifier, 'payload': response_data}
            expected_cmd = self._expected_response_command

            is_expected_response = expected_cmd is not None and command_identifier == expected_cmd
            is_generic_ack = expected_cmd is not None and command_identifier == models.GENERIC_ACK_COMMAND_ID and expected_cmd in models.GENERIC_ACK_COMMANDS
            # R36b: device-driven protocols (hot update) receive UNSOLICITED
            # frames (e.g. 0xF7 file requests) — queue any command in the
            # listen set without consuming _expected_response_command.
            is_listened = command_identifier in getattr(self, "_listen_commands", ())

            if is_listened:
                self.notification_queue.put_nowait(response_payload)
                return True
            if is_expected_response or is_generic_ack:
                # NB: clearing the scalar on the generic 0x33 ACK is LOAD-BEARING
                # for the protocol autoprobe (ble_probe sends a 0x46 probe, and 0x46
                # is a GENERIC_ACK command). Making the ACK keep the scalar (R53.35)
                # let the iOS-LE probe spuriously succeed on a Basic-only device →
                # the Pixoo was mis-detected as iOS-LE and EVERY read-back timed out
                # on real hardware. Reverted (HW-disproven). The "two-frame iOS-LE
                # read-back" the change targeted is unverified on any real device.
                self.notification_queue.put_nowait(response_payload)
                self._expected_response_command = None
                return True
            else:
                self.logger.warning(
                    f"Response command 0x{command_identifier:02x} does not match expected command {f'0x{expected_cmd:02x}' if expected_cmd is not None else 'None'}.")
        else:
            self.logger.warning(f"Unrecognized notification data (not iOS LE Protocol format): {data.hex()}")
        return False

    def _handle_basic_protocol_notification(self, new_data: bytearray) -> bool:
        self.message_buf.extend(new_data)
        if models.MESSAGE_START_BYTE not in self.message_buf:
            self.logger.debug("No start byte found in buffer, clearing.")
            self.message_buf.clear()
            return False
        msgs, self.message_buf = framing.parse_basic_protocol_frames(self.message_buf)
        for response_payload in msgs:
            self.notification_queue.put_nowait(response_payload)
        return True

    async def wait_for_any_response(self, command_ids: list[int],
                                    timeout: float = 10.0) -> tuple[int, bytes] | None:
        """Wait for the first inbound frame whose command id is in
        ``command_ids``; returns ``(command_id, payload)`` or ``None`` on
        timeout. Unlike :meth:`wait_for_response` this serves DEVICE-DRIVEN
        protocols (R36b hot update) where several different commands can
        arrive next (e.g. a 0xF7 file request OR a 0x9E data ack)."""
        loop = asyncio.get_running_loop()
        end_time = loop.time() + timeout
        wanted = set(command_ids)
        while True:
            remaining = end_time - loop.time()
            if remaining <= 0:
                return None
            try:
                response = await asyncio.wait_for(self.notification_queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                return None
            cmd = response.get('command_id')
            if cmd in wanted:
                return cmd, response.get('payload')
            self.logger.debug(f"wait_for_any: ignoring 0x{cmd:02x}")

    async def wait_for_response(self, command_id: int, timeout: float = 10.0) -> bytes | None:
        self.logger.debug(f"Waiting for response to command ID 0x{command_id:02x} for {timeout}s...")
        loop = asyncio.get_running_loop()
        end_time = loop.time() + timeout
        while True:
            remaining = end_time - loop.time()
            if remaining <= 0:
                break
            try:
                response = await asyncio.wait_for(self.notification_queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                break

            response_cmd_id = response.get('command_id')
            is_expected_response = response_cmd_id == command_id
            is_generic_ack = response_cmd_id == models.GENERIC_ACK_COMMAND_ID and command_id in models.GENERIC_ACK_COMMANDS

            if is_expected_response:
                self.logger.debug(f"Got matching response for command ID 0x{command_id:02x} (Received 0x{response_cmd_id:02x})")
                self._expected_response_command = None
                return response.get('payload')
            elif is_generic_ack:
                self.logger.debug(f"Received generic ACK (0x33) for command 0x{command_id:02x}. Continuing to wait for final data response.")
            else:
                self.logger.warning(f"Got unexpected response. Expected 0x{command_id:02x}, got 0x{response_cmd_id:02x}. Discarding.")

        self.logger.warning(f"Timeout waiting for notification response to command ID: 0x{command_id:02x}")
        return None

    async def send_command_and_wait_for_response(self, command: int | str, args: list | None = None, timeout: float = 10.0) -> bytes | None:
        if not self.is_connected:
            self.logger.error(f"Cannot send command '{command}': Not connected to a Divoom device.")
            return None

        command_id = models.COMMANDS.get(command, command) if isinstance(command, str) else command

        # Hold the response lock across drain→set-scalar→send→wait so a concurrent
        # caller can't drain our frames or overwrite _expected_response_command
        # mid-flight (cross-talk). If it's already held, a sibling wait is in
        # progress — warn so a future off-queue regression is visible, not silent.
        if self._response_lock.locked():
            self.logger.warning(
                "send_command_and_wait_for_response(0x%02x) contended — another "
                "response wait is in flight; serializing to avoid cross-talk",
                command_id if isinstance(command_id, int) else 0)
        async with self._response_lock:
            while not self.notification_queue.empty():
                self.notification_queue.get_nowait()
                self.logger.debug("Cleared a stale notification from the queue.")

            self._expected_response_command = command_id
            await self.send_command(command, args, write_with_response=True)
            return await self.wait_for_response(command_id, timeout)
