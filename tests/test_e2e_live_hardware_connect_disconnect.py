"""Live-hardware connect/disconnect feedback verification (R61 follow-up, opt-in).

Unlike test_e2e_gui_daemon_connect_disconnect.py (an isolated daemon + mock
transport, safe for CI), this file drives the REAL default daemon socket
(``/tmp/divoom.sock``) — whatever daemon/device is actually running on this
machine, e.g. the user's live menubar + a real Divoom device. Skipped by
default (added to ``conftest.py``'s ``HARDWARE_TEST_MODULES``); run with::

    pytest tests/test_e2e_live_hardware_connect_disconnect.py --run-hardware

Deliberately READ-ONLY: it verifies the daemon's honest status reporting is
internally consistent (the same correctness property the isolated suite
checks with a mock transport), but never issues a connect/disconnect against
the live device. A real write-cycle test would mean disconnecting whatever
the user is actually using at the moment they happen to run the suite — on a
SHARED daemon there's no way to tell "idle, safe to disturb" from "someone is
mid-session with this device" from the outside. If you want to exercise a
real connect/disconnect cycle by hand, drive the daemon directly:

    python3 -c "from divoom_client.daemon_protocol import DaemonClient; \\
        c = DaemonClient('/tmp/divoom.sock'); print(c.device_status())"

The menubar's own live icon state isn't asserted on here either — reading a
real NSStatusItem's tooltip from outside the process needs macOS
Accessibility automation, which is a separate, heavier piece of tooling this
file intentionally doesn't take on. What IS asserted: the same daemon
`device_status`/`connection_state` contract the menubar (
divoom-menubar/src/daemon.rs::connection_state) and the GUI (divoom_gui/
scanner_mixin.py::get_connection_state) both read UI feedback from — so a
live run at least proves that contract holds against real (not mocked)
daemon state, whatever it currently is.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parent.parent))

from divoom_client.daemon_protocol import DaemonClient, DEFAULT_SOCKET_PATH


@pytest.fixture
def live_client():
    client = DaemonClient(DEFAULT_SOCKET_PATH)
    status = client.send_command("get_status")
    if not status.get("success"):
        pytest.skip(
            f"No live daemon reachable at {DEFAULT_SOCKET_PATH} — start it "
            "(menubar app or `divoomd --socket /tmp/divoom.sock`) before "
            "running with --run-hardware."
        )
    return client


def test_device_status_is_internally_consistent(live_client):
    """Whatever the real state is right now, the fields the GUI/menubar both
    read for connect/disconnect feedback must agree with each other — this
    is the exact honesty check ScannerMixin.get_connection_state's own
    docstring calls out ("the honest state wins over a stale connected
    flag"), now verified against a REAL daemon instead of a mock."""
    status = live_client.device_status()
    assert status.get("success") is True

    connected = bool(status.get("connected"))
    connection_state = status.get("connection_state")
    assert connection_state in ("connected", "degraded", "disconnected", None), (
        f"unexpected connection_state value: {connection_state!r}"
    )

    if connection_state == "disconnected":
        assert connected is False, (
            "device_status reports connection_state=disconnected but "
            "connected=True — this is exactly the stale-flag bug "
            "get_connection_state's honesty override exists to mask; the "
            "DAEMON itself should never produce this combination."
        )
    if connected:
        assert connection_state in ("connected", "degraded"), (
            f"connected=True but connection_state={connection_state!r} "
            "— the two fields disagree about whether a device is owned."
        )


def test_get_status_replies_promptly(live_client):
    """A live daemon must answer get_status fast — this is the exact probe
    the menubar's own poll loop (and the GUI's daemon_health) relies on to
    tell 'daemon down' from 'device disconnected'. A slow/hung reply here
    would explain a menubar stuck showing a stale icon on a real machine."""
    import time

    start = time.monotonic()
    reply = live_client.send_command("get_status")
    elapsed = time.monotonic() - start
    assert reply.get("success") is True
    assert elapsed < 2.0, f"get_status took {elapsed:.2f}s — should be near-instant"
