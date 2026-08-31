"""Cloud-browse RPCs: the Divoom HTTP surface the DAEMON owns.

Sibling of :mod:`divoom_client.daemon_host_data`, and the same argument. That
module exists because now-playing, weather and sysmon were each answered a
second time inside the GUI process; this one exists because the cloud browse
was too, in five panels at once.

**Why this file did not exist until R70, which is the whole story.** The daemon
has wired `get_dial_types`, `get_dial_list`, `get_my_playlists`,
`get_playlist_images`, `get_aid_sleep_list`, `get_my_aid_sleep_list`,
`get_photo_albums`, `search_weather_city`, `fetch_gallery` and
`get_category_file_list` since the native-UI experiment. That UI was retired and
took the only client with it, so every panel that later needed one of these
found `from divoom_lib.cloud import CloudClient` easier than adding a wrapper
that did not exist. Five panels made that choice independently. The missing seam
WAS the defect; the twelve findings were its symptoms.

**Failures carry their reason.** Every one of those panels ended in
``except Exception: return []``, so "nothing found" covered a genuinely empty
result, an unreachable daemon, an unauthenticated account and a cloud error
equally. The daemon has always answered with the real thing — for example
``Photo/GetAlbumList failed (RC=3): Request data is incomplete`` — and the GUI
threw it away. :class:`CloudUnavailable` carries it back, with a ``cause`` the
UI can branch on so the three states stay DISTINGUISHABLE rather than collapsing
into one generic sentence, which would be no better than ``[]``.
"""
from __future__ import annotations

from typing import Any


class CloudUnavailable(RuntimeError):
    """A cloud browse could not be answered, and why.

    ``cause`` is the machine-readable half, deliberately not parsed out of the
    message text: matching on wording is not an API, and a reworded errno would
    silently change caller behaviour (the same reasoning that gave
    ``send_command`` its ``unreachable`` flag rather than an error-string
    convention).

    * ``"unreachable"`` — nothing was listening. The background service is not
      running; this is not a cloud problem and must not be reported as one.
    * ``"auth"`` — the daemon reached Divoom and was refused. Usually no
      credentials configured, or a token the server rejected.
    * ``"cloud"`` — the daemon reached Divoom and Divoom said no.
    """

    def __init__(self, reason: str, cause: str = "cloud") -> None:
        super().__init__(reason)
        self.reason = reason
        self.cause = cause


# Divoom's own return codes for an expired/mismatched token. The daemon already
# retries once on these; seeing one in a final reply means the retry also failed,
# which is an account problem and not a transient one.
_AUTH_MARKERS = ("RC=9", "RC=10", "RC=11", "UserNewGuest", "not configured",
                 "no credentials", "Token")


def _classify(reply: dict) -> str:
    if reply.get("unreachable"):
        return "unreachable"
    error = str(reply.get("error", ""))
    return "auth" if any(m in error for m in _AUTH_MARKERS) else "cloud"


class CloudDataMixin:
    """Cloud browse, as a daemon client. Mixed into :class:`DaemonClient`."""

    def cloud_call(self, command: str, args: dict | None = None) -> Any:
        """Send one cloud command and return its ``result``.

        Raises :class:`CloudUnavailable` on anything else, because the caller
        needs the reason and the alternative — returning ``[]`` — is what made
        five panels unable to say why they were empty.

        Uses ``cloud_timeout`` rather than the 2s quick-command default: these
        calls cross the network, and an auth refresh doubles the daemon's own
        15s HTTP timeout. A short read abandons a reply that was on its way,
        which looks exactly like an empty result.
        """
        from divoom_client.daemon_config import load_daemon_config

        reply = self.send_command(
            command, args or {},
            read_timeout=load_daemon_config().cloud_timeout,
        )
        if not isinstance(reply, dict):
            raise CloudUnavailable(
                f"{command}: malformed reply from the background service", "cloud")
        if not reply.get("success"):
            cause = _classify(reply)
            reason = str(reply.get("error") or "the background service said no")
            if cause == "unreachable":
                reason = f"the background service is not running ({reason})"
            raise CloudUnavailable(reason, cause)
        return reply.get("result")

    # ── clock faces (Channel/GetDialType + GetDialList) ──────────────────────
    def get_dial_types(self) -> list:
        return self.cloud_call("get_dial_types") or []

    def get_dial_list(self, dial_type: str, page: int = 1) -> list:
        return self.cloud_call(
            "get_dial_list", {"dial_type": dial_type, "page": page}) or []

    def list_clock_faces(self, dial_type: str | None = None, page: int = 1) -> list:
        """First category's list when ``dial_type`` is omitted (daemon-side
        convenience, so the GUI does not make two round trips to render a
        default view)."""
        args: dict = {"page": page}
        if dial_type is not None:
            args["dial_type"] = dial_type
        return self.cloud_call("list_clock_faces", args) or []

    # ── playlists (Playlist/GetMyList) ───────────────────────────────────────
    def get_my_playlists(self, limit: int = 30, page: int = 1) -> list:
        return self.cloud_call(
            "get_my_playlists", {"limit": limit, "page": page}) or []

    def get_playlist_images(self, play_id: int, limit: int = 30,
                            page: int = 1) -> list:
        return self.cloud_call(
            "get_playlist_images",
            {"play_id": play_id, "limit": limit, "page": page}) or []

    # ── sleep sounds (AidSleep/GetAllList) ───────────────────────────────────
    def get_aid_sleep_list(self, sleep_type: int, limit: int = 30,
                           page: int = 1) -> list:
        return self.cloud_call(
            "get_aid_sleep_list",
            {"sleep_type": sleep_type, "limit": limit, "page": page}) or []

    def get_my_aid_sleep_list(self, sleep_type: int, limit: int = 30,
                              page: int = 1) -> list:
        return self.cloud_call(
            "get_my_aid_sleep_list",
            {"sleep_type": sleep_type, "limit": limit, "page": page}) or []

    # ── photo albums (Photo/GetAlbumList) ────────────────────────────────────
    def get_photo_albums(self) -> list:
        return self.cloud_call("get_photo_albums") or []

    # ── weather city search (Weather/SearchCity) ─────────────────────────────
    def search_weather_city(self, keyword: str) -> list:
        return self.cloud_call("search_weather_city", {"keyword": keyword}) or []

    # ── gallery (GetCategoryFileListV2) ──────────────────────────────────────
    def fetch_gallery(self, classify: int, limit: int = 30, file_sort: int = 1,
                      file_size: int = 127) -> Any:
        """The cloud-voted gallery listing.

        The GUI used to POST this itself — its own credential cache, its own
        `config.ini` read, its own RC 9/10/11 retry and its own okhttp
        User-Agent, all against `appin.divoom-gz.com`. The daemon has done the
        same thing correctly the whole time.
        """
        return self.cloud_call("fetch_gallery", {
            "classify": classify, "limit": limit,
            "file_sort": file_sort, "file_size": file_size,
        })

    def get_category_file_list(self, classify: int | None = None,
                               limit: int = 20) -> Any:
        args: dict = {"limit": limit}
        if classify is not None:
            args["classify"] = classify
        return self.cloud_call("get_category_file_list", args)

    # ── credentials ──────────────────────────────────────────────────────────
    def get_cached_credentials(self) -> dict | None:
        """The daemon's cached login, without forcing a round trip to Divoom."""
        from divoom_client.daemon_config import load_daemon_config
        reply = self.send_command(
            "get_cached_credentials", {},
            read_timeout=load_daemon_config().cloud_timeout)
        if not isinstance(reply, dict) or not reply.get("success"):
            raise CloudUnavailable(
                str((reply or {}).get("error") or "credentials unavailable"),
                _classify(reply if isinstance(reply, dict) else {}))
        return reply.get("credentials")

    # ── one decoded preview (CDN download + magic-43/0xAA decode) ────────────
    def get_animated_preview(self, file_id: str) -> str:
        """A ``data:image/...;base64,`` URL for one gallery or hot-channel file.

        The daemon downloads and decodes; only the small data-url crosses the
        socket. `divoomd/src/sync_artwork.rs` names the Python GUI method it was
        written for parity with — and then nothing ever called it, so both
        halves lived on side by side.
        """
        from divoom_client.daemon_config import load_daemon_config
        reply = self.send_command(
            "get_animated_preview", {"file_id": file_id},
            read_timeout=load_daemon_config().cloud_timeout)
        if not isinstance(reply, dict) or not reply.get("success"):
            reply = reply if isinstance(reply, dict) else {}
            raise CloudUnavailable(
                str(reply.get("error") or f"no preview for {file_id}"),
                _classify(reply))
        return str(reply.get("preview") or "")
