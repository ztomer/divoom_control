"""P2.7: a daemon the GUI respawns gets the GUI's panels back.

Traced on 2026-10-18 (Pixoo-1, v0.41.2): three SIGTERMs of the daemon with the
GUI running each had `reconnect_daemon` spawn a new daemon -- and nothing else.
No `connect` was issued, `device_status` said `devices: []`, and the panel
stayed dark until the user clicked it. The GUI is the one that knows which
panels it linked, so its respawn path is the one that asks for them back.

No radio: the daemon is a fake client at the `ensure_daemon` seam, its
identity is its `get_status` uptime (a fresh daemon reports ~0 s), and the
panel it holds is whatever `connect_device` has linked on THAT instance.
"""
from __future__ import annotations

import pytest

from tests.support.scanner_support import host  # noqa: F401

MAC = "11:22:33:44:55:66"


class FakeDaemon:
    """One daemon instance: a start time, and the panels linked on it."""

    def __init__(self, uptime_s: int) -> None:
        self.uptime_s = uptime_s
        self.linked: list[str] = []
        self.connects: list[dict] = []

    def get_status(self) -> dict:
        return {"success": True, "uptime_s": self.uptime_s}

    def send_command(self, cmd: str, args=None, **_kw) -> dict:
        assert cmd == "get_status", cmd
        return self.get_status()

    def connect_device(self, **kw) -> dict:
        self.connects.append(kw)
        self.linked.append(kw.get("mac") or f"LAN:{kw.get('lan_ip')}")
        return {"success": True, "connected": True}

    def device_status(self, mac: str | None = None) -> dict:
        devices = [{"mac": m, "connected": True} for m in self.linked]
        if mac is not None:
            return {"success": True, "connected": mac in self.linked}
        return {"success": True, "devices": devices}


@pytest.fixture
def daemons(monkeypatch):
    """`ensure_daemon` returns whichever daemon is currently 'running'."""
    state = {"current": FakeDaemon(uptime_s=500)}
    monkeypatch.setattr("divoom_gui.daemon_bridge.ensure_daemon",
                        lambda *a, **k: state["current"])
    return state


def _settle(h) -> None:
    t = getattr(h, "_relink_thread", None)
    if t is not None:
        t.join(timeout=5)
        assert not t.is_alive(), "relink thread did not finish"


def test_respawned_daemon_gets_the_linked_panel_back(host, daemons):  # noqa: F811
    old = daemons["current"]
    assert host.connect_single_device(MAC) is True
    assert old.linked == [MAC]

    # The daemon dies; the GUI's banner path respawns one (reconnect_daemon).
    new = FakeDaemon(uptime_s=0)
    daemons["current"] = new
    host.reconnect_daemon()
    _settle(host)

    assert [c.get("mac") for c in new.connects] == [MAC], (
        "the respawned daemon was never asked to link the panel the old one held")


def test_a_live_daemon_is_not_asked_to_relink(host, daemons):  # noqa: F811
    """The respawn is what triggers it: the same instance gets no extra connect."""
    same = daemons["current"]
    assert host.connect_single_device(MAC) is True
    same.linked.clear()  # its link dropped -- P2.8's business, not a respawn
    # Same instance: its start time (now - uptime_s) has not moved.
    host.reconnect_daemon()
    _settle(host)
    assert len(same.connects) == 1


def test_a_panel_the_new_daemon_already_holds_is_left_alone(host, daemons):  # noqa: F811
    assert host.connect_single_device(MAC) is True
    new = FakeDaemon(uptime_s=0)
    new.linked = [MAC]  # e.g. another client linked it first
    daemons["current"] = new
    host.reconnect_daemon()
    _settle(host)
    assert new.connects == []


def test_lan_panel_is_relinked_with_its_address(host, daemons):  # noqa: F811
    assert host.connect_single_device("LAN:192.168.1.50") is True
    new = FakeDaemon(uptime_s=0)
    daemons["current"] = new
    host.reconnect_daemon()
    _settle(host)
    assert [c.get("lan_ip") for c in new.connects] == ["192.168.1.50"]
