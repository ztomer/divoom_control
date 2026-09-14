import asyncio
import inspect
import logging
import sys
from typing import Callable, Any

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='[MockDevice] %(message)s')
logger = logging.getLogger("MockDevice")

class MockBleakClient:
    """
    A mock class that mimics the behavior of bleak.BleakClient for Divoom devices.
    It simulates connection, disconnection, and characteristic read/write/notify.
    """
    def __init__(self, address: str, **kwargs):
        self.address = address
        self._is_connected = False
        self._notify_callbacks = {}
        self._notification_task = None
        # Record every frame the "device" receives so tests can assert the exact
        # wire bytes produced by the library (hardware-free end-to-end checks).
        self.written = []
        self.clock_style = 0
        self.brightness = 100
        logger.info(f"Initialized MockBleakClient for {address}")

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    async def connect(self, **kwargs) -> bool:
        logger.info(f"Connecting to {self.address}...")
        await asyncio.sleep(0.5) # Simulate connection delay
        self._is_connected = True
        logger.info("Connected!")
        return True

    async def disconnect(self) -> bool:
        logger.info("Disconnecting...")
        self._is_connected = False
        if self._notification_task:
            self._notification_task.cancel()
        logger.info("Disconnected.")
        return True

    async def start_notify(self, char_specifier: str, callback: Callable[[int, bytearray], None], **kwargs) -> None:
        logger.info(f"Starting notifications on {char_specifier}")
        self._notify_callbacks[char_specifier] = callback

    async def stop_notify(self, char_specifier: str) -> None:
        logger.info(f"Stopping notifications on {char_specifier}")
        if char_specifier in self._notify_callbacks:
            del self._notify_callbacks[char_specifier]

    async def write_gatt_char(self, char_specifier: str, data: bytes | bytearray, response: bool = False) -> None:
        logger.info(f"Write to {char_specifier}: {data.hex()}")
        self.written.append((char_specifier, bytes(data)))

        # Simulate processing delay
        await asyncio.sleep(0.1)

        # Logic to generate a response based on the input data
        response_data = self._generate_response(data)

        if response_data:
            await self._trigger_notification(char_specifier, response_data)

    def _generate_response(self, data: bytes) -> bytes | None:
        """
        Generates a mock response based on the input command.
        This is where the "device logic" lives.
        """
        # Basic Protocol Logic
        if data.startswith(b'\x01'):
            # Parse Basic Protocol
            try:
                length = int.from_bytes(data[1:3], 'little')
                payload = data[3:3+length-2] # Exclude checksum
                cmd = payload[0]
                logger.debug(f"Received Basic Protocol CMD: 0x{cmd:02x}")

                # Example: Get Settings (0x46) -> Respond with stateful settings
                if cmd == 0x46:
                    resp_payload = bytearray(23)
                    resp_payload[0:3] = b'\x04\x46\x55'
                    resp_payload[3 + 6] = self.brightness
                    resp_payload[3 + 15] = self.clock_style
                    return self._frame_basic_response(bytes(resp_payload))

                elif cmd == 0x45:
                    if len(payload) >= 4 and payload[1] == 0x00:
                        self.clock_style = payload[3]
                        logger.debug(f"MockDevice: Set clock style to {self.clock_style}")
                    return self._frame_basic_response(bytes([0x04, 0x45, 0x55, 0x00]))

                elif cmd == 0x74:
                    if len(payload) >= 2:
                        self.brightness = payload[1]
                        logger.debug(f"MockDevice: Set brightness to {self.brightness}")
                    return self._frame_basic_response(bytes([0x04, 0x74, 0x55, 0x00]))

            except Exception as e:
                logger.error(f"Failed to parse Basic Protocol packet: {e}")

        # iOS LE Protocol Logic
        elif data.startswith(b'\xfe\xef\xaa\x55'):
             try:
                # Header (4) + Len (2) + Cmd (1)
                cmd = data[6]
                payload = data[11:-2] # Exclude header, len, cmd, packetnum, crc
                logger.debug(f"Received iOS LE Protocol CMD: 0x{cmd:02x}")

                if cmd == 0x46: # Get Settings
                     # Respond with 20-byte payload in iOS LE format
                     resp_payload = bytearray(20)
                     resp_payload[6] = self.brightness
                     resp_payload[15] = self.clock_style
                     return self._frame_ios_response(cmd, bytes(resp_payload))

                elif cmd == 0x45:
                     if len(payload) >= 4 and payload[1] == 0x00:
                         self.clock_style = payload[3]
                         logger.debug(f"MockDevice: Set clock style to {self.clock_style}")
                     return self._frame_ios_response(cmd, b'\x00')

                elif cmd == 0x74:
                     if len(payload) >= 2:
                         self.brightness = payload[1]
                         logger.debug(f"MockDevice: Set brightness to {self.brightness}")
                     return self._frame_ios_response(cmd, b'\x00')

             except Exception as e:
                logger.error(f"Failed to parse iOS LE packet: {e}")

        return None

    def _frame_basic_response(self, payload: bytes) -> bytes:
        """Frames a payload into a Basic Protocol message."""
        # 01 LEN_L LEN_H PAYLOAD CRC_L CRC_H 02
        length = len(payload) + 2 # +2 for CRC
        len_bytes = length.to_bytes(2, 'little')

        # Calculate CRC (sum of length + payload)
        checksum_val = sum(len_bytes) + sum(payload)
        crc_bytes = checksum_val.to_bytes(2, 'little')

        return b'\x01' + len_bytes + payload + crc_bytes + b'\x02'

    def _frame_ios_response(self, cmd: int, payload: bytes) -> bytes:
        """Frames a payload into an iOS LE Protocol message."""
        header = b'\xfe\xef\xaa\x55'
        packet_num = b'\x00\x00\x00\x00'

        # Length = Cmd(1) + PacketNum(4) + Payload(N) + CRC(2)
        data_len = 1 + 4 + len(payload) + 2
        len_bytes = data_len.to_bytes(2, 'little')

        # CRC Input = Len + Cmd + PacketNum + Payload
        crc_input = len_bytes + bytes([cmd]) + packet_num + payload
        crc_val = sum(crc_input)
        crc_bytes = crc_val.to_bytes(2, 'little')

        return header + len_bytes + bytes([cmd]) + packet_num + payload + crc_bytes

    async def _trigger_notification(self, char_specifier: str, data: bytes) -> None:
        """Simulates an incoming notification from the device."""
        # In a real scenario, the notify UUID might be different from the write UUID.
        # Here we just look for any registered callback.
        # Assuming the user registered on the NOTIFY characteristic.

        # Find a callback (simplified)
        callback = None
        if self._notify_callbacks:
            callback = list(self._notify_callbacks.values())[0]

        if callback:
            logger.info(f"Sending notification: {data.hex()}")
            # Call the callback (sender_handle, data)
            # In bleak, callback is often a partial or bound method, but signature is (sender, data)
            if inspect.iscoroutinefunction(callback):
                 await callback(1, data)
            else:
                 callback(1, data)
        else:
            logger.warning("No notification callback registered, dropping response.")

async def main():
    """
    Interactive mode to test the MockBleakClient.
    """
    print("--- Divoom Mock Device Interactive Mode ---")
    client = MockBleakClient("00:11:22:33:44:55")
    await client.connect()

    def notification_handler(sender, data):
        print(f"\n[Notification] Received: {data.hex()}")

    await client.start_notify("mock-notify-uuid", notification_handler)

    print("\nEnter hex command to send (e.g., '010400460002' for Get Settings in Basic Protocol)")
    print("Type 'exit' to quit.")

    while True:
        user_input = await asyncio.to_thread(sys.stdin.readline)
        user_input = user_input.strip()

        if user_input.lower() == 'exit':
            break

        try:
            data = bytes.fromhex(user_input)
            await client.write_gatt_char("mock-write-uuid", data)
        except ValueError:
            print("Invalid hex string.")
        except Exception as e:
            print(f"Error: {e}")

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
