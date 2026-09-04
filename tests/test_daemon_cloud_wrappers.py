"""The cloud wrappers must send the RIGHT command — proven on the wire.

R70 P1.1. These wrappers are the seam whose absence caused all five cloud
panels to import `CloudClient` instead. Their whole job is to name a daemon
command correctly, so the test has to check the name and the arguments AS SENT,
not merely that a reply came back.

That distinction is the point. A test that asserted "the call returned a list"
would pass while the wrapper sent `get_dial_lst`, because the assertion would
be satisfied by the error path returning `[]` — which is precisely the shape of
bug this workstream exists to end. So the stub here is a REAL unix socket
speaking the real NDJSON framing, and every wrapper is pinned against the exact
request it must produce.

The error half matters as much as the happy half: `CloudUnavailable.cause` is
what lets a panel say "the background service is not running" instead of
"nothing found", so the three causes are pinned as distinguishable.
"""
from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import uuid

import pytest

from divoom_client.daemon_cloud import CloudUnavailable
from divoom_client.daemon_protocol import DaemonClient


class StubDaemon:
    """A real unix socket that records requests and replies with canned JSON."""

    def __init__(self, reply: dict):
        self.reply = reply
        self.requests: list[dict] = []
        self.path = os.path.join(
            tempfile.gettempdir(), f"divoom_cloud_stub_{uuid.uuid4().hex[:8]}.sock")
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(self.path)
        self._srv.listen(8)
        self._stop = False
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

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
        try:
            self._srv.close()
        except OSError:
            pass
        try:
            os.unlink(self.path)
        except OSError:
            pass


@pytest.fixture
def stub():
    made: list[StubDaemon] = []

    def _make(reply: dict) -> tuple[StubDaemon, DaemonClient]:
        s = StubDaemon(reply)
        made.append(s)
        return s, DaemonClient(socket_path=s.path)

    yield _make
    for s in made:
        s.close()


OK = {"success": True, "result": ["a", "b"]}

# The contract, as a table: (wrapper call, expected command, expected args).
# Anything the daemon's dispatch.rs does not accept under exactly these names
# is a wrapper that will return "nothing found" forever.
CONTRACT = [
    (lambda c: c.get_dial_types(), "get_dial_types", {}),
    (lambda c: c.get_dial_list("Social", 2), "get_dial_list",
     {"dial_type": "Social", "page": 2}),
    (lambda c: c.list_clock_faces("Normal", 3), "list_clock_faces",
     {"dial_type": "Normal", "page": 3}),
    (lambda c: c.list_clock_faces(), "list_clock_faces", {"page": 1}),
    (lambda c: c.get_my_playlists(10, 2), "get_my_playlists",
     {"limit": 10, "page": 2}),
    (lambda c: c.get_playlist_images(77, 5, 1), "get_playlist_images",
     {"play_id": 77, "limit": 5, "page": 1}),
    (lambda c: c.get_aid_sleep_list(1, 20, 1), "get_aid_sleep_list",
     {"sleep_type": 1, "limit": 20, "page": 1}),
    (lambda c: c.get_my_aid_sleep_list(0), "get_my_aid_sleep_list",
     {"sleep_type": 0, "limit": 30, "page": 1}),
    (lambda c: c.get_photo_albums(), "get_photo_albums", {}),
    (lambda c: c.search_weather_city("Tel Aviv"), "search_weather_city",
     {"keyword": "Tel Aviv"}),
    (lambda c: c.fetch_gallery(9, 30, 1, 127), "fetch_gallery",
     {"classify": 9, "limit": 30, "file_sort": 1, "file_size": 127}),
    (lambda c: c.get_category_file_list(9, 20), "get_category_file_list",
     {"classify": 9, "limit": 20}),
    (lambda c: c.get_category_file_list(), "get_category_file_list",
     {"limit": 20}),
]


@pytest.mark.parametrize("call, command, args", CONTRACT,
                         ids=[c[1] + str(i) for i, c in enumerate(CONTRACT)])
def test_wrapper_sends_exactly_the_expected_command(stub, call, command, args):
    s, client = stub(OK)
    call(client)
    assert len(s.requests) == 1
    assert s.requests[0]["command"] == command
    assert s.requests[0]["args"] == args


def test_every_command_this_module_sends_exists_in_the_daemon_dispatch():
    """The names are checked against `divoomd/src/daemon/dispatch.rs` itself.

    A wrapper whose command the daemon does not route falls into the catch-all
    (`command not implemented in the native daemon yet`) and reports as an empty
    panel — the exact symptom, with a working-looking client. Reading the Rust
    keeps this honest without a running daemon.
    """
    from pathlib import Path
    repo = Path(__file__).resolve().parent.parent
    dispatch = (repo / "divoomd" / "src" / "daemon" / "dispatch.rs").read_text()
    sync = (repo / "divoomd" / "src" / "sync_artwork.rs").read_text()
    for _call, command, _args in CONTRACT:
        assert f'"{command}"' in dispatch, f"{command} is not routed by the daemon"
    assert '"get_animated_preview"' in dispatch
    assert "pub async fn get_animated_preview" in sync


def test_get_animated_preview_returns_the_data_url(stub):
    s, client = stub({"success": True, "file_id": "x", "preview": "data:image/gif;base64,AAA"})
    assert client.get_animated_preview("group1/M00/x") == "data:image/gif;base64,AAA"
    assert s.requests[0]["command"] == "get_animated_preview"
    assert s.requests[0]["args"] == {"file_id": "group1/M00/x"}


def test_get_cached_credentials_passes_null_through(stub):
    """A daemon with no cached login answers success + null, which is an
    ANSWER, not a failure — raising here would report "cloud broken" for an
    account that simply has not logged in yet."""
    s, client = stub({"success": True, "credentials": None})
    assert client.get_cached_credentials() is None


# ── the failure half: reasons, and causes that stay distinguishable ──────────

def test_a_cloud_error_carries_the_daemon_reason(stub):
    s, client = stub({"success": False,
                      "error": "Photo/GetAlbumList failed (RC=3): Request data is incomplete"})
    with pytest.raises(CloudUnavailable) as exc:
        client.get_photo_albums()
    assert "RC=3" in exc.value.reason
    assert exc.value.cause == "cloud"


def test_an_auth_failure_is_classified_as_auth(stub):
    s, client = stub({"success": False, "error": "UserNewGuest failed (RC=10)"})
    with pytest.raises(CloudUnavailable) as exc:
        client.get_my_playlists()
    assert exc.value.cause == "auth"


def test_an_absent_daemon_is_unreachable_not_a_cloud_error():
    """The distinction a panel needs: "the service is not running" is not
    "Divoom returned nothing", and a user can only act on the first."""
    client = DaemonClient(socket_path="/tmp/divoom_definitely_not_here.sock")
    with pytest.raises(CloudUnavailable) as exc:
        client.get_dial_types()
    assert exc.value.cause == "unreachable"
    assert "not running" in exc.value.reason


def test_the_three_causes_produce_three_different_messages(stub):
    """P2.4's requirement, pinned at the seam: if these collapsed into one
    sentence, "says why" would be no better than the `[]` it replaces."""
    seen = {}
    for reply, expect in (
        ({"success": False, "error": "Weather/SearchCity failed (RC=1): Failed"}, "cloud"),
        ({"success": False, "error": "UserNewGuest failed (RC=10)"}, "auth"),
    ):
        s, client = stub(reply)
        with pytest.raises(CloudUnavailable) as exc:
            client.search_weather_city("x")
        seen[exc.value.cause] = exc.value.reason
    client = DaemonClient(socket_path="/tmp/divoom_definitely_not_here.sock")
    with pytest.raises(CloudUnavailable) as exc:
        client.search_weather_city("x")
    seen[exc.value.cause] = exc.value.reason

    assert set(seen) == {"cloud", "auth", "unreachable"}
    assert len(set(seen.values())) == 3


def test_an_empty_result_is_success_not_an_error(stub):
    """A genuinely empty catalog must NOT raise. Conflating "no results" with
    "could not ask" is the same collapse in the other direction."""
    s, client = stub({"success": True, "result": []})
    assert client.get_dial_types() == []


def test_cloud_calls_use_the_cloud_timeout_not_the_2s_default(stub):
    """The daemon's own HTTP timeout is 15s and it re-authenticates and retries
    on an expired token, so a 2s read would abandon replies that were on their
    way — indistinguishable, from the panel, from an empty result."""
    from divoom_client.daemon_config import load_daemon_config
    cfg = load_daemon_config()
    assert cfg.cloud_timeout >= 30, "cloud_timeout must outlast the daemon's retry path"
    assert cfg.cloud_timeout > cfg.client_timeout

    s, client = stub(OK)
    seen: dict = {}
    original = DaemonClient.send_command

    def spy(self, command, args=None, *, read_timeout=None, **kw):
        seen["read_timeout"] = read_timeout
        return original(self, command, args, read_timeout=read_timeout, **kw)

    DaemonClient.send_command = spy
    try:
        client.get_dial_types()
    finally:
        DaemonClient.send_command = original
    assert seen["read_timeout"] == cfg.cloud_timeout


# ── credentials: the wrappers R72 P1.1 added ─────────────────────────────────
#
# The GUI stopped calling divoom_lib.divoom_auth and now goes through these.
# They were shipped with zero coverage, which the pre-push floor caught.

def test_get_credentials_returns_a_value_object(stub):
    s, client = stub({"success": True, "token": 42, "user_id": 7,
                      "email": "a@b.com", "utc": 123})
    creds = client.get_credentials()
    assert creds.token == 42 and creds.user_id == 7
    assert creds.email == "a@b.com" and creds.utc == 123
    assert creds.is_valid()
    assert s.requests[-1]["command"] == "get_credentials"


def test_get_credentials_forwards_force_refresh(stub):
    """The flag decides whether the daemon re-logs in; dropping it silently
    would turn a deliberate refresh into a cache read."""
    s, client = stub({"success": True, "token": 1, "user_id": 1})
    client.get_credentials(force_refresh=True)
    assert s.requests[-1]["args"]["force_refresh"] is True
    client.get_credentials()
    assert s.requests[-1]["args"]["force_refresh"] is False


def test_get_credentials_raises_cloud_unavailable_on_failure(stub):
    from divoom_client.daemon_cloud import CloudUnavailable

    _s, client = stub({"success": False, "error": "UserNewGuest RC=10"})
    with pytest.raises(CloudUnavailable) as exc:
        client.get_credentials()
    assert "RC=10" in str(exc.value)


def test_save_credentials_sends_both_fields(stub):
    s, client = stub({"success": True, "token": 5, "user_id": 6, "email": "x@y.z"})
    creds = client.save_credentials("x@y.z", "hunter2")
    assert creds.is_valid() and creds.email == "x@y.z"
    args = s.requests[-1]["args"]
    assert args == {"email": "x@y.z", "password": "hunter2"}


def test_save_credentials_passes_a_blank_password_through(stub):
    """An empty password is MEANINGFUL: the daemon reads it as "keep the
    stored one". A wrapper that filtered it would make the email-only save
    unreachable -- see cloud_store::save_config."""
    s, client = stub({"success": True, "token": 5, "user_id": 6})
    client.save_credentials("x@y.z", "")
    assert s.requests[-1]["args"]["password"] == ""


def test_save_credentials_raises_on_failure(stub):
    from divoom_client.daemon_cloud import CloudUnavailable

    _s, client = stub({"success": False, "error": "saved, but login failed"})
    with pytest.raises(CloudUnavailable):
        client.save_credentials("x@y.z", "pw")


def test_credentials_value_object_semantics():
    """`is_valid` is token AND user_id non-zero -- the same predicate
    divoom_lib.DivoomCredentials used. It is not an expiry check."""
    from divoom_client.daemon_cloud import DaemonCredentials

    assert DaemonCredentials.from_reply(None) is None
    assert DaemonCredentials.from_reply({}).is_valid() is False
    assert DaemonCredentials.from_reply({"token": 1, "user_id": 0}).is_valid() is False
    assert DaemonCredentials.from_reply({"token": 0, "user_id": 1}).is_valid() is False
    assert DaemonCredentials.from_reply({"token": 1, "user_id": 1}).is_valid() is True
    # Missing/garbage fields must not raise -- a daemon mid-upgrade can omit them.
    assert DaemonCredentials.from_reply({"token": None, "email": None}).token == 0
