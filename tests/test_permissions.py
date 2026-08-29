"""Up-front macOS permission priming."""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / "divoom_gui"))

from divoom_gui import permissions


def test_prime_automation_pokes_exactly_the_registry_targets(monkeypatch):
    """Priming must cover the registry, and nothing else.

    R67/C3: this used to assert the literal ("Music", "Spotify") while the
    now-playing code also addressed Kaset — the drift that left Kaset's Apple
    Event denied in the headless daemon. Asserting against the registry instead
    of a hardcoded pair is what makes the two impossible to separate.
    """
    from divoom_lib.utils.media_players import apple_event_players

    calls = []
    monkeypatch.setattr(permissions.subprocess, "run",
                        lambda *a, **k: calls.append(a[0]))
    permissions._prime_automation()
    joined = " ".join(" ".join(c) for c in calls)

    for app in apple_event_players():
        assert app in joined, f"{app} is in the registry but was not primed"
    assert len(calls) == len(apple_event_players()), (
        "priming an app that is not in the registry asks the user to consent "
        "to something this app does not use")
    # osascript only, and never LAUNCHES a player (guarded by `is running`).
    assert all(c[0] == "osascript" for c in calls)
    if calls:
        assert "is running" in joined


def test_nothing_needs_an_automation_grant_now(monkeypatch):
    """R67/Phase 2: now-playing moved to MediaRemote, which needs no Apple Events.

    This is the user-visible win — the app stops asking for Automation access to
    music players entirely. If a future player has to be driven over AppleScript
    this test is the one that should change, deliberately, alongside the
    registry entry that primes it.
    """
    from divoom_lib.utils.media_players import apple_event_players

    assert apple_event_players() == (), (
        "a player needs an Automation grant again — make sure it is primed and "
        "that the user is told why")

    started = []
    monkeypatch.setattr(permissions.sys, "platform", "darwin")
    monkeypatch.setattr(permissions.threading, "Thread",
                        lambda *a, **k: started.append(1) or type("T", (), {"start": lambda self: None})())
    permissions.prime_permissions()
    assert not started, "no prompt thread should start when there is nothing to prime"


def test_prime_automation_swallows_errors(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("osascript missing")
    monkeypatch.setattr(permissions.subprocess, "run", _boom)
    permissions._prime_automation()   # must not raise


def test_prime_permissions_noop_off_darwin(monkeypatch):
    monkeypatch.setattr(permissions.sys, "platform", "linux")
    started = []
    monkeypatch.setattr(permissions.threading, "Thread",
                        lambda *a, **k: started.append(1) or type("T", (), {"start": lambda self: None})())
    permissions.prime_permissions()
    assert started == []   # no priming thread off macOS
