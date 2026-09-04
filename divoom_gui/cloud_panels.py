"""The ONE way a cloud-browse panel asks for a list.

R70 P2.1/P2.4. Five panels — clock faces, playlists, sleep sounds, photo
albums, city search — each did this:

    try:
        return CloudClient().get_whatever()
    except Exception as e:
        logger.error(...)
        return []

Three things were wrong with it, and only the first is obvious.

**It ran the cloud call in the GUI process.** The daemon has routed every one
of these commands since the native-UI experiment; that UI was retired and took
the only client with it, so each panel independently found `CloudClient` easier
than adding a wrapper that did not exist.

**It could not say why it was empty.** "Nothing found" covered a genuinely
empty catalog, an unreachable daemon, an unauthenticated account and a cloud
error equally. The daemon has always answered with the real reason — the
photo-album browse returns `Photo/GetAlbumList failed (RC=3): Request data is
incomplete` — and the GUI discarded it at the `except`.

**The doctrine was written down and looked reasonable.**
`weather_city.search_weather_city` explained itself: "Returns [] rather than
raising for the same reason every other cloud browse in this GUI does: a search
that errors should show 'no results', not break the panel it lives in." The
premise is false — a panel that says "the background service is not running" is
not broken, it is honest — but stated that way it reads as care, which is how
the pattern spread to five panels instead of being fixed in one.

**The envelope.** Every panel here returns
``{"ok": bool, "items": [...], "error": str, "cause": str}``. Callers get a
list on success and a REASON on failure, and `cause` is a flag
(``unreachable`` / ``auth`` / ``cloud``) rather than parsed error text, so the
UI can branch without matching on wording that may be reworded.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger("divoom_gui")


class CloudPanelMixin:
    """`_cloud_list` and nothing else. Mixed into the GUI API."""

    def _cloud_list(self, what: str,
                    call: Callable[[Any], list]) -> dict:
        """Run one cloud browse through the daemon and wrap the outcome.

        ``what`` names the thing being fetched, for a message a user can read
        ("could not load clock faces: ..."). ``call`` receives the daemon
        client — panels pass a one-liner, so there is no room for a panel to
        quietly do something else.
        """
        from divoom_client.daemon_cloud import CloudUnavailable

        try:
            client = self._client()
        except Exception as exc:  # ensure_daemon can fail outright
            return self._cloud_error(what, str(exc), "unreachable")
        if client is None:
            return self._cloud_error(
                what, "the background service is not running", "unreachable")

        try:
            items = call(client)
        except CloudUnavailable as exc:
            return self._cloud_error(what, exc.reason, exc.cause)
        except Exception as exc:
            # An unexpected shape is still a reason, and still not an empty
            # list. Silence here is what this module exists to remove.
            logger.exception("%s failed", what)
            return self._cloud_error(what, str(exc), "cloud")

        return {"ok": True, "items": list(items or []), "error": "", "cause": ""}

    @staticmethod
    def _cloud_error(what: str, reason: str, cause: str) -> dict:
        logger.error("%s unavailable (%s): %s", what, cause, reason)
        return {"ok": False, "items": [], "error": f"Could not load {what}: {reason}",
                "cause": cause}
