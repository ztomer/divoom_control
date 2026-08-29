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

# Every file that addresses a music player over Apple Events. Adding a third
# implementation without adding it here is itself the C2 duplication problem;
# this list is short on purpose.
NOW_PLAYING_SOURCES = (
    REPO / "divoom_lib" / "utils" / "media_source.py",
    REPO / "divoomd" / "src" / "live_jobs" / "music.rs",
)

# `tell application "Kaset"` / `if application "Music" is running`
TELL_RE = re.compile(r'application\s+\\?"([A-Za-z][A-Za-z0-9 .]*)\\?"')


def addressed_apps(path: Path) -> set[str]:
    """Application names this source addresses via AppleScript."""
    return set(TELL_RE.findall(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("source", NOW_PLAYING_SOURCES, ids=lambda p: p.name)
def test_every_addressed_player_is_in_the_registry(source: Path) -> None:
    """A player we send Apple Events to must be primed, or it fails in the daemon."""
    assert source.exists(), f"{source} moved — update NOW_PLAYING_SOURCES"
    addressed = addressed_apps(source)
    assert addressed, f"no `application \"...\"` found in {source.name} — regex stale?"

    missing = addressed - set(all_player_names())
    assert not missing, (
        f"{source.name} addresses {sorted(missing)} but they are not in "
        "divoom_lib/utils/media_players.PLAYERS. An unprimed player's Apple "
        "Event is DENIED in the headless daemon (no visible consent owner), so "
        "it silently returns no track while the foreground GUI still works."
    )


def test_kaset_is_primed() -> None:
    """The specific regression: Kaset was addressed but never primed."""
    assert "Kaset" in apple_event_players(), (
        "Kaset needs an Automation grant and must be primed from the foreground GUI"
    )


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
