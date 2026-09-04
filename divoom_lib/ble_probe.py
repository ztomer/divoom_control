"""BLE protocol auto-probe.

On first connect, when ``use_ios_le_protocol`` is unset, the transport doesn't
know whether the device speaks the iOS-LE framing or the Basic framing. We probe
by sending a 0x46 query in each framing and seeing which one the device answers.
Extracted from ``ble_transport.py`` to keep that file under the 500-LOC cap.
"""
from __future__ import annotations

import asyncio
from typing import Any

_PROBE_CMD = 0x46
_PROBE_TIMEOUT = 1.5


async def autoprobe_protocol(t: Any) -> None:
    """Detect + set ``t.use_ios_le_protocol`` by probing both framings.

    No-op if the framing is already known. On success sets the framing and
    clears ``_expected_response_command``; if neither answers, defaults to Basic.
    """
    if t.use_ios_le_protocol is not None:
        return

    t.logger.info("use_ios_le_protocol not set. Probing BLE protocol format...")
    payload = [_PROBE_CMD]

    async def _try(send, label: str) -> bool:
        try:
            if await send(payload, write_with_response=True):
                if await t.wait_for_response(_PROBE_CMD, timeout=_PROBE_TIMEOUT) is not None:
                    t.logger.info("Protocol probe succeeded: Detected %s BLE!", label)
                    return True
        except Exception as e:  # a probe write/timeout is not fatal — fall through
            t.logger.debug("%s probe raised: %s", label, e)
        return False

    t.escapePayload = False

    t.use_ios_le_protocol = True
    t._expected_response_command = _PROBE_CMD
    if await _try(t._send_ios_le_payload, "iOS-LE Protocol"):
        t._expected_response_command = None
        return

    t.use_ios_le_protocol = False
    t._expected_response_command = _PROBE_CMD
    if await _try(t._send_basic_protocol_payload, "Basic Protocol"):
        t._expected_response_command = None
        return

    t.logger.info("Both BLE protocol probes failed. Defaulting to BLE Basic Protocol.")
    t.use_ios_le_protocol = False
    t._expected_response_command = None
