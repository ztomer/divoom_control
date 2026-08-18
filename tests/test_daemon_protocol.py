"""R16 Phase 1 — daemon wire protocol (NDJSON framing, shapes, client)."""
import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / "divoom_gui"))

from divoom_client.daemon_protocol import (
    EVENT_STATUS, EVENT_NOTIFICATION, SUBSCRIBE_COMMAND,
    encode_message, iter_messages, make_request,
    make_status_event, make_notification_event, DaemonClient,
)


# ── framing ─────────────────────────────────────────────────────────────
def test_encode_is_one_ndjson_line():
    raw = encode_message({"a": 1, "b": "x"})
    assert raw.endswith(b"\n")
    assert raw.count(b"\n") == 1
    assert json.loads(raw.decode().strip()) == {"a": 1, "b": "x"}


def test_iter_messages_splits_and_keeps_remainder():
    buf = encode_message({"n": 1}) + encode_message({"n": 2}) + b'{"n":3'  # partial
    msgs, remainder = iter_messages(buf)
    assert [m["n"] for m in msgs] == [1, 2]
    assert remainder == b'{"n":3'


def test_iter_messages_skips_blank_and_malformed():
    buf = b"\n" + b"not json\n" + encode_message({"ok": True})
    msgs, remainder = iter_messages(buf)
    assert msgs == [{"ok": True}]
    assert remainder == b""


def test_message_constructors():
    assert make_request("ping") == {"command": "ping", "args": {}}
    assert make_request("x", {"a": 1}) == {"command": "x", "args": {"a": 1}}
    assert make_status_event("active", {"seen": 2}) == {
        "type": EVENT_STATUS, "state": "active", "counters": {"seen": 2}}
    ev = make_notification_event(6, "T", "B", True)
    assert ev == {"type": EVENT_NOTIFICATION, "app_type": 6,
                  "title": "T", "body": "B", "routed": True}


# ── client against a tiny fake daemon ───────────────────────────────────
def _sock_path() -> str:
    import os
    return f"/tmp/divoom_proto_{os.getpid()}.sock"


def _serve_one(sock_path, handler, ready):
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    srv.listen(1)
    srv.settimeout(5.0)
    ready.set()
    try:
        conn, _ = srv.accept()
        handler(conn)
    finally:
        srv.close()


def test_send_command_round_trip():
    sp = _sock_path()
    import os
    if os.path.exists(sp):
        os.remove(sp)

    def handler(conn):
        data = conn.recv(4096)
        msgs, _ = iter_messages(data)
        assert msgs[0] == {"command": "get_status", "args": {}}
        conn.sendall(encode_message({"success": True, "state": "idle"}))
        conn.close()

    ready = threading.Event()
    t = threading.Thread(target=_serve_one, args=(sp, handler, ready), daemon=True)
    t.start()
    ready.wait(2.0)
    try:
        reply = DaemonClient(sp).send_command("get_status")
    finally:
        t.join(timeout=5.0)
        if os.path.exists(sp):
            os.remove(sp)
    assert reply == {"success": True, "state": "idle"}


def test_send_command_no_daemon_returns_error():
    reply = DaemonClient("/tmp/divoom_absent_xyz.sock").send_command("ping")
    assert reply["success"] is False
    assert "error" in reply


def test_subscribe_streams_events():
    sp = _sock_path()
    import os
    if os.path.exists(sp):
        os.remove(sp)

    def handler(conn):
        data = conn.recv(4096)
        msgs, _ = iter_messages(data)
        assert msgs[0]["command"] == SUBSCRIBE_COMMAND
        conn.sendall(encode_message(make_status_event("active", {"seen": 1})))
        conn.sendall(encode_message(make_notification_event(6, "hi", "there", True)))
        time.sleep(0.1)
        conn.close()

    ready = threading.Event()
    t = threading.Thread(target=_serve_one, args=(sp, handler, ready), daemon=True)
    t.start()
    ready.wait(2.0)
    received = []
    try:
        DaemonClient(sp).subscribe(received.append)  # returns when daemon closes
    finally:
        t.join(timeout=5.0)
        if os.path.exists(sp):
            os.remove(sp)
    assert [e["type"] for e in received] == [EVENT_STATUS, EVENT_NOTIFICATION]
    assert received[0]["state"] == "active"
    assert received[1]["routed"] is True


def test_subscribe_no_daemon_returns_false():
    assert DaemonClient("/tmp/divoom_absent_xyz.sock").subscribe(lambda e: None) is False
