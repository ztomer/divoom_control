"""Fault-injecting BLE device double for the hardening suite.

Scriptable to drop, time out, lie about ``is_connected``, fail the Nth connect,
or look "busy" — so every connect/reconnect/health path is testable in CI
without hardware. Mirrors the minimal surface ``ble_connection.ensure_connected``
(and later phases) rely on: async ``connect()`` / ``disconnect()`` and an
``is_connected`` property.
"""
from __future__ import annotations

import asyncio


class FakeBleDevice:
    def __init__(self, *, connect_results=None, raise_on_connect=None,
                 lie_connected=False):
        """``connect_results``: optional list consumed per connect() call; each
        item is True (connect succeeds), False (succeeds-but-stays-disconnected:
        the CoreBluetooth lie), or an Exception instance to raise.
        ``raise_on_connect``: a single Exception raised on every connect (shorthand).
        ``lie_connected``: if True, is_connected reports True even after a drop.
        """
        self._connected = False
        self._results = list(connect_results) if connect_results else None
        self._raise = raise_on_connect
        self._lie = lie_connected
        self.connect_calls = 0
        self.disconnect_calls = 0

    @property
    def is_connected(self) -> bool:
        return True if self._lie else self._connected

    @property
    def is_alive(self) -> bool:
        # P2 honest liveness: the REAL state, even when is_connected lies (the OS
        # disconnect callback flips this immediately; drop() simulates it).
        return self._connected

    async def connect(self):
        self.connect_calls += 1
        await asyncio.sleep(0)
        if self._raise is not None:
            raise self._raise
        if self._results is not None:
            outcome = self._results.pop(0) if self._results else True
            if isinstance(outcome, BaseException):
                raise outcome
            self._connected = bool(outcome)   # False = the "lie" (stays down)
            return
        self._connected = True

    async def disconnect(self):
        self.disconnect_calls += 1
        await asyncio.sleep(0)
        self._connected = False

    # Test helper: simulate the device vanishing mid-session.
    def drop(self):
        self._connected = False
