"""R36b — device HOT channel update (APK HotUpdateHandle port).

Byte layouts mirror the decompiled APK (CmdManager.y1/x1/I); the session test
replays the EXACT exchange observed on a real Ditoo (2026-06-09): device
requests v1099 → info ack [0][start:2] → 201 packets → done [1] → device
requests v1100 → no newer file → clean end.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.append(str(Path(__file__).parent.parent))

from divoom_lib.models import COMMANDS
from divoom_lib.tools.hot_update import HotFile, HotUpdate, clear_hot_manifest_cache


@pytest.fixture(autouse=True)
def _clear_hot_cache():
    """The device_type-keyed manifest cache is module-level; clear it around each
    test so a cached download from one test never masks another's monkeypatched
    fetch_hot_manifest / download_hot_file."""
    clear_hot_manifest_cache()
    yield
    clear_hot_manifest_cache()


CMD_LIST = COMMANDS["send hot file list"]
CMD_INFO = COMMANDS["hot update file info"]
CMD_DATA = COMMANDS["hot send file data"]
CMD_REQUEST = COMMANDS["request new file info"]


def _file(vendor=40005454, version=1099, body=b"\x07" * 522):
    f = HotFile(vendor, f"group1/v{version}.bin", version, "")
    f.body = body
    return f


def test_manifest_payload_apk_layout():
    m = HotUpdate._manifest_payload([_file(version=1098), _file(version=1099)])
    assert m[0] == 1  # one vendor
    assert int.from_bytes(bytes(m[1:5]), "little") == 40005454
    assert int.from_bytes(bytes(m[5:9]), "little") == 1099  # newest wins


def test_file_info_payload_apk_layout():
    f = _file()
    info = HotUpdate._file_info_payload(f)
    assert len(info) == 16
    assert int.from_bytes(bytes(info[0:4]), "little") == f.vendor_id
    assert int.from_bytes(bytes(info[4:8]), "little") == 522
    assert int.from_bytes(bytes(info[8:12]), "little") == sum(f.body)  # byte-sum u32
    assert int.from_bytes(bytes(info[12:16]), "little") == 1099


def test_packets_zero_padded_256():
    f = _file(body=bytes(range(256)) * 2 + b"\x09" * 10)
    assert f.packet_count == 3
    assert f.packet(0) == bytes(range(256))
    assert f.packet(2)[:10] == b"\x09" * 10 and f.packet(2)[10:] == bytes(246)


def test_pick_file_apk_fallback_rules():
    old, new = _file(version=1098), _file(version=1099)
    files = [old, new]
    assert HotUpdate._pick_file(files, 40005454, 1099) is new   # exact
    assert HotUpdate._pick_file(files, 40005454, 1000) is old   # lowest >= req
    assert HotUpdate._pick_file(files, 40005454, 1100) is None  # nothing newer
    assert HotUpdate._pick_file(files, 1, 1099) is None         # wrong vendor


@pytest.mark.asyncio
async def test_session_replays_real_ditoo_exchange(monkeypatch):
    """Full session against a fake transport, mirroring the live Ditoo run."""
    f = _file(body=b"\xAB" * 600)  # 3 packets

    divoom = MagicMock()
    divoom.logger = MagicMock()
    divoom.send_command = AsyncMock(return_value=True)
    conn = MagicMock()
    conn._listen_commands = set()
    req_1099 = bytes((40005454).to_bytes(4, "little")) + bytes((1099).to_bytes(4, "little"))
    req_1100 = bytes((40005454).to_bytes(4, "little")) + bytes((1100).to_bytes(4, "little"))
    conn.wait_for_any_response = AsyncMock(side_effect=[
        (CMD_REQUEST, req_1099),       # device asks for v1099
        (CMD_INFO, bytes([0, 0, 0])),  # accept, start at packet 0
        (CMD_DATA, bytes([1])),        # file done
        (CMD_REQUEST, req_1100),       # device asks for v1100 (nothing newer)
    ])
    divoom._conn = conn

    hu = HotUpdate(divoom)
    monkeypatch.setattr("divoom_lib.tools.hot_update.fetch_hot_manifest", lambda dt: [f])
    monkeypatch.setattr("divoom_lib.tools.hot_update.download_hot_file", lambda x: True)
    monkeypatch.setattr("divoom_lib.tools.hot_update.INTER_PACKET_DELAY", 0)

    result = await hu.update(device_size=16)
    assert result["success"] is True
    # device sent an explicit done-ack (CMD_DATA [1]) → confirmed.
    assert result["served"] == [{"file_id": f.file_id, "version": 1099, "confirmed": True}]
    assert result["confirmed"] == 1

    sent = [c.args for c in divoom.send_command.await_args_list]
    cmds = [a[0] for a in sent]
    assert cmds[0] == CMD_LIST                      # manifest first
    assert cmds.count(CMD_INFO) == 1                # one file info
    data = [a[1] for a in sent if a[0] == CMD_DATA]
    assert len(data) == 3                           # 3 packets, no resends
    assert [int.from_bytes(bytes(d[:2]), "little") for d in data] == [0, 1, 2]
    assert all(len(d) == 2 + 256 for d in data)     # idx:2 + zero-padded 256
    assert conn._listen_commands == set()           # listen set restored


@pytest.mark.asyncio
async def test_session_serves_resend_requests(monkeypatch):
    f = _file(body=b"\x01" * 300)  # 2 packets

    divoom = MagicMock()
    divoom.logger = MagicMock()
    divoom.send_command = AsyncMock(return_value=True)
    conn = MagicMock()
    conn._listen_commands = set()
    req = bytes((40005454).to_bytes(4, "little")) + bytes((1099).to_bytes(4, "little"))
    conn.wait_for_any_response = AsyncMock(side_effect=[
        (CMD_REQUEST, req),
        (CMD_INFO, bytes([0, 0, 0])),
        (CMD_DATA, bytes([0, 1, 0])),  # resend packet 1
        (CMD_DATA, bytes([2])),        # done
        None,                          # session quiet
    ])
    divoom._conn = conn

    hu = HotUpdate(divoom)
    monkeypatch.setattr("divoom_lib.tools.hot_update.fetch_hot_manifest", lambda dt: [f])
    monkeypatch.setattr("divoom_lib.tools.hot_update.download_hot_file", lambda x: True)
    monkeypatch.setattr("divoom_lib.tools.hot_update.INTER_PACKET_DELAY", 0)

    result = await hu.update(device_size=16)
    assert result["success"] is True
    data_idx = [int.from_bytes(bytes(c.args[1][:2]), "little")
                for c in divoom.send_command.await_args_list if c.args[0] == CMD_DATA]
    assert data_idx == [0, 1, 1]  # packet 1 re-sent on request


@pytest.mark.asyncio
async def test_silent_device_file_marked_unconfirmed(monkeypatch):
    """ACK ≠ device-confirmed: a file whose packets all wrote but got NO done-ack
    (device went silent) must be served with confirmed=False, and not counted in
    the confirmed total. Teeth: the old _stream_file returned a bare True for the
    no-done-ack case, so served carried no confirmed flag and the silent file was
    indistinguishable from a device-confirmed one."""
    f = _file(body=b"\x01" * 300)  # 2 packets

    divoom = MagicMock()
    divoom.logger = MagicMock()
    divoom.send_command = AsyncMock(return_value=True)
    conn = MagicMock()
    conn._listen_commands = set()
    req = bytes((40005454).to_bytes(4, "little")) + bytes((1099).to_bytes(4, "little"))
    conn.wait_for_any_response = AsyncMock(side_effect=[
        (CMD_REQUEST, req),            # device asks for v1099
        (CMD_INFO, bytes([0, 0, 0])),  # accept, start at packet 0
        None,                          # _stream_file done-wait: device SILENT
        None,                          # outer loop: quiet -> end session
    ])
    divoom._conn = conn

    hu = HotUpdate(divoom)
    monkeypatch.setattr("divoom_lib.tools.hot_update.fetch_hot_manifest", lambda dt: [f])
    monkeypatch.setattr("divoom_lib.tools.hot_update.download_hot_file", lambda x: True)
    monkeypatch.setattr("divoom_lib.tools.hot_update.INTER_PACKET_DELAY", 0)

    result = await hu.update(device_size=16)
    assert result["success"] is True
    assert result["served"] == [{"file_id": f.file_id, "version": 1099, "confirmed": False}]
    assert result["confirmed"] == 0  # streamed but NOT device-confirmed


# ── device_type-keyed download cache (no redundant per-device fetch) ───────

@pytest.mark.asyncio
async def test_load_hot_files_caches_per_device_type(monkeypatch):
    """Two syncs of the same device class reuse one CDN fetch+download instead of
    re-downloading per device; a different class fetches separately."""
    from divoom_lib.tools import hot_update as hu_mod

    fetch_calls, dl_calls = [], []

    def fake_fetch(dt):
        fetch_calls.append(dt)
        f = _file(version=1099 + dt)
        f.body = None          # force the download path to populate it
        return [f]

    def fake_dl(f):
        dl_calls.append(f.file_id)
        f.body = b"\x02" * 300
        return True

    monkeypatch.setattr(hu_mod, "fetch_hot_manifest", fake_fetch)
    monkeypatch.setattr(hu_mod, "download_hot_file", fake_dl)

    files1, dl1, cached1 = await hu_mod._load_hot_files(1)
    assert dl1 == 1 and cached1 is False
    assert fetch_calls == [1] and len(dl_calls) == 1

    # Same device_type → served from cache: no new fetch, no new download.
    files2, dl2, cached2 = await hu_mod._load_hot_files(1)
    assert cached2 is True and dl2 == 1
    assert files2 is files1
    assert fetch_calls == [1] and len(dl_calls) == 1  # unchanged

    # Different device_type → its own fetch+download.
    _f3, _dl3, cached3 = await hu_mod._load_hot_files(0)
    assert cached3 is False
    assert fetch_calls == [1, 0] and len(dl_calls) == 2


@pytest.mark.asyncio
async def test_clear_hot_manifest_cache_forces_refetch(monkeypatch):
    from divoom_lib.tools import hot_update as hu_mod

    fetch_calls = []

    def fake_fetch(dt):
        fetch_calls.append(dt)
        f = _file()
        f.body = None
        return [f]

    monkeypatch.setattr(hu_mod, "fetch_hot_manifest", fake_fetch)
    monkeypatch.setattr(hu_mod, "download_hot_file",
                        lambda f: (setattr(f, "body", b"\x03" * 300), True)[1])

    await hu_mod._load_hot_files(1)
    hu_mod.clear_hot_manifest_cache()
    await hu_mod._load_hot_files(1)
    assert fetch_calls == [1, 1]  # cleared → re-fetched, not served from cache
