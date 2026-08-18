"""spp_bridge.py — subprocess bridge for Divoom BT-Classic SPP.

Coverage strategy (R61 coverage push, item 1): spp_bridge.py is a subprocess
entrypoint that pipes hex-JSON messages between divoomd (Rust) and
BTSppTransport over real stdin/stdout, using asyncio.StreamReader bound to a
real OS pipe (loop.connect_read_pipe(..., sys.stdin)). The message
parse/dispatch/encode logic in read_stdin_loop/read_notifications_loop/main
is pure and fully testable via dependency injection: we monkeypatch
asyncio.StreamReader (to a fake reader we script) and asyncio.get_event_loop
(to a dummy loop whose connect_read_pipe is a no-op), and monkeypatch
BTSppTransport at the spp_bridge call site so no real Bluetooth/IOBluetooth
call is ever made (see divoom-ble-tcc-harness-limit: real BT from this shell
crashes on TCC).

The one line genuinely NOT unit-testable: `if __name__ == "__main__":
asyncio.run(main())` (only executes when the file is run as a real script,
which for this module means spinning up a real BTSppTransport against real
hardware — the same TCC-crash class documented in
divoom-ble-tcc-harness-limit). That block carries a narrow, individually
justified `# pragma: no cover`, matching the gui_main.py/audio_visualizer.py
precedent (see `git show 11d5beb -- divoom_gui/gui_main.py`) rather than a
blanket file exclusion.
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))

from divoom_client import spp_bridge


# ── Fakes ───────────────────────────────────────────────────────────────────

class FakeStdinReader:
    """Stands in for asyncio.StreamReader: readline() replays a scripted list
    of byte-lines, then signals EOF with b"" (matching real StreamReader)."""
    _source_traceback = None

    def __init__(self, lines):
        self._lines = list(lines)

    async def readline(self):
        if not self._lines:
            return b""
        return self._lines.pop(0)


class DummyLoop:
    """Stands in for the real event loop: connect_read_pipe would normally
    bind a real OS pipe to the protocol; here we just no-op so the already
    (monkeypatched) FakeStdinReader is used instead."""
    async def connect_read_pipe(self, protocol_factory, pipe):
        protocol_factory()
        return None, None


class FakeTransport:
    def __init__(self, mtu=512):
        self.sent = []
        self.mtu = mtu
        self.notification_queue = asyncio.Queue()
        self.connect_called = False
        self.disconnect_called = False
        self.connect_error = None

    async def send(self, payload, framing="basic", packet_number=0):
        self.sent.append({"payload": payload, "framing": framing, "packet_number": packet_number})

    async def connect(self):
        self.connect_called = True
        if self.connect_error:
            raise self.connect_error

    async def disconnect(self):
        self.disconnect_called = True


def _line(obj):
    return (json.dumps(obj) + "\n").encode()


@pytest.fixture
def patch_stdin(monkeypatch):
    """Wire spp_bridge.read_stdin_loop's asyncio.StreamReader()/get_event_loop()
    calls to our fakes, scripted with `lines` (list of dicts or raw bytes)."""
    def _apply(lines):
        encoded = [l if isinstance(l, (bytes, bytearray)) else _line(l) for l in lines]
        monkeypatch.setattr(spp_bridge.asyncio, "StreamReader", lambda: FakeStdinReader(encoded))
        monkeypatch.setattr(spp_bridge.asyncio, "get_event_loop", lambda: DummyLoop())
    return _apply


# ── read_stdin_loop ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_write_command_dispatches_to_transport_send(patch_stdin):
    transport = FakeTransport()
    patch_stdin([{"command": "write", "payload": [1, 2, 3], "framing": "extended", "packet_number": 7}])

    await spp_bridge.read_stdin_loop(transport)

    assert transport.sent == [{"payload": [1, 2, 3], "framing": "extended", "packet_number": 7}]


@pytest.mark.asyncio
async def test_write_command_uses_defaults_when_fields_missing(patch_stdin):
    transport = FakeTransport()
    patch_stdin([{"command": "write"}])

    await spp_bridge.read_stdin_loop(transport)

    assert transport.sent == [{"payload": [], "framing": "basic", "packet_number": 0}]


@pytest.mark.asyncio
async def test_disconnect_command_breaks_loop_without_sending(patch_stdin):
    transport = FakeTransport()
    # A write AFTER disconnect must never be reached.
    patch_stdin([
        {"command": "disconnect"},
        {"command": "write", "payload": [9]},
    ])

    await spp_bridge.read_stdin_loop(transport)

    assert transport.sent == []


@pytest.mark.asyncio
async def test_unknown_command_is_ignored_and_loop_continues(patch_stdin):
    transport = FakeTransport()
    patch_stdin([
        {"command": "ping"},
        {"command": "write", "payload": [5]},
    ])

    await spp_bridge.read_stdin_loop(transport)

    assert transport.sent == [{"payload": [5], "framing": "basic", "packet_number": 0}]


@pytest.mark.asyncio
async def test_malformed_json_line_reports_error_and_continues(patch_stdin, capsys):
    transport = FakeTransport()
    patch_stdin([
        b"not json at all\n",
        {"command": "write", "payload": [1]},
    ])

    await spp_bridge.read_stdin_loop(transport)

    out = capsys.readouterr().out
    lines = [json.loads(l) for l in out.strip().splitlines() if l.strip()]
    errors = [l for l in lines if l.get("type") == "error"]
    assert len(errors) == 1
    assert "error" in errors[0]
    # Loop kept going after the bad line and still handled the next command.
    assert transport.sent == [{"payload": [1], "framing": "basic", "packet_number": 0}]


@pytest.mark.asyncio
async def test_transport_send_exception_is_caught_and_reported(patch_stdin, capsys):
    transport = FakeTransport()

    async def _boom(payload, framing="basic", packet_number=0):
        raise RuntimeError("send failed")

    transport.send = _boom
    patch_stdin([{"command": "write", "payload": [1]}])

    await spp_bridge.read_stdin_loop(transport)

    out = capsys.readouterr().out
    lines = [json.loads(l) for l in out.strip().splitlines() if l.strip()]
    assert any(l.get("type") == "error" and "send failed" in l.get("error", "") for l in lines)


@pytest.mark.asyncio
async def test_empty_line_eof_ends_loop_immediately(patch_stdin):
    transport = FakeTransport()
    patch_stdin([])  # first readline() returns b"" right away

    # Must return promptly, not hang.
    await asyncio.wait_for(spp_bridge.read_stdin_loop(transport), timeout=2)

    assert transport.sent == []


# ── read_notifications_loop ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_notification_loop_prints_and_marks_done(capsys):
    transport = FakeTransport()
    await transport.notification_queue.put({"command_id": 42, "payload": bytes([1, 2, 3])})
    # Force the loop to stop after the first item by making the *second*
    # queue.get() raise (simulates a closed/broken queue rather than hanging).
    real_get = transport.notification_queue.get
    calls = {"n": 0}

    async def _get():
        calls["n"] += 1
        if calls["n"] == 1:
            return await real_get()
        raise RuntimeError("queue closed")

    transport.notification_queue.get = _get

    await spp_bridge.read_notifications_loop(transport)

    out = capsys.readouterr().out
    lines = [json.loads(l) for l in out.strip().splitlines() if l.strip()]
    assert lines == [{"type": "notification", "command_id": 42, "payload": [1, 2, 3]}]


@pytest.mark.asyncio
async def test_notification_loop_exits_on_first_exception(capsys):
    transport = FakeTransport()

    async def _boom():
        raise KeyError("command_id")

    transport.notification_queue.get = _boom

    # Must return (not hang) after logging the error.
    await asyncio.wait_for(spp_bridge.read_notifications_loop(transport), timeout=2)

    out = capsys.readouterr().out
    assert out.strip() == ""  # nothing was printed before the exception


# ── main() ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_main_connects_prints_connected_and_runs_loops(monkeypatch, capsys):
    transport = FakeTransport(mtu=999)
    made_with = {}

    def _factory(mac_address, channel_id, device_kind, device_name):
        made_with.update(mac=mac_address, channel=channel_id, kind=device_kind, name=device_name)
        return transport

    monkeypatch.setattr(spp_bridge, "BTSppTransport", _factory)
    monkeypatch.setattr(sys, "argv", ["spp_bridge.py", "--mac", "AA:BB:CC:DD:EE:FF", "--channel", "3"])

    stdin_calls = []
    notif_calls = []

    async def _fake_stdin_loop(t):
        stdin_calls.append(t)

    async def _fake_notif_loop(t):
        notif_calls.append(t)

    monkeypatch.setattr(spp_bridge, "read_stdin_loop", _fake_stdin_loop)
    monkeypatch.setattr(spp_bridge, "read_notifications_loop", _fake_notif_loop)

    await spp_bridge.main()

    assert made_with == {"mac": "AA-BB-CC-DD-EE-FF", "channel": 3, "kind": "default", "name": None}
    assert transport.connect_called
    assert transport.disconnect_called
    assert stdin_calls == [transport]
    assert notif_calls == [transport]

    out = capsys.readouterr().out
    lines = [json.loads(l) for l in out.strip().splitlines() if l.strip()]
    assert lines[0] == {"type": "connected", "mtu": 999}
    assert lines[-1] == {"type": "disconnected"}


@pytest.mark.asyncio
async def test_main_connect_failure_prints_disconnected_and_exits(monkeypatch, capsys):
    transport = FakeTransport()
    transport.connect_error = RuntimeError("no such device")

    monkeypatch.setattr(spp_bridge, "BTSppTransport", lambda **kw: transport)
    monkeypatch.setattr(sys, "argv", ["spp_bridge.py", "--mac", "11:22:33:44:55:66"])

    with pytest.raises(SystemExit) as exc_info:
        await spp_bridge.main()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    lines = [json.loads(l) for l in out.strip().splitlines() if l.strip()]
    assert lines == [{"type": "disconnected", "error": "no such device"}]
    # disconnect() must not be called — connect() never succeeded.
    assert not transport.disconnect_called


@pytest.mark.asyncio
async def test_main_uses_default_channel_kind_and_name(monkeypatch):
    transport = FakeTransport()
    made_with = {}

    def _factory(mac_address, channel_id, device_kind, device_name):
        made_with.update(mac=mac_address, channel=channel_id, kind=device_kind, name=device_name)
        return transport

    monkeypatch.setattr(spp_bridge, "BTSppTransport", _factory)
    monkeypatch.setattr(sys, "argv", ["spp_bridge.py", "--mac", "aa:bb:cc:dd:ee:ff"])
    monkeypatch.setattr(spp_bridge, "read_stdin_loop", lambda t: _noop())
    monkeypatch.setattr(spp_bridge, "read_notifications_loop", lambda t: _noop())

    await spp_bridge.main()

    assert made_with == {"mac": "aa-bb-cc-dd-ee-ff", "channel": None, "kind": "default", "name": None}


async def _noop():
    return None
