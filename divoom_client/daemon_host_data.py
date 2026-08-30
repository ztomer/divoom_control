"""Host-data RPCs: the facts the DAEMON owns and the GUI must not re-derive.

Grouped here because they share one rationale, not because the file was long.
Each of these answers a question about the HOST -- what is playing, which
players exist, the weather, the machine's own load -- and each was once answered
a second time inside the GUI process. R67/C2 named that class: the GUI must be a
CLIENT, not a parallel implementation. Two implementations of one fact always
drift, and when they do the preview lies while every test stays green, because
both halves were individually correct.

The concrete damage each one caused is in its own docstring; they are worth
keeping together so the next "the GUI could just compute this" has somewhere to
be argued with.
"""
from __future__ import annotations


class HostDataMixin:
    """Daemon-owned host facts. Mixed into :class:`DaemonClient`."""

    def now_playing(self, include_artwork: bool = False) -> dict:
        """What is playing, from the daemon's single source of truth.

        R67/C2: the GUI used to answer this itself, in Python, by driving
        AppleScript at each player and then guessing a cover-art URL from the
        iTunes Search API — a second implementation of what the daemon already
        did, running in the GUI process, which is why the GUI was the thing
        asking for Apple Music access.

        ``include_artwork`` attaches the raw image bytes as base64. They are
        ~360KB, so a poller should watch ``identity`` (which excludes artwork)
        and only fetch the bytes when it changes.
        """
        return self.send_command("now_playing",
                                 {"include_artwork": bool(include_artwork)})

    def players(self) -> dict:
        """Every media player the daemon can see, and which is playing.

        R67: `now_playing` reports the ONE session macOS considers current, and
        macOS keeps that session on a PAUSED player — so a paused Kaset made a
        playing Feishin look silent. This separates registration from playback,
        and carries a `hint` when a player is running but unreachable for a
        reason the user can fix.
        """
        return self.send_command("players")

    def weather(self, location: str = "") -> dict:
        """One weather reading, from the source that feeds the device.

        R67/C2: the GUI used to fetch this itself while the daemon fetched it
        again for the device — two fetches of one fact, and potentially two
        different cities, because `location` was never passed through. Empty
        `location` lets the provider geolocate.
        """
        return self.send_command("weather", {"location": location or ""})

    def sysmon(self, size: int = 16) -> dict:
        """Host metrics AND the frame the device would be shown, together.

        The frame arrives as `frame_rgb_b64`: base64 of `size * size * 3` raw
        RGB bytes, from the same renderer the live sysmon job pushes. The GUI
        used to sample psutil and draw its own PIL version, so the preview tile
        and the device were two programs that happened to agree — the same
        second-implementation shape R67/C2 removed from now-playing and weather.
        """
        return self.send_command("sysmon", {"size": int(size)})
