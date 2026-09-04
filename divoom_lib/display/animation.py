import asyncio

from divoom_lib.sender_protocol import CommandSender
from divoom_lib.models import (
    COMMANDS,
    ANSGC_CONTROL_START_SENDING, ANSGC_CONTROL_SENDING_DATA, ANSGC_CONTROL_TERMINATE_SENDING,
    SUG_CONTROL_START_SAVING, SUG_CONTROL_TRANSMIT_DATA, SUG_CONTROL_TRANSMISSION_END,
    SUG_DATA_LED_EDITOR, SUG_DATA_SCROLL_ANIMATION,
    ANUD_CONTROL_START_SENDING, ANUD_CONTROL_SENDING_DATA, ANUD_CONTROL_TERMINATE_SENDING,
    ABUD_CONTROL_START_SENDING, ABUD_CONTROL_SENDING_DATA, ABUD_CONTROL_TERMINATE_SENDING,
    ABUD_CONTROL_DELETE, ABUD_CONTROL_PLAY_ARTWORK, ABUD_CONTROL_DELETE_ALL_BY_INDEX,
    AGUDI_CONTROL_WORD_SUCCESS, AGUDI_CONTROL_WORD_FAILURE
)
from .animation_user import AnimationUserDefine

class Animation(AnimationUserDefine):
    """
    Provides functionality to control the animation features of a Divoom device.

    Usage::

        import asyncio
        from divoom_lib import Divoom

        async def main():
            device_address = "XX:XX:XX:XX:XX:XX"  # Replace with your device's address
            divoom = Divoom(mac=device_address)
            
            try:
                await divoom.connect()
                await divoom.animation.set_gif_speed(100)
            finally:
                if divoom.is_connected:
                    await divoom.disconnect()

        if __name__ == "__main__":
            asyncio.run(main())
    """
    def __init__(self, divoom: CommandSender):
        """
        Initializes the Animation controller.

        Args:
            divoom: The Divoom object to send commands to the device.
        """
        super().__init__(divoom)

    async def set_gif_speed(self, speed: int) -> bool:
        """
        Set the animation speed for GIFs.
        """
        self.logger.info(f"Setting GIF speed to {speed}ms (0x16)...")
        args = speed.to_bytes(2, byteorder='little')
        return await self.communicator.send_command(COMMANDS["set gif speed"], list(args))

    async def set_light_phone_gif(self, total_len: int, gif_id: int, gif_data: list) -> bool:
        """
        Display user-drawn animations on the device (0x49).
        """
        self.logger.info(f"Setting light phone gif (0x49)...")
        args = []
        args += total_len.to_bytes(2, byteorder='little')
        args += gif_id.to_bytes(1, byteorder='big')
        args.extend(gif_data)
        return await self.communicator.send_command(COMMANDS["set light phone gif"], args)

    def _handle_ansgc_start_sending(self, kwargs: dict) -> list | None:
        file_size = kwargs.get("file_size")
        if file_size is not None:
            return list(file_size.to_bytes(4, byteorder='little'))
        self.logger.error("Missing 'file_size' for Start Sending control word.")
        return None

    def _handle_ansgc_sending_data(self, kwargs: dict) -> list | None:
        file_size = kwargs.get("file_size")
        file_offset_id = kwargs.get("file_offset_id")
        file_data = kwargs.get("file_data")
        if file_size is not None and file_offset_id is not None and file_data is not None:
            return list(file_size.to_bytes(4, byteorder='little')) + \
                   list(file_offset_id.to_bytes(2, byteorder='little')) + \
                   file_data
        self.logger.error("Missing 'file_size', 'file_offset_id', or 'file_data' for Sending Data control word.")
        return None

    def _handle_ansgc_terminate_sending(self, kwargs: dict) -> list | None:
        return [] # No additional data

    _ansgc_handlers = {
        ANSGC_CONTROL_START_SENDING: _handle_ansgc_start_sending,
        ANSGC_CONTROL_SENDING_DATA: _handle_ansgc_sending_data,
        ANSGC_CONTROL_TERMINATE_SENDING: _handle_ansgc_terminate_sending,
    }

    async def app_new_send_gif_cmd(self, control_word: int, write_with_response: bool = False, **kwargs) -> bool:
        """
        Send a new GIF animation to the device using the upgraded protocol.
        """
        self.logger.info(
            f"App new send GIF command with control word {control_word} (0x8b)...")
        args = [control_word]

        handler = self._ansgc_handlers.get(control_word)
        if handler:
            control_args = handler(self, kwargs)
            if control_args is not None:
                args.extend(control_args)
            else:
                return False
        else:
            self.logger.warning(
                f"Unknown control word for app_new_send_gif_cmd: {control_word}")
            return False

        return await self.communicator.send_command(COMMANDS["app new send gif cmd"], args, write_with_response=write_with_response)

    async def stream_animation_8b(self, blob: bytes) -> bool:
        """Stream a pre-encoded animation frame blob via the 0x8B 3-phase
        protocol, matching the **futpib** reference exactly
        (``references/divoom-refs/futpib/src/lib.rs`` ``create_network_packets_from``
        + ``protocol/animation.rs``), which is the canonical implementation of
        the same StartSeeding/SendingData/Terminate framing this command uses.

        Per futpib: ``file_offset_id`` is a sequential **chunk index**
        (0,1,2,…, u16 LE) and chunks are **256 bytes**. This pairing is
        load-bearing: the device reconstructs the file by placing chunk *N* at
        byte *N×256*, so a smaller chunk size (the monthly-best daemon used 200)
        leaves permanent gaps and the transfer never completes — the stall in
        R11 items 1c/2a/9.

        On top of the wire format we add BLE robustness (not in futpib, which
        targets a stream socket): write-with-response on BLE, 0.5s after start
        for buffer allocation, and a brief inter-chunk delay to avoid GATT
        congestion.

        R34 §1b — APK alignment (the official app is the authoritative protocol
        reference, `references/apk/`): the app's 0x8b flow is DEVICE-DRIVEN —
        after the start packet it WAITS for the device's "send the animation"
        response before streaming, and it serves per-chunk RETRANSMIT requests
        (`bluetooth/s.java` SPP_APP_NEW_GIF_CMD2020 handler →
        `DesignSendModel.startSendAllAni` / `resendBlueData`). We do both on
        BLE, degrading gracefully to the legacy fixed sleeps when the device
        doesn't respond (LAN/SPP or older firmware).

        R35 hardware verification (4 devices): the APK does NOT send CW=2
        (terminate). Neither do we — verified PASS on Timoo, Ditoo, Tivoo Max,
        and Pixoo with and without the terminate packet.

        Args:
            blob: concatenated per-frame bodies (see animation_8b._build_animation_blob).

        Returns:
            True if all phases succeeded, else False.
        """
        file_size = len(blob)
        if file_size <= 0:
            return False

        is_lan = getattr(self.communicator, "lan", None) is not None
        is_spp = getattr(self.communicator, "use_spp", False)
        is_ble = not is_lan and not is_spp
        write_with_response = is_ble
        delay = 0.01 if is_ble else 0.0

        # APK §2: set _expected_response_command BEFORE sending START so the
        # iOS LE notification handler routes the device's "[0] → ready" reply
        # into the notification_queue instead of dropping it. Without this the
        # handler sees expected_cmd=None, the device's ACK is lost, and we
        # sleep the full timeout before sending data — ~3.5s dead air which
        # exceeds the device's internal spinner timeout (~1-2s).
        _cmd_8b = COMMANDS["app new send gif cmd"]
        # R53.x HW: LISTEN for 0x8B for the whole stream. _await_8b_device_ready's
        # wait_for_response CLEARS the scalar on the start-ACK match, so for the chunk
        # loop AND the retransmit window _expected_response_command is None — and 0x8B
        # is not a generic-ACK command, so without it in _listen_commands the
        # notification handler DROPS every unsolicited retransmit request. The device's
        # "re-send chunk N" was then lost, the chunk never recovered, and the stream
        # STILL returned True (ACK != success). Listening queues those frames WITHOUT
        # consuming the scalar (handler is_listened branch), so _serve_8b_retransmits
        # can actually serve them. Scoped to the stream; removed in finally.
        _listen = getattr(self.communicator, "_listen_commands", None)
        _listening_8b = is_ble and isinstance(_listen, set)
        if is_ble and hasattr(self.communicator, '_expected_response_command'):
            self.communicator._expected_response_command = _cmd_8b
        if _listening_8b:
            _listen.add(_cmd_8b)

        try:
            if not await self.app_new_send_gif_cmd(
                control_word=ANSGC_CONTROL_START_SENDING, file_size=file_size
            ):
                self.logger.error("0x8B start phase failed")
                return False

            # APK: wait for the device's "ready, send it" reply to the start packet
            # rather than guessing how long buffer allocation takes. Fall back to
            # the legacy 0.5s sleep when no reply arrives.
            if not (is_ble and await self._await_8b_device_ready(timeout=2.0)):
                await asyncio.sleep(0.5)  # let the device allocate buffers

            chunk_size = 256  # MUST match futpib/APK (hVar.q(256)); chunk N → byte N*256
            offset_id = 0
            for i in range(0, file_size, chunk_size):
                chunk = list(blob[i:i + chunk_size])
                if not await self.app_new_send_gif_cmd(
                    control_word=ANSGC_CONTROL_SENDING_DATA,
                    file_size=file_size,
                    file_offset_id=offset_id,
                    file_data=chunk,
                    write_with_response=write_with_response,
                ):
                    self.logger.error(f"0x8B data chunk {offset_id} failed")
                    return False
                offset_id += 1
                if delay > 0:
                    await asyncio.sleep(delay)

            # APK: the device may ask for dropped chunks to be re-sent; without
            # this, one lost chunk = a permanently failed upload.
            if is_ble:
                await self._serve_8b_retransmits(blob, file_size, chunk_size,
                                                 write_with_response)

            # APK: no terminate packet (CW=2). Verified on 4 hardware devices
            # (Timoo, Ditoo, Tivoo Max, Pixoo) — animation renders correctly
            # without it.
            return True
        finally:
            # ALWAYS clear the scalar we set before START. wait_for_response clears
            # it on a match mid-stream, but on the device-ready-timeout or
            # chunk-failure paths it would otherwise stay pinned to 0x8B and
            # mis-route the NEXT op's notifications (cross-talk). The during-stream
            # handshake is unchanged — this only guarantees cleanup on exit.
            if is_ble and hasattr(self.communicator, '_expected_response_command'):
                self.communicator._expected_response_command = None
            if _listening_8b:
                _listen.discard(_cmd_8b)

    async def _await_8b_device_ready(self, timeout: float = 3.0) -> bool:
        """Wait for the device's 0x8b response with ``payload[0] == 0`` —
        APK semantics: "device requests the animation" (`bluetooth/s.java`,
        SPP_APP_NEW_GIF_CMD2020 handler, response byte 0 →
        ``DesignSendModel.startSendAllAni()``). Returns False on timeout or
        when the transport has no response channel (caller falls back to the
        legacy fixed sleep)."""
        wait = getattr(self.communicator, "wait_for_response", None)
        if wait is None:
            return False
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while True:
            remaining = end - loop.time()
            if remaining <= 0:
                return False
            payload = await wait(COMMANDS["app new send gif cmd"], timeout=remaining)
            if payload is None:
                return False
            if len(payload) >= 1 and payload[0] == 0:
                self.logger.info("0x8B: device requested the animation (start ACK)")
                return True
            # Anything else (stale frame, early retransmit) — keep waiting.

    async def _serve_8b_retransmits(self, blob: bytes, file_size: int,
                                    chunk_size: int, write_with_response: bool,
                                    quiet_timeout: float = 1.0,
                                    max_requests: int = 256) -> None:
        """Serve the device's 0x8b retransmit requests after the chunk stream —
        APK semantics: response ``[1][chunk_idx:2 LE]`` means "re-send chunk N"
        (`bluetooth/s.java` → ``DesignSendModel.resendBlueData(N)``). Stops when
        the device goes quiet for ``quiet_timeout`` (the normal end state) or
        after ``max_requests`` (safety valve). Best-effort: never raises."""
        wait = getattr(self.communicator, "wait_for_response", None)
        if wait is None:
            return
        for _ in range(max_requests):
            try:
                payload = await wait(COMMANDS["app new send gif cmd"],
                                     timeout=quiet_timeout)
            except Exception:
                return
            if payload is None:
                return  # quiet — device has everything
            if len(payload) >= 3 and payload[0] == 1:
                idx = int.from_bytes(bytes(payload[1:3]), byteorder="little")
                start = idx * chunk_size
                if start >= file_size:
                    self.logger.warning(f"0x8B retransmit request out of range: {idx}")
                    continue
                self.logger.info(f"0x8B: device requested retransmit of chunk {idx}")
                await self.app_new_send_gif_cmd(
                    control_word=ANSGC_CONTROL_SENDING_DATA,
                    file_size=file_size,
                    file_offset_id=idx,
                    file_data=list(blob[start:start + chunk_size]),
                    write_with_response=write_with_response,
                )
            # payload[0] == 0 here would be a late start-ACK — ignore.

    async def set_rhythm_gif(self, pos: int, total_length: int, gif_id: int, data: list) -> bool:
        """
        Set the related information for the rhythm animation.
        """
        self.logger.info(
            f"Setting rhythm GIF: pos={pos}, total_length={total_length}, gif_id={gif_id} (0xb7)...")
        args = []
        args += pos.to_bytes(1, byteorder='big')
        args += total_length.to_bytes(2, byteorder='little')
        args += gif_id.to_bytes(1, byteorder='big')
        args.extend(data)
        return await self.communicator.send_command(COMMANDS["set rhythm gif"], args)

    async def app_send_eq_gif(self, pos: int, total_length: int, gif_id: int, data: list) -> bool:
        """
        Send an EQ rhythm animation to the device.
        """
        self.logger.info(
            f"App sending EQ GIF: pos={pos}, total_length={total_length}, gif_id={gif_id} (0x1b)...")
        args = []
        args += pos.to_bytes(1, byteorder='big')
        args += total_length.to_bytes(2, byteorder='little')
        args += gif_id.to_bytes(1, byteorder='big')
        args.extend(data)
        return await self.communicator.send_command(COMMANDS["app send eq gif"], args)
