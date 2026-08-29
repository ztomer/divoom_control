"""The registry of music players this project talks to.

R67/C3: `divoom_gui/permissions.py` primed macOS Automation (Apple Events)
consent for ``("Music", "Spotify")`` while the now-playing code addressed
``Music``, ``Spotify`` **and** ``Kaset``. Kaset was never primed.

That gap is invisible in the GUI and fatal in the daemon. Priming exists because
a headless daemon's consent dialog has no visible owner: the user never sees it,
the Apple Event is denied, and the daemon silently gets no track. The foreground
GUI, by contrast, raises a visible prompt and gets granted. So Kaset "worked"
in the card and never reached the device — the reported symptom exactly.

The class is a capability gate enumerated in one place and its consumers
enumerated in another. The fix is to have one list and derive both from it:
`permissions.py` primes what is here, the query code addresses what is here, and
`tests/test_media_player_registry.py` fails if any AppleScript-addressed
application in the Python *or* Rust now-playing code is missing from it.

Adding a player is therefore one edit here, and forgetting to prime it is a test
failure rather than a silent denial in the daemon only.
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


# Order is query order: the richest source first. Feishin is checked before the
# AppleScript players because it returns a direct cover-art URL without needing
# an Automation grant at all.
PLAYERS: tuple[MediaPlayer, ...] = (
    MediaPlayer(
        app_name="Feishin",
        needs_apple_events=False,
        why="Navidrome/Subsonic client — read via its cached credentials, not Apple Events.",
    ),
    MediaPlayer(
        app_name="Kaset",
        needs_apple_events=True,
        why="YouTube Music client — returns a direct thumbnail URL, higher quality "
            "than the iTunes Search fallback.",
    ),
    MediaPlayer(
        app_name="Spotify",
        needs_apple_events=True,
        why="Track and artist for album-art lookup.",
    ),
    MediaPlayer(
        app_name="Music",
        needs_apple_events=True,
        why="Apple Music — track and artist for album-art lookup.",
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
