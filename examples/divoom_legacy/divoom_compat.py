# divoom_legacy/divoom_compat.py
"""Backward-compatible pass-through properties of the ``Divoom`` facade.

Each one reads or writes the same attribute on ``self._conn`` (the
``DivoomConnection`` that owns the BLE link), so callers and tests written
against the pre-split API keep working. Split out of ``divoom.py``, whose
``Divoom`` class inherits this mixin.
"""

from typing import Any


class ConnectionCompatMixin:
    """Delegating properties onto ``self._conn``; see the module docstring."""

    # ── Backwards Compatible Client Properties ───────────────────────────────────

    @property
    def client(self) -> Any:
        return self._conn.client

    @client.setter
    def client(self, val: Any) -> None:
        self._conn.client = val

    @property
    def notification_queue(self) -> Any:
        return self._conn.notification_queue

    @notification_queue.setter
    def notification_queue(self, val: Any) -> None:
        self._conn.notification_queue = val

    def drain_notifications(self) -> int:
        """Discard any queued (stale/unsolicited) notification frames so the next
        query reads its OWN fresh response. The device sends unsolicited frames
        on state change (e.g. a 0x46 when brightness changes), which otherwise
        make manual read-back methods lag one step behind. Returns the count
        drained. Mirrors the drain in send_command_and_wait_for_response."""
        q = self._conn.notification_queue
        n = 0
        while not q.empty():
            try:
                q.get_nowait()
                n += 1
            except Exception:
                break
        return n

    @property
    def use_ios_le_protocol(self) -> bool:
        return self._conn.use_ios_le_protocol

    @use_ios_le_protocol.setter
    def use_ios_le_protocol(self, val: bool) -> None:
        self._conn.use_ios_le_protocol = val

    @property
    def message_buf(self) -> bytearray:
        return self._conn.message_buf

    @message_buf.setter
    def message_buf(self, val: bytearray) -> None:
        self._conn.message_buf = val

    @property
    def WRITE_CHARACTERISTIC_UUID(self) -> str:
        return self._conn.WRITE_CHARACTERISTIC_UUID

    @WRITE_CHARACTERISTIC_UUID.setter
    def WRITE_CHARACTERISTIC_UUID(self, val: str) -> None:
        self._conn.WRITE_CHARACTERISTIC_UUID = val

    @property
    def NOTIFY_CHARACTERISTIC_UUID(self) -> str:
        return self._conn.NOTIFY_CHARACTERISTIC_UUID

    @NOTIFY_CHARACTERISTIC_UUID.setter
    def NOTIFY_CHARACTERISTIC_UUID(self, val: str) -> None:
        self._conn.NOTIFY_CHARACTERISTIC_UUID = val

    @property
    def READ_CHARACTERISTIC_UUID(self) -> str:
        return self._conn.READ_CHARACTERISTIC_UUID

    @READ_CHARACTERISTIC_UUID.setter
    def READ_CHARACTERISTIC_UUID(self, val: str) -> None:
        self._conn.READ_CHARACTERISTIC_UUID = val

    @property
    def SPP_CHARACTERISTIC_UUID(self) -> str:
        return self._conn.SPP_CHARACTERISTIC_UUID

    @SPP_CHARACTERISTIC_UUID.setter
    def SPP_CHARACTERISTIC_UUID(self, val: str) -> None:
        self._conn.SPP_CHARACTERISTIC_UUID = val

    @property
    def escapePayload(self) -> bool:
        return self._conn.escapePayload

    @escapePayload.setter
    def escapePayload(self, val: bool) -> None:
        self._conn.escapePayload = val

    @property
    def max_reconnect_attempts(self) -> int:
        return self._conn.max_reconnect_attempts

    @max_reconnect_attempts.setter
    def max_reconnect_attempts(self, val: int) -> None:
        self._conn.max_reconnect_attempts = val

    @property
    def reconnect_delay(self) -> float:
        return self._conn.reconnect_delay

    @reconnect_delay.setter
    def reconnect_delay(self, val: float) -> None:
        self._conn.reconnect_delay = val
