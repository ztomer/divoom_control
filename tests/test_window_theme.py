"""DV.WINBG -- a launch in the Light theme never shows a dark frame first.

Found 2026-11-14 (30 fps capture of the installed 0.45.11, Light chosen, Dark appearance): the
window opened on 14 frames of (10, 11, 16) -- gui_main's hard-coded `background_color="#0a0b10"`
-- then one of (27, 27, 27), WKWebView's own dark backdrop, before the page's first light frame.
The native side could not do better: the choice lived only in the page's localStorage.

Now the choice is also kept in config.ini, read before the window exists: the window is created
in that theme's `--bg-base`, its NSWindow takes the choice's appearance (so WKWebView's backdrop
agrees) and a dynamic background, and the page gets the same choice in its URL.

TEETH (each watched red): put `background_color="#0a0b10"` back and the launch-colour rows go
red; drop the appearance in apply_to_window and the native light row goes red; drop `?theme=`
from the page's boot and the URL row goes red; stop reporting choices and the report row goes red.
"""

import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from divoom_gui import first_paint, gui_main, window_theme  # noqa: E402
from tests.support.browser import add_init_js, eval_js, launch, require_browser, wait_js  # noqa: E402
from tests.support.gui_main_fakes import _patch_main_common  # noqa: E402

WEB_UI = _REPO / "divoom_gui" / "web_ui"


def _bg_base(block_selector: str) -> str:
    css = (WEB_UI / "style.css").read_text()
    block = css[css.index(block_selector + " {") :]
    block = block[: block.index("}")]
    return re.search(r"--bg-base:\s*(#[0-9a-fA-F]{6})", block).group(1).lower()


def test_the_window_colours_are_the_pages_bg_base():
    css = {"dark": _bg_base(":root"), "light": _bg_base("body.theme-light")}
    assert css == window_theme.BG


def test_the_choice_round_trips_and_absent_means_the_page_decides(tmp_path):
    cfg = tmp_path / "config.ini"
    assert window_theme.read_choice(cfg) is None
    for choice in window_theme.CHOICES:
        assert window_theme.write_choice(choice, cfg)
        assert window_theme.read_choice(cfg) == choice
    assert not window_theme.write_choice("sepia", cfg)
    assert window_theme.read_choice(cfg) == "system"


@pytest.mark.parametrize(
    ("choice", "system_light", "want"),
    [
        ("light", False, "light"),
        ("dark", True, "dark"),
        ("system", True, "light"),
        ("system", False, "dark"),
        (None, True, "light"),
        (None, False, "dark"),
    ],
)
def test_the_launch_background_is_the_drawn_theme(choice, system_light, want):
    assert window_theme.launch_background(choice, lambda: system_light) == window_theme.BG[want]


def _launch(monkeypatch, tmp_path, choice, system_light):
    ctx = _patch_main_common(monkeypatch, tmp_path)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_keep_daemon_alive", lambda: True)
    monkeypatch.setattr("divoom_lib.lifecycle_config.get_quit_menubar_on_exit", lambda: True)
    monkeypatch.setattr(first_paint, "keep_painting_while_occluded", lambda w, **kw: None)
    monkeypatch.setattr(window_theme, "read_choice", lambda: choice)
    monkeypatch.setattr(window_theme, "_system_is_light", lambda: system_light)
    themed = []
    monkeypatch.setattr(window_theme, "theme_window", lambda w, c: themed.append((w, c)))
    with pytest.raises(SystemExit):
        gui_main.main()
    return ctx, themed


@pytest.mark.parametrize(("choice", "system_light"), [("light", False), ("system", True)])
def test_a_light_launch_creates_a_light_window(monkeypatch, tmp_path, choice, system_light):
    ctx, themed = _launch(monkeypatch, tmp_path, choice, system_light)
    (kwargs,) = ctx.create_window_calls
    assert kwargs["background_color"] == window_theme.BG["light"], "the window opens dark under a light page"
    assert f"theme={choice}" in kwargs["url"], "the page must draw the choice the window was created in"
    assert themed == [(ctx.window, choice)]


def test_a_dark_launch_creates_a_dark_window(monkeypatch, tmp_path):
    ctx, _ = _launch(monkeypatch, tmp_path, "dark", True)
    assert ctx.create_window_calls[0]["background_color"] == window_theme.BG["dark"]


def test_no_stored_choice_leaves_the_url_to_the_page(monkeypatch, tmp_path):
    ctx, _ = _launch(monkeypatch, tmp_path, None, False)
    assert "theme=" not in ctx.create_window_calls[0]["url"]


class _Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, fn):
        self.handlers.append(fn)
        return self


def test_the_window_is_themed_before_its_first_show():
    win = type("W", (), {})()
    win.events = type("E", (), {"before_show": _Event()})()
    applied = []
    window_theme.theme_window(
        win, "light", native_window=lambda w: "NSWINDOW", apply=lambda n, c: applied.append((n, c))
    )
    assert applied == []
    for h in win.events.before_show.handlers:
        h()
    assert applied == [("NSWINDOW", "light")]


def _resolved_rgb(nswindow):
    import AppKit

    out = []

    def read():
        c = nswindow.backgroundColor().colorUsingColorSpace_(AppKit.NSColorSpace.sRGBColorSpace())
        out.append(tuple(round(v * 255) for v in (c.redComponent(), c.greenComponent(), c.blueComponent())))

    nswindow.effectiveAppearance().performAsCurrentDrawingAppearance_(read)
    return out[0]


def _hex_rgb(h):
    return tuple(int(h[i : i + 2], 16) for i in (1, 3, 5))


@pytest.mark.skipif(sys.platform != "darwin", reason="AppKit window")
@pytest.mark.parametrize(
    ("choice", "app_appearance"), [("light", "NSAppearanceNameDarkAqua"), ("dark", "NSAppearanceNameAqua")]
)
def test_a_real_nswindow_draws_the_choice_against_the_app_appearance(choice, app_appearance):
    """The case the owner met: a light choice in a dark app (and the reverse)."""
    import AppKit

    app = AppKit.NSApplication.sharedApplication()
    before = app.appearance()
    app.setAppearance_(AppKit.NSAppearance.appearanceNamed_(app_appearance))
    try:
        win = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(((0, 0), (200, 100)), 0, 2, True)
        window_theme.apply_to_window(win, choice)
        assert _resolved_rgb(win) == _hex_rgb(window_theme.BG[choice])
        window_theme.apply_to_window(win, "system")
        follows = "dark" if app_appearance.endswith("DarkAqua") else "light"
        assert _resolved_rgb(win) == _hex_rgb(window_theme.BG[follows]), "system follows the app's appearance"
    finally:
        app.setAppearance_(before)


def test_set_theme_choice_keeps_the_choice(monkeypatch, tmp_path):
    from divoom_gui.lifecycle_mixin import LifecycleSettingsMixin

    cfg = tmp_path / "config.ini"
    write = window_theme.write_choice
    monkeypatch.setattr(window_theme, "write_choice", lambda c: write(c, cfg))
    api = LifecycleSettingsMixin()
    assert api.set_theme_choice("light") is True
    assert window_theme.read_choice(cfg) == "light"
    assert api.set_theme_choice("sepia") is False


# ── the page: `?theme=` wins, and every choice reaches the app ──

_RECORDING_API = """
window.__themeCalls = [];
window.pywebview = { api: new Proxy({}, { get: (_t, name) => (...args) => {
    if (name === 'set_theme_choice') window.__themeCalls.push(args[0]);
    return Promise.resolve(String(name).startsWith('get_') ? '{}' : true); } })};
"""


async def _open(p, scheme, query="", storage=None):
    browser = await launch(p)
    page = await browser.new_page(viewport={"width": 1280, "height": 900}, color_scheme=scheme)
    seed = "".join(f"localStorage.setItem({k!r}, {v!r});" for k, v in (storage or {}).items())
    await add_init_js(page, _RECORDING_API + f"\ntry {{ {seed} }} catch (e) {{}}\n")
    await page.goto(f"file://{WEB_UI / 'index.html'}{query}")
    await wait_js(page, "() => !!window.DivoomTheme && !!window.DivoomState")
    return browser, page


@pytest.mark.asyncio
async def test_the_apps_choice_in_the_url_wins_over_the_page_store():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, "dark", "?theme=light", {"divoom-theme": "dark"})
        try:
            assert await eval_js(page, "() => document.body.classList.contains('theme-light')")
            assert await eval_js(page, "() => localStorage.getItem('divoom-theme')") == "light"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_the_page_reports_its_choice_to_the_app():
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser, page = await _open(p, "dark", "", {"divoom-theme": "light"})
        try:
            # A boot with no `?theme=` (an app that never kept one) hands its stored choice over.
            assert await eval_js(page, "() => window.__themeCalls") == ["light"]
            await eval_js(page, "() => window.DivoomTheme.choose('dark')")
            assert await eval_js(page, "() => window.__themeCalls") == ["light", "dark"]
        finally:
            await browser.close()
