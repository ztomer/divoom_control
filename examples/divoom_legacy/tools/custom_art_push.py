"""Custom art (user-define) channel push — LightMakeNewModel.java port.

Protocol (APK-verified):
  p1(page) → N2(page, 12-items) header → hVar.d() data chunks → K0() end

Two modes:
  Old (0xB1 / SPP_SET_USER_GIF):   header=[0,0,page]  data=[1][chunk_sz:2][slice]
  New (0x8C / SPP_APP_NEW_USER_DEFINE2020): header=[0,totalLen:4,page]
                                          data=[1][total_len:4][idx:2][slice]
  K0() = [0x02] on whichever command the mode uses.

See docs/CUSTOM_CHANNEL_VS_APK.md for full wire-format tables.
"""

from __future__ import annotations

import asyncio
import logging

from divoom_lib.models import COMMANDS

logger = logging.getLogger("divoom_lib.custom_art_push")

SLOTS_PER_PAGE = 12
CHUNK_SIZE = 256  # hVar.q(256) — matches APK n().q(256)
INTER_CHUNK_DELAY = 0.04  # APK old-mode q.s().I(true) sleeps 40ms between sends

# 0x8E page-query read-back: a responsive device answers sub-second; many
# devices (e.g. Pixoo, HW-verified 2026-06) never reply at all. Bound it tight
# so a non-answering device fails fast instead of wedging the serialized command
# queue for the full 10s default — every other op for that device blocks behind it.
QUERY_TIMEOUT = 4.0

_CMD_OLD = COMMANDS["set user gif"]           # 0xB1
_CMD_NEW = COMMANDS["app new user define"]     # 0x8C


def _le16(v: int) -> list[int]:
    return [v & 0xFF, (v >> 8) & 0xFF]


def _le32(v: int) -> list[int]:
    return [v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF, (v >> 24) & 0xFF]


# ── N2 header ────────────────────────────────────────────────────────────

def build_n2_header(page: int, total_encoded_len: int | None = None) -> tuple[int, list[int]]:
    """Build the N2() header command + args.

    Old mode (no total_encoded_len):
        (0xB1, [0x00, 0x00, page])
    New mode (total_encoded_len provided):
        (0x8C, [0x00, *total_encoded_len:4 LE, page])

    Returns:
        (command_id, args_list)
    """
    if total_encoded_len is not None:
        return _CMD_NEW, [0x00] + _le32(total_encoded_len) + [page & 0xFF]
    return _CMD_OLD, [0x00, 0x00, page & 0xFF]


# ── Data chunk packets ───────────────────────────────────────────────────

def build_data_packets(encoded_blob: bytes, total_len: int,
                       use_new_mode: bool) -> list[tuple[int, list[int]]]:
    """Chunk encoded data into hVar.d()-compatible SPP command payloads.

    Returns list of (command_id, args_list) suitable for send_command().
    The APK's hVar.d() splits the blob into CHUNK_SIZE pieces and wraps
    each in an SPP frame via s.c(cmd, chunk_payload).

    Old mode (p=true, f30417j=true):
        per chunk: [0x01][chunk_size:2 LE][data_slice]
    New mode (p=false, i=true, f30416i=true → i9=4, i11=2):
        per chunk: [0x01][total_len:4 LE][chunk_idx:2 LE][data_slice]
    """
    cmd = _CMD_NEW if use_new_mode else _CMD_OLD
    packets: list[tuple[int, list[int]]] = []
    offset = 0
    idx = 0
    while offset < len(encoded_blob):
        chunk = encoded_blob[offset:offset + CHUNK_SIZE]
        chunk_size = len(chunk)
        if use_new_mode:
            args = [0x01] + _le32(total_len) + _le16(idx) + list(chunk)
        else:
            args = [0x01] + _le16(chunk_size) + list(chunk)
        packets.append((cmd, args))
        offset += CHUNK_SIZE
        idx += 1
    return packets


# ── K0 end signal ────────────────────────────────────────────────────────

def build_k0(use_new_mode: bool) -> tuple[int, list[int]]:
    """Build the K0() end-of-transmission signal.

    Returns:
        (command_id, [0x02])
    """
    return (_CMD_NEW if use_new_mode else _CMD_OLD, [0x02])


# ── Push entry points ────────────────────────────────────────────────────

async def push_page(divoom, page: int,
                    encoded_frames: list[bytes],
                    use_new_mode: bool = True) -> bool:
    """Push encoded frames to a custom art page on the device.

    This matches the APK's LightMakeNewModel.r() → v() → y() + K0() flow.

    Args:
        divoom: connected Divoom instance (or anything with send_command)
        page: target page index 0, 1, or 2
        encoded_frames: list of AA-encoded frame blobs, one per slot
                        (must be exactly SLOTS_PER_PAGE = 12 items; pad with
                        empty frames if needed)
        use_new_mode: True for 0x8C protocol, False for 0xB1 legacy

    Returns:
        True if all phases succeeded.
    """
    total_len = sum(len(f) for f in encoded_frames)

    # 1. N2 header
    cmd, args = build_n2_header(page, total_len if use_new_mode else None)
    logger.info("Sending N2 header (cmd=0x%02x page=%d total_len=%d)", cmd, page, total_len)
    if not await divoom.send_command(cmd, args):
        logger.error("N2 header send failed")
        return False

    # 2. Data chunks (y() → hVar.d())
    encoded_blob = b"".join(encoded_frames)
    packets = build_data_packets(encoded_blob, total_len, use_new_mode)
    logger.info("Sending %d data chunks (total %d bytes)", len(packets), total_len)
    for i, (pkt_cmd, pkt_args) in enumerate(packets):
        if not await divoom.send_command(pkt_cmd, pkt_args):
            logger.error("Data chunk %d/%d send failed", i + 1, len(packets))
            return False
        if not use_new_mode:
            await asyncio.sleep(INTER_CHUNK_DELAY)

    # 3. K0 end signal
    cmd, args = build_k0(use_new_mode)
    logger.info("Sending K0 end signal (cmd=0x%02x)", cmd)
    if not await divoom.send_command(cmd, args):
        logger.error("K0 end signal send failed")
        return False

    return True


async def push_slot(divoom, page: int, slot: int,
                    encoded_frame: bytes,
                    existing_frames: list[bytes] | None = None,
                    use_new_mode: bool = True) -> bool:
    """Push one frame to a specific slot by merging with existing page data.

    The APK's o() method loads existing 12-slot page data, finds the
    first empty slot or uses the specified slot, inserts the new frame,
    and sends the full page.

    Args:
        divoom: connected Divoom instance
        page: target page 0, 1, or 2
        slot: target slot 0-11 (ignored if existing_frames has content
              in this slot; the frame replaces it)
        encoded_frame: AA-encoded frame blob for this slot
        existing_frames: current 12 frames on the page (or None to
                         create empty page)
        use_new_mode: True for 0x8C protocol

    Returns:
        True on success.
    """
    if existing_frames is None:
        frames = [b""] * SLOTS_PER_PAGE
    else:
        frames = list(existing_frames)
        while len(frames) < SLOTS_PER_PAGE:
            frames.append(b"")

    if slot is not None and 0 <= slot < SLOTS_PER_PAGE:
        frames[slot] = encoded_frame
    else:
        # auto-assign first empty slot
        for i in range(SLOTS_PER_PAGE):
            if not frames[i]:
                frames[i] = encoded_frame
                slot = i
                break

    logger.info("Pushing frame to page=%d slot=%d (mode=%s)", page, slot,
                "new" if use_new_mode else "old")
    return await push_page(divoom, page, frames, use_new_mode=use_new_mode)


# ── Page query (0x8E) ────────────────────────────────────────────────────

async def query_page(divoom, page: int, timeout: float = QUERY_TIMEOUT) -> list[int] | None:
    """Query device for filled slot IDs on a page via 0x8E.

    The device responds with type-1 (data) and type-2 (end-of-page)
    chunks wrapped in 0x8B. Returns list of 4-byte slot IDs.

    Args:
        divoom: connected Divoom instance
        page: page to query (0, 1, or 2)
        timeout: read-back deadline (bounded — see QUERY_TIMEOUT). A device that
            doesn't answer 0x8E returns None at the deadline rather than blocking
            the serialized command queue for the full 10s default.

    Returns:
        list of 4-byte LE slot IDs, or None on failure/timeout.
    """
    cmd = COMMANDS["app get user define info"]  # 0x8E
    response = await divoom.send_command_and_wait_for_response(cmd, [page & 0xFF], timeout=timeout)
    if response is None or len(response) < 8:
        logger.warning("0x8E query returned short response (%s)", response.hex() if response else "None")
        return None

    # Response format (LightMake64Model.x()):
    #   Byte[0]: type (1=data, 2=end)
    #   Byte[1]: page_id (type=1) or next_page (type=2)
    #   Byte[2..3]: total_count LE16
    #   Byte[4..5]: cur_seq LE16
    #   Byte[6..7]: item_count LE16
    #   Byte[8..]:  item_count × 4-byte LE32 IDs
    rtype = response[0]
    if rtype == 1:
        item_count = int.from_bytes(response[6:8], byteorder="little")
        ids = []
        pos = 8
        for _ in range(item_count):
            if pos + 4 > len(response):
                break
            fid = int.from_bytes(response[pos:pos+4], byteorder="little")
            ids.append(fid)
            pos += 4
        return ids
    elif rtype == 2:
        return []  # page is empty
    else:
        logger.warning("0x8E unexpected response type %d", rtype)
        return None
