"""Up-front macOS permission priming.

Some features touch TCC-gated resources lazily. The worst offender: the album-art
live widget controls Music/Spotify via AppleScript (Apple Events / "Automation"),
and that osascript runs inside the HEADLESS daemon — so the consent dialog had no
visible owner and the user never saw it, the Apple Event was denied, and the
widget silently got no track (the device channel never changed, while the GUI
preview rendered a local placeholder).

Fix: trigger the prompts at GUI startup, from the FOREGROUND app, so they're
visible and granted once up front. The grant is attributed to the responsible
bundle (Divoom.app), which the daemon it spawns inherits — so the daemon's later
osascript calls just work.

Bluetooth is already primed by the daemon's first scan (its prompt is declared in
the Info.plist and surfaces because the GUI is foreground), so it isn't repeated
here.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import threading

logger = logging.getLogger("divoom_gui.permissions")

# AppleScript-controllable players the cover-art widget queries.
#
# R67/C3: this was a hardcoded ("Music", "Spotify") while the now-playing code
# also addressed Kaset — so Kaset was never primed, its Apple Event was denied
# in the headless daemon, and the daemon got no track even though the foreground
# GUI (which prompts visibly) could see one. The list now comes from the single
# registry every consumer reads; tests/test_media_player_registry.py fails if
# they ever diverge again.
from divoom_lib.utils.media_players import apple_event_players

_AUTOMATION_TARGETS = apple_event_players()


def _prime_automation() -> None:
    for app in _AUTOMATION_TARGETS:
        # Only poke a target that's already running, so we never LAUNCH Music or
        # Spotify just to ask. `... is running` doesn't send an Apple Event; the
        # `tell ... to get player state` does — that's what raises the Automation
        # prompt (now owned by the foreground GUI, so it's visible).
        script = (
            f'if application "{app}" is running then\n'
            f'    tell application "{app}" to get player state\n'
            f'end if'
        )
        try:
            subprocess.run(["osascript", "-e", script],
                           capture_output=True, timeout=5)
            logger.debug("primed Automation for %s", app)
        except Exception as e:
            logger.debug("automation prime for %s failed: %s", app, e)


def prime_permissions() -> None:
    """Trigger the app's TCC prompts up front (macOS only). Best-effort and
    threaded, so it never blocks GUI launch."""
    if sys.platform != "darwin":
        return
    threading.Thread(target=_prime_automation, name="perm-prime",
                     daemon=True).start()
