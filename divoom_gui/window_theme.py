"""The window is in the page's theme before the page paints (DV.WINBG).

Between the window's first show and the page's first paint (the stylesheets, Google Fonts
among them, block it) the owner sees what the NATIVE side draws: the NSWindow's background
and WKWebView's default backdrop. Until 0.45.11 the window background was a hard-coded dark
`#0a0b10` and the web view's backdrop followed the system appearance, so a launch in the
Light theme opened on a dark frame for ~0.5 s (measured 2026-11-14: 14 frames of
(10, 11, 16) then one of (27, 27, 27) before the first light frame, 30 fps capture of the
installed 0.45.11 under the Dark appearance).

The theme choice used to live only in the page's localStorage, which the native side
cannot read before the page runs. So the choice is ALSO kept in
`~/.config/divoom-control/config.ini` `[gui] theme`, which the page writes through
`set_theme_choice` whenever it chooses, and which gui_main reads before the window exists:

* the page is told the choice in its URL (`theme=`), so page and window draw one choice;
* the NSWindow's appearance is the choice (Aqua / DarkAqua; none for "system"), so
  WKWebView's own backdrop is in the same theme;
* the NSWindow's background is a dynamic colour: `BG[theme]` for whichever theme its
  appearance resolves to, so "system" follows the appearance live with no code.

`BG` is the page's `--bg-base` per theme (style.css; tests/test_window_theme.py pins it).
"""

from __future__ import annotations

import configparser
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_FILE = Path.home() / ".config" / "divoom-control" / "config.ini"
SECTION = "gui"
KEY = "theme"
CHOICES = ("dark", "light", "system")

# style.css `--bg-base` for `:root` (dark) and `body.theme-light`.
BG = {"dark": "#121316", "light": "#f4f4f6"}

_AQUA = "NSAppearanceNameAqua"
_DARK_AQUA = "NSAppearanceNameDarkAqua"


def read_choice(path: Path = CONFIG_FILE) -> str | None:
    """The stored choice, or None when none was ever stored (the page's own store then
    decides, and reports it back). Never raises."""
    try:
        if path.exists():
            cfg = configparser.ConfigParser()
            cfg.read(path)
            value = cfg.get(SECTION, KEY, fallback=None)
            if value in CHOICES:
                return value
    except (configparser.Error, OSError) as e:
        logger.warning("theme read failed (%s); the page decides", e)
    return None


def write_choice(choice: str, path: Path = CONFIG_FILE) -> bool:
    """Persist the choice. Returns True on success; an unknown choice is refused."""
    if choice not in CHOICES:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        cfg = configparser.ConfigParser()
        if path.exists():
            cfg.read(path)
        if not cfg.has_section(SECTION):
            cfg.add_section(SECTION)
        cfg.set(SECTION, KEY, choice)
        from divoom_lib.utils.atomic_io import atomic_write_config

        atomic_write_config(path, cfg)
        return True
    except (configparser.Error, OSError) as e:
        logger.warning("theme write failed (%s)", e)
        return False


def appearance_name(choice: str | None) -> str | None:
    """The NSAppearance name the window takes for a choice; None follows the app's."""
    return {"light": _AQUA, "dark": _DARK_AQUA}.get(choice or "system")


def drawn(choice: str | None, system_is_light: bool) -> str:
    """The theme drawn for a choice, as theme_boot.js resolves it."""
    if choice in ("dark", "light"):
        return choice
    return "light" if system_is_light else "dark"


def _system_is_light() -> bool:
    try:
        import AppKit

        style = AppKit.NSUserDefaults.standardUserDefaults().stringForKey_("AppleInterfaceStyle")
        return style != "Dark"
    except ImportError:
        return False


def launch_background(choice: str | None, system_is_light: Callable[[], bool] | None = None) -> str:
    """The static background colour to create the window with (hex)."""
    return BG[drawn(choice, (system_is_light or _system_is_light)())]


def _nscolor(hexcolor: str) -> Any:
    import AppKit

    h = hexcolor.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    return AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, 1.0)


def dynamic_background() -> Any:
    """An NSColor that is BG['light'] under a light appearance and BG['dark'] otherwise."""
    import AppKit

    light, dark = _nscolor(BG["light"]), _nscolor(BG["dark"])

    def provide(appearance: Any) -> Any:
        best = appearance.bestMatchFromAppearancesWithNames_([_AQUA, _DARK_AQUA])
        return light if best == _AQUA else dark

    return AppKit.NSColor.colorWithName_dynamicProvider_("DivoomWindowBackground", provide)


def apply_to_window(nswindow: Any, choice: str | None) -> None:
    """Put an NSWindow in the choice's theme: its appearance and its background. Main thread."""
    import AppKit

    name = appearance_name(choice)
    nswindow.setAppearance_(None if name is None else AppKit.NSAppearance.appearanceNamed_(name))
    nswindow.setBackgroundColor_(dynamic_background())


def _cocoa_window(window: Any) -> Any:
    from divoom_gui.first_paint import _cocoa_window as native

    return native(window)


def theme_window(
    window: Any,
    choice: str | None,
    *,
    native_window: Callable[[Any], Any] = _cocoa_window,
    apply: Callable[[Any, str | None], None] = apply_to_window,
) -> None:
    """Wire a pywebview window so it is in `choice`'s theme from its first show.
    Call before `webview.start()`; pywebview runs before_show on the main thread before
    the window is ordered in."""

    def _before_show() -> None:
        nswindow = native_window(window)
        if nswindow is None:
            logger.warning("window theme: no NSWindow; the window keeps its launch background")
            return
        apply(nswindow, choice)

    window.events.before_show += _before_show
