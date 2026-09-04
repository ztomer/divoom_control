"""The five cloud panels are CLIENTS, and they say why they are empty.

R70 P2.1/P2.4. These tests assert the architecture, not the return value, and
the difference matters: a test that checked "get_dial_types returns a list"
passed for years while the panel ran its own HTTP against
`appin.divoom-gz.com`, because the `except -> []` returned a list too.

So each panel is checked for two things:

* the daemon command went out on the socket, AND
* **no HTTP left this process.** The second half is the one that encodes the
  rule. A panel that asks the daemon *and also* calls the cloud passes a
  socket-only assertion, and that is exactly the half-migrated state a staged
  rollout produces.

The failure half is checked for distinguishability. Three causes must yield
three different messages, or "says why" collapses back into one generic
sentence that is no better than the `[]` it replaced.

Hole A, from the test plan: the existing e2e suites for these panels stub
`window.pywebview.api` in JS, so the Python here had never been executed by a
test at all. That is why four of these five panels sat at 38-50% coverage,
the lowest in the tree.
"""
from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import uuid

import pytest

from divoom_client.daemon_protocol import DaemonClient


class StubDaemon:
    def __init__(self, reply: dict):
        self.reply = reply
        self.requests: list[dict] = []
        self.path = os.path.join(
            tempfile.gettempdir(), f"divoom_panel_{uuid.uuid4().hex[:8]}.sock")
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(self.path)
        self._srv.listen(8)
        self._stop = False
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while not self._stop:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                return
            with conn:
                buf = b""
                try:
                    while b"\n" not in buf:
                        chunk = conn.recv(65536)
                        if not chunk:
                            break
                        buf += chunk
                    if buf:
                        self.requests.append(json.loads(buf.split(b"\n")[0]))
                        conn.sendall(json.dumps(self.reply).encode() + b"\n")
                except OSError:
                    pass

    def close(self) -> None:
        self._stop = True
        for fn in (self._srv.close, lambda: os.unlink(self.path)):
            try:
                fn()
            except OSError:
                pass


@pytest.fixture
def no_http(monkeypatch):
    """Make ANY outbound HTTP from this process an immediate, loud failure.

    This is the assertion that actually encodes "the GUI is a client". Without
    it a panel could ask the daemon and still call the cloud itself, and every
    socket-level check would stay green.
    """
    calls: list[str] = []

    def boom(*a, **kw):
        calls.append(str(a[:1]))
        raise AssertionError(
            "the GUI made an HTTP call — cloud access belongs to the daemon")

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(urllib.request, "Request", boom)
    try:
        import requests
        monkeypatch.setattr(requests, "get", boom)
        monkeypatch.setattr(requests, "post", boom)
    except ImportError:
        pass
    return calls


@pytest.fixture
def panel(no_http):
    """A GUI API object carrying all five panel mixins, wired to a stub."""
    made: list[StubDaemon] = []

    def _make(reply: dict):
        from divoom_gui.aid_sleep import AidSleepMixin
        from divoom_gui.clock_faces import ClockFacesMixin
        from divoom_gui.photo_albums import PhotoAlbumsMixin
        from divoom_gui.playlists import PlaylistsMixin
        from divoom_gui.weather_city import WeatherCityMixin

        stub = StubDaemon(reply)
        made.append(stub)
        client = DaemonClient(socket_path=stub.path)

        class Api(ClockFacesMixin, PlaylistsMixin, AidSleepMixin,
                  PhotoAlbumsMixin, WeatherCityMixin):
            def _client(self):
                return client

        return stub, Api()

    yield _make
    for s in made:
        s.close()


OK = {"success": True, "result": [{"Name": "one"}, {"Name": "two"}]}

# (panel call, the daemon command it MUST send)
PANELS = [
    (lambda a: a.get_dial_types(), "get_dial_types"),
    (lambda a: a.get_dial_list("Social"), "get_dial_list"),
    (lambda a: a.get_my_playlists(), "get_my_playlists"),
    (lambda a: a.get_aid_sleep_list(1), "get_aid_sleep_list"),
    (lambda a: a.get_photo_albums(), "get_photo_albums"),
    (lambda a: a.search_weather_city("Tel Aviv"), "search_weather_city"),
]


@pytest.mark.parametrize("call, command", PANELS, ids=[p[1] for p in PANELS])
def test_the_panel_asks_the_daemon_and_makes_no_http_call(panel, call, command):
    stub, api = panel(OK)
    result = call(api)
    assert result["ok"] is True, result
    assert result["items"] == [{"Name": "one"}, {"Name": "two"}]
    assert [r["command"] for r in stub.requests] == [command]


@pytest.mark.parametrize("call, command", PANELS, ids=[p[1] for p in PANELS])
def test_a_failure_carries_the_daemons_reason_not_an_empty_list(panel, call, command):
    stub, api = panel({"success": False,
                       "error": "Photo/GetAlbumList failed (RC=3): Request data is incomplete"})
    result = call(api)
    assert result["ok"] is False
    assert result["items"] == []
    assert "RC=3" in result["error"], result
    assert result["cause"] == "cloud"


def test_an_empty_catalog_is_a_success_not_a_failure(panel):
    """The other direction of the same collapse: a genuinely empty result must
    not be reported as a problem, or the panel cries wolf."""
    stub, api = panel({"success": True, "result": []})
    result = api.get_my_playlists()
    assert result["ok"] is True and result["items"] == []
    assert result["error"] == ""


def test_the_three_causes_stay_distinguishable(panel):
    """P2.4's actual requirement. If these produced one message, "says why"
    would be no better than the [] it replaced."""
    seen = {}

    stub, api = panel({"success": False, "error": "Weather/SearchCity failed (RC=1): Failed"})
    r = api.search_weather_city("x")
    seen[r["cause"]] = r["error"]

    stub, api = panel({"success": False, "error": "UserNewGuest failed (RC=10)"})
    r = api.get_my_playlists()
    seen[r["cause"]] = r["error"]

    from divoom_gui.playlists import PlaylistsMixin

    class Absent(PlaylistsMixin):
        def _client(self):
            return None

    r = Absent().get_my_playlists()
    seen[r["cause"]] = r["error"]

    assert set(seen) == {"cloud", "auth", "unreachable"}, seen
    assert len(set(seen.values())) == 3, seen


def test_an_absent_daemon_names_the_service_not_the_cloud(panel):
    from divoom_gui.clock_faces import ClockFacesMixin

    class Absent(ClockFacesMixin):
        def _client(self):
            return None

    r = Absent().get_dial_types()
    assert r["ok"] is False
    assert r["cause"] == "unreachable"
    assert "background service" in r["error"]


def test_an_empty_keyword_is_an_empty_result_not_an_error(panel):
    """Nothing to report and nothing went wrong — reporting a failure here
    would be the cry-wolf direction of the same mistake."""
    stub, api = panel(OK)
    r = api.search_weather_city("   ")
    assert r["ok"] is True and r["items"] == []
    assert stub.requests == [], "an empty keyword must not reach the daemon"


def test_no_panel_imports_the_cloud_client_any_more():
    """The structural half, in case someone re-adds a convenience import: the
    gate enforces this repo-wide, and this pins the five files by name."""
    from pathlib import Path
    gui = Path(__file__).resolve().parent.parent / "divoom_gui"
    for name in ("clock_faces.py", "playlists.py", "aid_sleep.py",
                 "photo_albums.py", "weather_city.py"):
        src = (gui / name).read_text()
        assert "divoom_lib.cloud" not in src, f"{name} still imports CloudClient"
        assert "CloudPanelMixin" in src, f"{name} must go through the funnel"
