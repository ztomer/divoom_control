"""R36b — the device HOT channel update (APK ``HotUpdateHandle`` port).

This is NOT the drawing/display path: it stores Divoom's curated "hot" files
into the device's own hot-channel rotation, exactly like the official app's
"Update" button on the hot channel page.

APK sources (references/apk/): ``bluetooth/update/HotUpdateHandle.java``,
``CmdManager.y1/x1/I/E1/w2/w1``, response routing in ``bluetooth/s.java``.

Protocol (device-driven; all multi-byte fields little-endian):

1. HTTP ``POST appin.divoom-gz.com/Hot/GetHotFiles32`` ``{DeviceType, IsTest}``
   → ``VendorList[] = {VendorId, FileList[]: {FileId, Version, Sha1}}``.
   DeviceType: 1=16px, 0=32px, 2=64px, 3=128px, 4=256px.
2. Download each ``fin.divoom-gz.com/{FileId}``, verify sha1. For devices
   < 128px the RAW cloud container is sent as-is (device firmware stores and
   decodes hot files itself — ``C1301b.d()`` returns the file unmodified).
3. ``send hot file list`` 0x9B: ``[count] + {vendorId:4, newestVersion:4}*``.
4. Device drives the rest:
   - ``request new file info`` 0xF7 ``[vendorId:4][version:4]`` → we reply
     ``hot update file info`` 0x9D ``[vendorId:4][fileSize:4][checksum:4]
     [version:4]`` (checksum = u32 byte-sum). File choice mirrors the APK:
     exact version, else the LOWEST version >= requested, else give up.
   - 0x9D response ``[0][startPacket:2]`` → stream ``hot send file data``
     0x9E ``[packetIdx:2][256-byte chunk, zero-padded last]``, ~20ms apart.
   - 0x9E response ``[0][idx:2]`` = resend that packet; ``[1]``/``[2]`` =
     file done. The device then 0xF7-requests the next file, or goes silent.
5. Quiet for ``IDLE_DONE_TIMEOUT`` = up to date. (0x9F pauses/cancels.)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import urllib.request

from divoom_lib.models import COMMANDS

logger = logging.getLogger("divoom_hot_update")

HOT_API_URL = "https://appin.divoom-gz.com/Hot/GetHotFiles32"
HOT_FILE_BASE = "https://fin.divoom-gz.com/"
USER_AGENT = "okhttp/4.12.0"

CHUNK_SIZE = 256          # APK: 256.0d packet size, zero-padded last packet
INTER_PACKET_DELAY = 0.02  # APK: Thread.sleep(20) between hot packets
IDLE_DONE_TIMEOUT = 5.0   # APK: 5s without a device request = up to date
HTTP_TIMEOUT = 15

# DeviceType by pixel size (GetHotFilesRequest semantics).
DEVICE_TYPE_BY_SIZE = {16: 1, 32: 0, 64: 2, 128: 3, 256: 4}

_CMD_LIST = COMMANDS["send hot file list"]
_CMD_INFO = COMMANDS["hot update file info"]
_CMD_DATA = COMMANDS["hot send file data"]
_CMD_PAUSE = COMMANDS["hot pause file send"]
_CMD_REQUEST = COMMANDS["request new file info"]


class HotFile:
    """One downloadable hot file (APK ``C1302c`` / UpdateFileBean)."""

    def __init__(self, vendor_id: int, file_id: str, version: int, sha1: str):
        self.vendor_id = vendor_id
        self.file_id = file_id
        self.version = version
        self.sha1 = sha1
        self.body: bytes | None = None

    @property
    def checksum(self) -> int:
        return sum(self.body) & 0xFFFFFFFF if self.body else 0

    def packet(self, idx: int) -> bytes:
        """256-byte packet ``idx`` of the body, zero-padded (APK ``r()``)."""
        start = idx * CHUNK_SIZE
        chunk = self.body[start:start + CHUNK_SIZE]
        return chunk + bytes(CHUNK_SIZE - len(chunk))

    @property
    def packet_count(self) -> int:
        return -(-len(self.body) // CHUNK_SIZE) if self.body else 0


def fetch_hot_manifest(device_type: int) -> list[HotFile]:
    """HTTP step: the vendor/file manifest for this device class."""
    req = urllib.request.Request(
        HOT_API_URL,
        data=json.dumps({"DeviceType": device_type, "IsTest": False}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
        data = json.loads(r.read())
    files = []
    for vendor in data.get("VendorList") or []:
        vid = int(vendor.get("VendorId", 0))
        for f in vendor.get("FileList") or []:
            files.append(HotFile(vid, f["FileId"], int(f["Version"]), f.get("Sha1", "")))
    return files


def download_hot_file(f: HotFile) -> bool:
    """Download + sha1-verify one hot file body (raw container, per APK for
    sub-128px devices)."""
    req = urllib.request.Request(HOT_FILE_BASE + f.file_id,
                                 headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
        body = r.read()
    if f.sha1 and hashlib.sha1(body).hexdigest().lower() != f.sha1.lower():
        logger.warning(f"hot file {f.file_id}: sha1 mismatch, skipping")
        return False
    f.body = body
    return True


# ── manifest + body cache, keyed by device_type ───────────────────────────
# The manifest and every file body depend ONLY on device_type (pixel class), so
# syncing N same-size devices used to re-hit the CDN N times (fetch manifest +
# download every body per device). Cache the fully-downloaded HotFile set per
# device_type for a short TTL and reuse it. Bodies are read-only during
# streaming, so sharing them across devices is safe. A daemon-wide guard
# (_try_begin_hot_update) serializes hot updates, so no lock is needed.
_MANIFEST_CACHE_TTL = 300.0  # seconds
_manifest_cache: dict[int, tuple[float, list[HotFile]]] = {}


def clear_hot_manifest_cache() -> None:
    """Drop all cached manifests (force-refresh / test hook)."""
    _manifest_cache.clear()


async def _load_hot_files(device_type: int, progress_cb=None) -> tuple[list[HotFile], int, bool]:
    """Return ``(files, downloaded_count, from_cache)`` for ``device_type``,
    reusing a recent cached download for the same device class so N same-size
    devices don't each re-fetch from the CDN."""
    now = time.monotonic()
    cached = _manifest_cache.get(device_type)
    if cached and (now - cached[0]) < _MANIFEST_CACHE_TTL:
        files = cached[1]
        dl = sum(1 for f in files if f.body is not None)
        if dl:
            return files, dl, True

    files = await asyncio.to_thread(fetch_hot_manifest, device_type)
    if not files:
        return [], 0, False
    if progress_cb:
        progress_cb({"phase": "downloading", "current": 0, "total": len(files)})
    ok_dl = 0
    for i, f in enumerate(files):
        try:
            ok_dl += 1 if await asyncio.to_thread(download_hot_file, f) else 0
        except Exception as e:
            logger.warning(f"hot file {f.file_id}: download failed: {e}")
        if progress_cb:
            progress_cb({"phase": "downloading", "current": i + 1,
                         "total": len(files), "file_id": f.file_id})
    if ok_dl:
        _manifest_cache[device_type] = (now, files)
    return files, ok_dl, False


class HotUpdate:
    """Drives one hot-channel update session against a connected device."""

    def __init__(self, divoom):
        self.divoom = divoom
        self.logger = getattr(divoom, "logger", logger)

    # ── wire helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _manifest_payload(files: list[HotFile]) -> list[int]:
        """0x9B body (APK ``y1``): [count] + {vendorId:4, newestVersion:4}."""
        vendors: dict[int, int] = {}
        for f in files:
            if f.body is not None:
                vendors[f.vendor_id] = max(vendors.get(f.vendor_id, 0), f.version)
        out = [len(vendors) & 0xFF]
        for vid, newest in vendors.items():
            out += list(vid.to_bytes(4, "little")) + list(newest.to_bytes(4, "little"))
        return out

    @staticmethod
    def _file_info_payload(f: HotFile) -> list[int]:
        """0x9D body (APK ``x1``): vendorId:4 + fileSize:4 + checksum:4 + version:4."""
        return (list(f.vendor_id.to_bytes(4, "little"))
                + list(len(f.body).to_bytes(4, "little"))
                + list(f.checksum.to_bytes(4, "little"))
                + list(f.version.to_bytes(4, "little")))

    @staticmethod
    def _pick_file(files: list[HotFile], vendor_id: int, version: int) -> HotFile | None:
        """APK ``v()``/``n()``/``m()``: exact version, else LOWEST >= requested."""
        candidates = [f for f in files if f.vendor_id == vendor_id and f.body]
        for f in candidates:
            if f.version == version:
                return f
        higher = [f for f in candidates if f.version >= version]
        return min(higher, key=lambda f: f.version) if higher else None

    # ── session ───────────────────────────────────────────────────────────

    async def _stream_file(self, f: HotFile, start_packet: int, wait_any) -> tuple[bool, bool]:
        """Stream one file's packets, then serve resends until the device ends it.

        Returns ``(ok, confirmed)``:
          * ``(False, False)`` — a packet write failed (transport error).
          * ``(True, True)``   — the device explicitly confirmed the file done, OR
            moved on to request the next file (it accepted this one).
          * ``(True, False)``  — every packet was written but the device went SILENT
            (no done-ack within IDLE_DONE_TIMEOUT). The bytes were ACKed at the link
            layer, but the device never confirmed it stored/applied the file — an
            honest "unconfirmed", NOT a clean success (ACK ≠ device-confirmed).
        """
        total = f.packet_count
        self.logger.info(f"hot: streaming {f.file_id} v{f.version} "
                         f"({len(f.body)}B, packets {start_packet}..{total - 1})")
        for idx in range(start_packet, total):
            payload = list(idx.to_bytes(2, "little")) + list(f.packet(idx))
            if not await self.divoom.send_command(_CMD_DATA, payload):
                self.logger.error(f"hot: packet {idx} write failed")
                return False, False
            await asyncio.sleep(INTER_PACKET_DELAY)
        # Post-stream: serve resends until the device declares the file done.
        while True:
            got = await wait_any([_CMD_DATA, _CMD_REQUEST], timeout=IDLE_DONE_TIMEOUT)
            if got is None:
                self.logger.warning(f"hot: no done-ack for {f.file_id}; continuing (UNCONFIRMED)")
                return True, False
            cmd, payload = got
            if cmd == _CMD_REQUEST:
                # Device moved on already — it accepted this file; let caller handle it.
                self._pending_request = payload
                return True, True
            if len(payload) >= 1 and payload[0] in (1, 2):
                self.logger.info(f"hot: device confirmed {f.file_id} done")
                return True, True
            if len(payload) >= 3 and payload[0] == 0:
                idx = int.from_bytes(bytes(payload[1:3]), "little")
                self.logger.info(f"hot: resend packet {idx}")
                await self.divoom.send_command(
                    _CMD_DATA, list(idx.to_bytes(2, "little")) + list(f.packet(idx)))

    async def update(self, *, device_size: int = 16,
                     progress_cb=None) -> dict:
        """Run a full hot-channel update. Returns a summary dict.
        If ``progress_cb`` is provided it is called with a phase dict at each
        stage: ``{"phase": "fetching_manifest"|"downloading"|"uploading"|"done",
        "current": int, "total": int, "file_id": str, ...}``."""
        comm = getattr(self.divoom, "_conn", None) or self.divoom
        wait_any = getattr(comm, "wait_for_any_response", None)
        if wait_any is None:
            return {"success": False, "error": "transport lacks wait_for_any_response"}

        if progress_cb:
            progress_cb({"phase": "fetching_manifest"})

        device_type = DEVICE_TYPE_BY_SIZE.get(int(device_size), 1)
        # Fetch manifest + download bodies once per device_type; reuse across
        # same-size devices (see _load_hot_files) instead of re-hitting the CDN.
        files, ok_dl, from_cache = await _load_hot_files(device_type, progress_cb)
        if not files:
            return {"success": False, "error": "empty hot manifest"}
        if ok_dl == 0:
            return {"success": False, "error": "no hot files downloadable"}
        if from_cache and progress_cb:
            # Jump the download bar — nothing was re-fetched.
            progress_cb({"phase": "downloading", "current": len(files),
                         "total": len(files)})
        self.logger.info(f"hot: manifest {len(files)} files, {ok_dl} downloaded"
                         f"{' (cached)' if from_cache else ''}")

        listen = getattr(comm, "_listen_commands", None)
        if isinstance(listen, set):
            listen.update({_CMD_REQUEST, _CMD_INFO, _CMD_DATA, _CMD_PAUSE})
        served, self._pending_request = [], None

        if progress_cb:
            progress_cb({"phase": "uploading", "current": 0, "total": ok_dl})

        try:
            if not await self.divoom.send_command(_CMD_LIST, self._manifest_payload(files)):
                return {"success": False, "error": "manifest (0x9B) write failed"}

            while True:
                if self._pending_request is not None:
                    payload, self._pending_request = self._pending_request, None
                    cmd = _CMD_REQUEST
                else:
                    got = await wait_any([_CMD_REQUEST, _CMD_PAUSE],
                                         timeout=IDLE_DONE_TIMEOUT)
                    if got is None:
                        break  # quiet — device is up to date
                    cmd, payload = got
                if cmd == _CMD_PAUSE:
                    self.logger.info("hot: device paused the update")
                    break
                if len(payload) < 8:
                    continue
                vendor_id = int.from_bytes(bytes(payload[0:4]), "little")
                version = int.from_bytes(bytes(payload[4:8]), "little")
                self.logger.info(f"hot: device requests vendor {vendor_id} v{version}")
                f = self._pick_file(files, vendor_id, version)
                if f is None:
                    self.logger.info("hot: no matching file; ending session")
                    break
                if not await self.divoom.send_command(_CMD_INFO, self._file_info_payload(f)):
                    return {"success": False, "error": "file info (0x9D) write failed",
                            "served": served}
                got = await wait_any([_CMD_INFO, _CMD_REQUEST], timeout=IDLE_DONE_TIMEOUT)
                if got is None:
                    self.logger.warning("hot: no 0x9D ack; ending session")
                    break
                cmd2, p2 = got
                if cmd2 == _CMD_REQUEST:
                    self._pending_request = p2
                    continue
                if not p2 or p2[0] != 0:
                    self.logger.info(f"hot: device declined file (resp {bytes(p2).hex()})")
                    continue
                start = int.from_bytes(bytes(p2[1:3]), "little") if len(p2) >= 3 else 0
                ok, confirmed = await self._stream_file(f, start, wait_any)
                if ok:
                    served.append({"file_id": f.file_id, "version": f.version,
                                   "confirmed": confirmed})
                    if progress_cb:
                        progress_cb({"phase": "uploading", "current": len(served),
                                     "total": ok_dl, "file_id": f.file_id})
        finally:
            if isinstance(listen, set):
                listen.difference_update({_CMD_REQUEST, _CMD_INFO, _CMD_DATA, _CMD_PAUSE})

        # ACK ≠ device-confirmed: `confirmed` counts files the device positively
        # acknowledged (done-ack or moved-on); served files that streamed but went
        # silent are in `served` with confirmed=False. A caller that needs honesty
        # compares confirmed against len(served).
        result = {"success": True, "served": served,
                  "manifest": len(files), "downloaded": ok_dl,
                  "confirmed": sum(1 for s in served if s.get("confirmed"))}
        if progress_cb:
            progress_cb({"phase": "done", **result})
        self.logger.info(f"hot: session complete — {len(served)} file(s) served")
        return result

    async def show_hot_channel(self, page: int | None = None) -> bool:
        """Switch the device to the HOT channel (APK ``w2``: 0x45 [HOT_MODE=2]);
        optionally select a hot page (``w1``: 0x85 [1, page])."""
        ok = await self.divoom.send_command(COMMANDS["set light mode"], [0x02])
        if ok and page is not None:
            await self.divoom.send_command(COMMANDS["send hotctrl"], [1, int(page) & 0xFF])
        return bool(ok)
