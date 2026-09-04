"""The registry of music players this project talks to.

R67/C3: `divoom_gui/permissions.py` primed macOS Automation (Apple Events)
consent for ``("Music", "Spotify")`` while the now-playing code addressed
``Music``, ``Spotify`` **and** ``Kaset``. Kaset was never primed.

That gap was invisible in the GUI and fatal in the daemon. Priming existed
because a headless daemon's consent dialog has no visible owner: the user never
saw it, the Apple Event was denied, and the daemon silently got no track, while
the foreground GUI raised a visible prompt and was granted. So Kaset "worked" in
the card and never reached the device — the reported symptom exactly.

**Phase 2 removed the cause rather than patching the list.** Now-playing comes
from macOS MediaRemote (see the `nowplaying` crate), which reads a single
system-wide source for every player that publishes to Now Playing — with NO
Apple Events and therefore no per-app Automation grant at all. Nothing in this
repo queries a player over AppleScript any more, so `apple_event_players()` is
empty and `permissions.py` has nothing to prime.

The registry is kept because the underlying class is real and would come back
the moment someone adds a player MediaRemote does not cover: a capability gate
enumerated in one place and its consumers in another will drift.
`tests/test_media_player_registry.py` discovers Apple-Event player queries
across the tree and fails if any addresses an app that is not listed here — and
fails the other way too, if a player is primed that nothing addresses, so we
cannot leave the user consenting to something unused.
"""
from __future__ import annotations

from typing import NamedTuple


class MediaPlayer(NamedTuple):
    """A player we query for the current track."""

    app_name: str
    """The macOS application name used in `tell application "..."`."""

    needs_apple_events: bool
    """True when reaching it requires an Automation (Apple Events) grant, and
    therefore up-front priming from the foreground GUI."""

    why: str
    """Shown in logs and in the permission explanation. Users deserve to know
    what a consent prompt is for."""


# Every player is now reached through MediaRemote, so none needs an Automation
# grant. They stay listed because the registry is what the drift gate checks
# against: if a future player has to be driven over AppleScript, flipping its
# flag here is the single edit that also primes it.
_VIA_MEDIA_REMOTE = (
    "reached through macOS MediaRemote (the system Now Playing source), which "
    "needs no Automation grant"
)

PLAYERS: tuple[MediaPlayer, ...] = (
    MediaPlayer(
        app_name="Kaset",
        needs_apple_events=False,
        why=f"YouTube Music client — {_VIA_MEDIA_REMOTE}. Verified 2026-08-29: "
            "returns title, artist and real cover-art bytes.",
    ),
    MediaPlayer(
        app_name="Spotify",
        needs_apple_events=False,
        why=f"{_VIA_MEDIA_REMOTE}.",
    ),
    MediaPlayer(
        app_name="Music",
        needs_apple_events=False,
        why=f"Apple Music — {_VIA_MEDIA_REMOTE}.",
    ),
    MediaPlayer(
        app_name="Feishin",
        needs_apple_events=False,
        why="Navidrome/Subsonic client — read via its cached credentials, "
            "never Apple Events.",
    ),
)


def apple_event_players() -> tuple[str, ...]:
    """App names that need an Automation grant — the priming list.

    `divoom_gui/permissions.py` uses exactly this; it must never hardcode its
    own copy again.
    """
    return tuple(p.app_name for p in PLAYERS if p.needs_apple_events)


def all_player_names() -> tuple[str, ...]:
    """Every player in the registry, Apple-Events or not."""
    return tuple(p.app_name for p in PLAYERS)
