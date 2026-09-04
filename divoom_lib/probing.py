import asyncio
from typing import Any

def _get_cache_module(cache_mod=None):
    if cache_mod is not None:
        return cache_mod
    from .utils import cache as cache_mod
    return cache_mod

async def _try_send_command_with_framing(conn: Any, command_id: int, payload: list, timeout: float = 3.0, use_ios: bool = False, escape: bool = False):
    conn.use_ios_le_protocol = use_ios
    conn.escapePayload = escape
    return await conn._divoom.send_command_and_wait_for_response(command_id, payload, timeout=timeout)

async def _send_diagnostic_payload(conn: Any, write_uuid: str, args_payload: list, cache_data: dict, cache_dir: str, device_id: str, cache_mod: Any = None):
    cache_mod = _get_cache_module(cache_mod)
    conn.WRITE_CHARACTERISTIC_UUID = write_uuid

    # 1. Try SPP first (escaped)
    resp = await conn._divoom._try_send_command_with_framing(0x45, args_payload, timeout=3.0, use_ios=False, escape=True)
    if resp is not None:
        conn.use_ios_le_protocol = False
        conn.escapePayload = True
        existing = cache_data or {}
        existing.update({
            "write_characteristic_uuid": write_uuid,
            "ack_characteristic_uuid": conn.NOTIFY_CHARACTERISTIC_UUID,
            "last_successful_payload": [f"{b:02x}" for b in args_payload],
            "last_successful_use_ios_le": False,
            "escapePayload": True,
        })
        try:
            await asyncio.to_thread(cache_mod.save_device_cache, cache_dir, device_id, existing)
        except OSError:
            pass
        return True

    # 2. Try iOS-LE fallback (non-escaped)
    resp = await conn._divoom._try_send_command_with_framing(0x45, args_payload, timeout=3.0, use_ios=True, escape=False)
    if resp is not None:
        conn.use_ios_le_protocol = True
        conn.escapePayload = False
        existing = cache_data or {}
        existing.update({
            "write_characteristic_uuid": write_uuid,
            "ack_characteristic_uuid": conn.NOTIFY_CHARACTERISTIC_UUID,
            "last_successful_payload": [f"{b:02x}" for b in args_payload],
            "last_successful_use_ios_le": True,
            "escapePayload": False,
        })
        try:
            await asyncio.to_thread(cache_mod.save_device_cache, cache_dir, device_id, existing)
        except OSError:
            pass
        return True

    return False

async def _handle_cached_payload(conn: Any, write_uuid: str, cached_data: dict, cache_dir: str, device_id: str, cache_mod: Any = None):
    cache_mod = _get_cache_module(cache_mod)
    payload_hex = cached_data.get("last_successful_payload")
    if not payload_hex:
        return False

    try:
        payload = [int(x, 16) for x in payload_hex]
    except Exception:
        return False

    conn.WRITE_CHARACTERISTIC_UUID = write_uuid
    use_ios = bool(cached_data.get("last_successful_use_ios_le", False))
    escape = bool(cached_data.get("escapePayload", False))

    resp = await conn._divoom._try_send_command_with_framing(0x45, payload, timeout=3.0, use_ios=use_ios, escape=escape)
    if resp is not None:
        conn.use_ios_le_protocol = use_ios
        conn.escapePayload = escape
        existing = cached_data or {}
        existing.update({
            "write_characteristic_uuid": write_uuid,
            "ack_characteristic_uuid": conn.NOTIFY_CHARACTERISTIC_UUID,
            "last_successful_payload": payload_hex,
            "last_successful_use_ios_le": use_ios,
            "escapePayload": escape,
        })
        try:
            await asyncio.to_thread(cache_mod.save_device_cache, cache_dir, device_id, existing)
        except OSError:
            pass
        return True
    return False

async def probe_write_characteristics_and_try_channel_switch(conn: Any, write_chars: list, notify_chars: list, read_chars: list, cached_data: dict, cache_dir: str, device_id: str, colors: list = None, cache_mod: Any = None):
    cache_mod = _get_cache_module(cache_mod)
    colors = colors or [
        (0xFF, 0x00, 0x00),
        (0x00, 0xFF, 0x00),
        (0x00, 0x00, 0xFF),
        (0xFF, 0xFF, 0x00),
        (0xFF, 0x00, 0xFF),
        (0x00, 0xFF, 0xFF),
    ]

    for idx, ch in enumerate(write_chars):
        uuid = ch.uuid
        conn.WRITE_CHARACTERISTIC_UUID = uuid

        # Try cached payload first
        if cached_data and cached_data.get("last_successful_payload"):
            if await _handle_cached_payload(conn, uuid, cached_data, cache_dir, device_id, cache_mod):
                return uuid

        # Try diagnostic color payload
        r, g, b = colors[idx % len(colors)]
        args_payload = [0x01, r, g, b, 100, 0x00, 0x01, 0x00, 0x00, 0x00]
        if await _send_diagnostic_payload(conn, uuid, args_payload, cached_data, cache_dir, device_id, cache_mod):
            return uuid

    # Fallback if nothing else worked
    try:
        await conn._divoom.send_command(0x05, [0x09])
        await asyncio.sleep(0.1)
        await conn._divoom.send_command(0x8a, [0x02])
        await asyncio.sleep(0.1)

        # Try SPP
        resp = await conn._divoom._try_send_command_with_framing(0x45, [0x02], timeout=3.0, use_ios=False, escape=True)
        if resp is not None:
            conn.use_ios_le_protocol = False
            conn.escapePayload = True
            return None

        # Try iOS-LE
        resp = await conn._divoom._try_send_command_with_framing(0x45, [0x02], timeout=3.0, use_ios=True, escape=False)
        if resp is not None:
            conn.use_ios_le_protocol = True
            conn.escapePayload = False
            return None
    except Exception:
        pass

    return None

async def set_canonical_light(conn: Any, cache_dir: str, device_id: str, cache_mod: Any = None, rgb: list = None):
    cache_mod = _get_cache_module(cache_mod)
    rgb = rgb or [0xFF, 0xFF, 0xFF]
    args = [0x01] + rgb + [100, 0x00, 0x01, 0x00, 0x00, 0x00]

    # 1. Try SPP
    resp = await conn._divoom._try_send_command_with_framing(0x45, args, timeout=3.0, use_ios=False, escape=True)
    if resp is not None:
        conn.use_ios_le_protocol = False
        conn.escapePayload = True
        try:
            existing = await asyncio.to_thread(cache_mod.load_device_cache, cache_dir, device_id) or {}
            existing.update({
                "last_successful_payload": [f"{b:02x}" for b in args],
                "last_successful_use_ios_le": False,
                "escapePayload": True,
                "write_characteristic_uuid": conn.WRITE_CHARACTERISTIC_UUID,
            })
            await asyncio.to_thread(cache_mod.save_device_cache, cache_dir, device_id, existing)
        except OSError:
            pass
        return True

    # 2. Try iOS-LE
    resp = await conn._divoom._try_send_command_with_framing(0x45, args, timeout=3.0, use_ios=True, escape=False)
    if resp is not None:
        conn.use_ios_le_protocol = True
        conn.escapePayload = False
        try:
            existing = await asyncio.to_thread(cache_mod.load_device_cache, cache_dir, device_id) or {}
            existing.update({
                "last_successful_payload": [f"{b:02x}" for b in args],
                "last_successful_use_ios_le": True,
                "escapePayload": False,
                "write_characteristic_uuid": conn.WRITE_CHARACTERISTIC_UUID,
            })
            await asyncio.to_thread(cache_mod.save_device_cache, cache_dir, device_id, existing)
        except OSError:
            pass
        return True

    return False
