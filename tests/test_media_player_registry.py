"""R67/C3: the Automation priming list must cover every player we address.

The defect this pins: `permissions.py` primed ("Music", "Spotify") while the
now-playing code — in BOTH languages — also did
`tell application "Kaset"`. Nothing connected the two lists, so adding a player
without priming it was a silent, GUI-invisible failure that only bit the
headless daemon.

These tests read the ACTUAL source of both implementations and assert every
AppleScript-addressed application appears in the registry. They are deliberately
grep-based rather than import-based: the point is to catch a new
`tell application "..."` that someone adds without touching the registry, and an
import cannot see a string that was never wired up.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from divoom_lib.utils.media_players import (
    PLAYERS,
    all_player_names,
    apple_event_players,
)

REPO = Path(__file__).resolve().parents[1]

# Where an Apple-Event consumer could live. DISCOVERED, not hardcoded: R67
# deleted divoomd/src/live_jobs/music.rs when MediaRemote replaced it, and a
# hardcoded list would have had to be edited in lockstep — a maintenance step
# nobody performs, which is the very class this file exists to gate.
SEARCH_ROOTS = (
    REPO / "divoom_lib",
    REPO / "divoom_gui",
    REPO / "divoomd" / "src",
)
SOURCE_SUFFIXES = (".py", ".rs")

# `tell application "Kaset"` / `if application "Music" is running`
TELL_RE = re.compile(r'application\s+\\?"([A-Za-z][A-Za-z0-9 .]*)\\?"')


def addressed_apps(path: Path) -> set[str]:
    """Application names this source addresses via AppleScript."""
    return set(TELL_RE.findall(path.read_text(encoding="utf-8", errors="replace")))


# What makes an Apple Event a NOW-PLAYING query rather than any other use.
# `tell application "Python" to activate` (the GUI focusing its own window) is an
# Apple Event too, and a self-targeting one needs no Automation grant — so the
# gate keys on the player idioms, not on the mere presence of `application "X"`.
PLAYER_IDIOMS = ("player state", "player info", "player position",
                 "current track", "playerState", "playerInfo")


def apple_event_consumers() -> dict[Path, set[str]]:
    """Source files that query a music player's state over Apple Events."""
    found: dict[Path, set[str]] = {}
    for root in SEARCH_ROOTS:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix not in SOURCE_SUFFIXES or "__pycache__" in str(path):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if not any(idiom in text for idiom in PLAYER_IDIOMS):
                continue
            apps = addressed_apps(path)
            if apps:
                found[path] = apps
    return found


def test_every_addressed_player_is_in_the_registry() -> None:
    """A player we send Apple Events to must be primed, or it fails in the daemon.

    An unprimed player's Apple Event is DENIED in the headless daemon (its
    consent dialog has no visible owner) while the foreground GUI still works —
    so the bug shows up only on the path to the device.
    """
    offenders = {}
    known = set(all_player_names())
    for path, apps in apple_event_consumers().items():
        missing = apps - known
        if missing:
            offenders[path.relative_to(REPO)] = sorted(missing)
    assert not offenders, (
        "these sources address applications over Apple Events that are not in "
        f"divoom_lib/utils/media_players.PLAYERS: {offenders}"
    )


def test_kaset_is_primed_while_anything_still_addresses_it() -> None:
    """The original regression: Kaset was addressed but never primed.

    R67/Phase 2 moved now-playing to MediaRemote, which needs no Apple Events at
    all — so if nothing addresses Kaset any more, priming it would raise a
    consent prompt for no reason. The assertion tracks reality either way rather
    than pinning one side of a migration.
    """
    still_addressed = any("Kaset" in apps for apps in apple_event_consumers().values())
    if still_addressed:
        assert "Kaset" in apple_event_players(), (
            "Kaset is still addressed over Apple Events, so it must be primed")
    else:
        assert "Kaset" not in apple_event_players(), (
            "nothing addresses Kaset any more — priming it would prompt the user "
            "for an Automation grant this app no longer uses")


def test_permissions_module_uses_the_registry() -> None:
    """`permissions.py` must not hold a second, hand-maintained copy."""
    from divoom_gui import permissions

    assert tuple(permissions._AUTOMATION_TARGETS) == apple_event_players(), (
        "permissions.py must derive its targets from the registry, not hardcode them"
    )


def test_registry_marks_feishin_as_not_needing_apple_events() -> None:
    """Feishin is read from its cached credentials, so priming it would raise a
    consent prompt the user does not need. The flag keeps that honest."""
    feishin = next(p for p in PLAYERS if p.app_name == "Feishin")
    assert feishin.needs_apple_events is False
    assert "Feishin" not in apple_event_players()


def test_every_player_explains_itself() -> None:
    """A consent prompt the user cannot understand is a dark pattern; each entry
    carries the reason it exists."""
    for p in PLAYERS:
        assert p.why.strip(), f"{p.app_name} has no stated reason"


def test_registry_has_no_duplicates() -> None:
    names = all_player_names()
    assert len(names) == len(set(names))
