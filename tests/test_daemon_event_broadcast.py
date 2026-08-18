"""Verify the daemon *broadcasts* connection state so the UI can update live.

R58/UI-reliability gap: the daemon now emits enriched `status` events on
connect/disconnect carrying `connected` + `mac`/`lan_ip`. A subscriber (the GUI
→ web UI) must receive those events and be able to update connection state
*without* polling. This test proves the events are actually delivered and
carry the fields the UI needs — the foundation for "the UI gets the updates".

Hardware-free: uses the daemon's built-in mock transport.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from divoom_daemon.daemon_protocol import DaemonClient  # noqa: E402

_DIVOOMD = _REPO / "target" / "release" / "divoomd"


def _wait_for_socket(path: Path, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                s.connect(str(path))
            return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"daemon socket {path} never came up")


@pytest.fixture
def mock_daemon():
    """Spawn the real daemon (release binary) on a temp socket in mock mode."""
    if not _DIVOOMD.exists():
        pytest.skip(f"divoomd binary not built at {_DIVOOMD}")
    sock = tempfile.NamedTemporaryFile(suffix=".sock", delete=False)
    sock.close()
    path = Path(sock.name)
    proc = subprocess.Popen(
        [str(_DIVOOMD), "--socket", str(path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_socket(path)
        yield str(path)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        try:
            path.unlink()
        except OSError:
            pass


class _Subscriber:
    """Single persistent subscription; collects events + block-until-pred."""

    def __init__(self, path: str):
        self._events: list[dict] = []
        self._lock = threading.Lock()
        self._cv = threading.Condition()
        self._path = path
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        client = DaemonClient(socket_path=self._path)

        def on_event(ev):
            with self._cv:
                self._events.append(ev)
                self._cv.notify_all()

        def should_stop():
            return self._stop

        client.subscribe(on_event, should_stop=should_stop)

    def wait_for(self, pred, timeout: float = 6.0) -> list[dict]:
        deadline = time.time() + timeout
        with self._cv:
            while time.time() < deadline:
                with self._lock:
                    snap = list(self._events)
                if pred(snap):
                    return snap
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                self._cv.wait(timeout=min(remaining, 0.2))
        with self._lock:
            return list(self._events)

    def close(self):
        self._stop = True
        self._thread.join(timeout=2)


def test_connect_event_carries_connected_and_mac(mock_daemon):
    """On connect (mock), a `status` event must report connected=true + the mac."""
    sub = _Subscriber(mock_daemon)
    try:
        # Ensure the subscription is established (initial snapshot received)
        # before issuing connect, so we don't miss the broadcast.
        sub.wait_for(lambda evs: any(e.get("type") == "status" for e in evs), timeout=3)
        DaemonClient(socket_path=mock_daemon).send_command("connect", {"mock": True})
        snap = sub.wait_for(
            lambda evs: any(e.get("type") == "status" and e.get("connected") is True for e in evs)
        )
    finally:
        sub.close()
    status_evs = [e for e in snap if e.get("type") == "status"]
    assert status_evs, f"no status events received: {snap}"
    conn = [e for e in status_evs if e.get("connected") is True]
    assert conn, f"no connected=true status event: {status_evs}"
    assert conn[0].get("mac") == "MOCK_MAC", f"event missing mac: {conn[0]}"
    assert conn[0].get("state") == "active"


def test_disconnect_event_reports_connected_false(mock_daemon):
    """On disconnect, a `status` event must report connected=false (no id)."""
    sub = _Subscriber(mock_daemon)
    try:
        sub.wait_for(lambda evs: any(e.get("type") == "status" for e in evs), timeout=3)
        client = DaemonClient(socket_path=mock_daemon)
        assert client.send_command("connect", {"mock": True}).get("success") is True
        sub.wait_for(
            lambda evs: any(e.get("type") == "status" and e.get("connected") is True for e in evs)
        )
        client.send_command("disconnect")
        snap = sub.wait_for(
            lambda evs: any(e.get("type") == "status" and e.get("connected") is False for e in evs)
        )
    finally:
        sub.close()
    disc = [e for e in snap if e.get("type") == "status" and e.get("connected") is False]
    assert disc, f"no connected=false status event after disconnect: {snap}"
    assert disc[0].get("state") == "idle"
    assert "mac" not in disc[0] and "lan_ip" not in disc[0]


def test_owned_devices_event_on_connect_and_disconnect(mock_daemon):
    """The daemon must broadcast the owned-device set on connect/disconnect so
    the UI stops polling get_device_activity every 4s (R59/event-driven)."""
    sub = _Subscriber(mock_daemon)
    try:
        sub.wait_for(lambda evs: any(e.get("type") == "status" for e in evs), timeout=3)
        DaemonClient(socket_path=mock_daemon).send_command("connect", {"mock": True})
        snap = sub.wait_for(
            lambda evs: any(e.get("type") == "owned_devices" for e in evs)
        )
        owned = [e for e in snap if e.get("type") == "owned_devices"]
        assert owned, f"no owned_devices event: {snap}"
        devs = owned[-1].get("devices", [])
        assert any(d.get("address") == "MOCK_MAC" for d in devs), f"owned set missing mac: {devs}"

        DaemonClient(socket_path=mock_daemon).send_command("disconnect")
        snap2 = sub.wait_for(
            lambda evs: any(
                e.get("type") == "owned_devices" and e.get("devices") == [] for e in evs
            )
        )
        cleared = [e for e in snap2 if e.get("type") == "owned_devices" and e.get("devices") == []]
        assert cleared, f"owned_devices not cleared on disconnect: {snap2}"
    finally:
        sub.close()
