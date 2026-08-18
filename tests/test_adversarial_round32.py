"""R53 round 32 — multi-persona CONVERGENCE-pass fixes (not clean: 6 new bugs).

- exclusive_start/exclusive_end must use the long sync read timeout, not the 2s
  default (the daemon enqueues acquire behind an in-flight push → client timed out
  while the daemon acquired → orphaned token + wedged device).
- get_memorial_time must tolerate a truncated-multibyte title (errors='replace'),
  not crash and lose all 10 memorials.
- media_source must import urllib.parse explicitly (was bound only via a
  urllib.request side-effect).
- ConnectionApi.scan_devices must call self._client() (method form) — it used the
  property form → got a bound method → AttributeError → always-empty scan.
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / "divoom_gui"))


# ── Hashimoto: exclusive RPC timeout ────────────────────────────────────────

def test_exclusive_rpcs_use_long_read_timeout():
    from divoom_client.daemon_protocol import DaemonClient
    from divoom_client.daemon_config import load_daemon_config

    expected = load_daemon_config().sync_read_timeout
    assert expected >= 100  # sanity: it's the long (sync_artwork) timeout, not 2s

    c = object.__new__(DaemonClient)
    seen = {}

    def _fake_send(command, args=None, *, read_timeout=None, **kw):
        seen[command] = read_timeout
        return {"success": True}

    c.send_command = _fake_send
    c.exclusive_start("tok")
    c.exclusive_end("tok")
    assert seen["exclusive_start"] == expected
    assert seen["exclusive_end"] == expected


# ── Linus: memorial decode tolerance ────────────────────────────────────────

def test_get_memorial_time_tolerates_truncated_utf8():
    from divoom_lib.scheduling.alarm import Alarm
    from divoom_lib import models as _c  # GMT_* / MEMORIAL_COUNT live in models

    gmt_len = _c.GMT_MEMORIAL_INFO_LENGTH
    count = _c.MEMORIAL_COUNT
    ts = _c.GMT_TITLE_NAME_START

    rec = bytearray(gmt_len)
    rec[ts:ts + 3] = b"\xf0\x9f\x8e"  # first 3 bytes of a 4-byte emoji → dangling
    response = bytes(rec) * count

    class _Dev:
        async def send_command_and_wait_for_response(self, _cmd):
            return response

    a = object.__new__(Alarm)
    a._divoom = _Dev()
    a.logger = logging.getLogger("t")

    res = asyncio.run(a.get_memorial_time())
    assert res is not None and len(res) == count, "must parse all records, not crash"


# ── Carmack: urllib.parse import ────────────────────────────────────────────

def test_media_source_imports_urllib_parse():
    import divoom_lib.utils.media_source as ms
    # quote() is reachable without relying on urllib.request's import side-effect
    assert ms.urllib.parse.quote("a b") == "a%20b"


# ── Uncle Bob: ConnectionApi.scan_devices calls the client ──────────────────

def test_connection_scan_devices_calls_client():
    from divoom_gui.api.connection import ConnectionApi

    class _Client:
        def scan(self, timeout, limit):
            return {"devices": [{"mac": "AA:BB"}]}

    state = {"_daemon_client": _Client()}
    api = object.__new__(ConnectionApi)
    api._state_getter = lambda: state

    res = json.loads(api.scan_devices())
    assert res == [{"mac": "AA:BB"}], "scan_devices must reach client.scan, not a bound method"
