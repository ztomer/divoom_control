"""Round6 layout & exposure checks — later rounds (r9/r10/r11/r18/r33/
r15/r12/r40), browser render and custom-art coverage. Split from
test_round6_layout_and_exposure.py."""
import re
import sys
from pathlib import Path

import pytest

from tests.support.browser import launch as launch_browser, require_browser
from tests.support.round6_webui import (
    APP_JS,
    CHANNELS_JS,
    GALLERY_CSS,
    GALLERY_JS,
    GUI_API_PY,
    INDEX_HTML,
    LIGHTING_FORWARD_PY,
    REPO_ROOT,
    ROUTINES_JS,
    SETTINGS_JS,
    TEMPLATES_JS,
)


# ──────────────────────────────────────────────────────────────────
# 5b. Round 9 — Display card (orientation / mirror / factory reset)
# ──────────────────────────────────────────────────────────────────


def test_r9_display_card_exists():
    """Orientation/mirror/factory-reset live in the R40 §8 Device Settings
    section (one glass pane with a Danger zone block at the bottom)."""
    src = TEMPLATES_JS
    assert 'id="screen-dir-tabs"' in src, "Display controls missing orientation tabs."
    assert 'id="screen-mirror-toggle"' in src, "Display controls missing mirror toggle."
    assert 'id="factory-reset-btn"' in src, "factory-reset-btn is missing from the DOM."
    # R40 §8: factory reset is in a danger-card block at the bottom of the pane.
    assert re.search(
        r'class="danger-card"[\s\S]*?id="factory-reset-btn"',
        src,
    ), "factory-reset-btn is not inside the Danger zone block."


def test_r9_settings_js_wires_display_and_guards_reset():
    """settings.js wires orientation/mirror and double-confirms factory reset."""
    src = SETTINGS_JS
    assert "set_screen_dir" in src, "settings.js does not call set_screen_dir."
    assert "set_screen_mirror" in src, "settings.js does not call set_screen_mirror."
    # Factory reset must be confirmed (dialog + typed RESET token) before calling.
    assert "factory_reset" in src, "settings.js does not call factory_reset."
    assert 'factory_reset?.("RESET")' in src, (
        "factory_reset must be called with the literal 'RESET' token."
    )
    assert "window.prompt" in src and "RESET" in src, (
        "Factory reset must require a typed RESET confirmation."
    )


def test_r9_gui_api_exposes_display_bridges():
    """gui_api.py has set_screen_dir / set_screen_mirror / token-gated
    factory_reset; brightness stays the existing LAN/multi-target bridge."""
    src = GUI_API_PY.read_text()
    assert re.search(r"def\s+set_screen_dir\s*\(", src), "missing set_screen_dir bridge."
    assert re.search(r"def\s+set_screen_mirror\s*\(", src), "missing set_screen_mirror bridge."
    assert re.search(r"def\s+factory_reset\s*\(", src), "missing factory_reset bridge."
    assert 'str(confirm) != "RESET"' in src, (
        "factory_reset must refuse unless the caller passes the 'RESET' token."
    )


# ──────────────────────────────────────────────────────────────────
# 5c. Round 10 — Notification mirroring (ANCS) card
# ──────────────────────────────────────────────────────────────────


def test_r10_notification_card_in_tools_device():
    """Tools→Device has a Notification card with app select, text, Send."""
    src = TEMPLATES_JS
    assert 'id="notif-app-select"' in src, "Notification card missing app <select>."
    assert 'id="notif-text"' in src, "Notification card missing text input."
    assert 'id="notif-send"' in src, "Notification card missing Send button."


def test_r10_settings_js_wires_notification():
    src = SETTINGS_JS
    assert "send_notification" in src, "settings.js does not call send_notification."


def test_r10_gui_api_and_lib_expose_notification():
    api = GUI_API_PY.read_text()
    assert re.search(r"def\s+send_notification\s*\(", api), "missing send_notification bridge."
    # range guard present
    assert "1 <= t <= 14" in api, "send_notification must guard app_type 1-14."
    # command id registered
    from pathlib import Path as _P
    cmds = (REPO_ROOT / "divoom_lib" / "models" / "commands.py").read_text()
    assert '"set android ancs": 0x50' in cmds, "0x50 ANCS command not registered."


# ──────────────────────────────────────────────────────────────────
# 5d. Round 11 Phase 2 — quick GUI wins
# ──────────────────────────────────────────────────────────────────

CHANNELS_CSS = REPO_ROOT / "divoom_gui" / "web_ui" / "channels.css"
CUSTOM_ART_CSS = REPO_ROOT / "divoom_gui" / "web_ui" / "custom_art.css"


def _channels_css() -> str:
    """channels.css + custom_art.css (the custom-art block was split out
    under the 500-LOC rule but is part of the same channel chrome)."""
    return CHANNELS_CSS.read_text() + CUSTOM_ART_CSS.read_text()


def test_r11_ambient_color_controls_gated_and_no_custom_label():
    """Ambient color controls have an id to gate (3a) and the bare 'Custom'
    label is gone (3b)."""
    html = INDEX_HTML.read_text()
    amb = re.search(r'id="panel-ambient">(.+?)<!-- Round 6 — Scoreboard', html, re.DOTALL)
    assert amb is not None, "ambient panel not found"
    block = amb.group(1)
    assert 'id="ambient-color-controls"' in block, "color controls need an id to gate by mode"
    assert "Custom</span>" not in block, "the 'Custom' label should be removed"
    js = CHANNELS_JS
    assert "updateAmbientColorVisibility" in js, "channels.js must gate color controls by mode"


def test_r11_scoreboard_reset_button():
    html = INDEX_HTML.read_text()
    assert 'id="scoreboard-reset-btn"' in html, "scoreboard Reset button missing"
    js = CHANNELS_JS
    assert "scoreboard-reset-btn" in js, "Reset button not wired in channels.js"


def test_r11_custom_art_push_is_pinned_footer():
    """The Custom Art panel is a flex column with a fixed header (tabs+slots)
    and a scrolling library, so the Push button stays pinned at the bottom."""
    css = _channels_css()
    assert re.search(r"#panel-design\.active\s*\{[^}]*flex-direction:\s*column", css), (
        "#panel-design.active must be a flex column so the push button pins"
    )
    assert re.search(r"#push-custom-art-btn\s*\{[^}]*flex-shrink:\s*0", css), (
        "#push-custom-art-btn must not shrink (pinned footer)"
    )
    assert re.search(r"\.custom-art-fixed\s*\{[^}]*flex-shrink:\s*0", css), (
        "tabs+slots header must stay fixed while the library scrolls"
    )


# R39+: custom art lives in the Pixel Art section template (injected), not in
# static index.html. These structure checks read that template.
PIXEL_ART_JS = (REPO_ROOT / "divoom_gui" / "web_ui" / "templates_pixel_art.js").read_text()


def test_r37_custom_art_page_tabs_in_html():
    assert 'id="custom-art-page-tabs"' in PIXEL_ART_JS, "Page tabs container missing"
    tabs = re.findall(r'class="page-tab glow-btn compact"', PIXEL_ART_JS)
    assert len(tabs) == 3, f"Expected 3 .page-tab elements, got {len(tabs)}"


def test_r37_custom_art_slot_grid_in_html():
    assert 'id="custom-art-slot-grid"' in PIXEL_ART_JS, "Slot grid container missing"


def test_r37_custom_art_push_button_id_in_html():
    assert 'id="push-custom-art-btn"' in PIXEL_ART_JS, "#push-custom-art-btn missing"


def test_r37_custom_art_js_loaded():
    html = INDEX_HTML.read_text()
    assert 'src="custom_art.js"' in html, "custom_art.js not loaded in index.html"


def test_r37_custom_art_page_tab_css():
    css = _channels_css()
    assert ".page-tab.active" in css, ".page-tab.active rule missing in channels.css"


def test_r37_custom_art_slot_grid_css():
    css = _channels_css()
    assert ".custom-art-slot:hover" in css, ".custom-art-slot:hover rule missing in channels.css"


APPBAR_CSS = REPO_ROOT / "divoom_gui" / "web_ui" / "appbar.css"


def test_r11_appbar_phase3():
    """Phase 3: sliders pushed right via a leading spacer (4c), unified value
    font (4a), brightness-mapped thumb (4e), and the slider drag-fix (4d).
    R32: the bottom-right corner transport indicator (4b) was removed."""
    html = INDEX_HTML.read_text()
    # R32: the corner connectivity indicator pill is gone.
    assert 'class="appbar-transports corner-transports"' not in html
    assert 'corner-transports' not in html, "the corner indicator markup should be removed (R32)"
    # 4c: a drag-spacer appears before the brightness blocks (pushes sliders right)
    header = re.search(r'<header class="integrated-appbar.+?</header>', html, re.DOTALL).group(0)
    assert header.index("appbar-drag-spacer") < header.index("appbar-brightness")

    css = APPBAR_CSS.read_text()
    assert "#appbar-volume-value" in css, "4a: volume value must share the value type rule"
    assert ".corner-transports" not in css, "corner indicator styles should be removed (R32)"
    assert "--thumb-color" in css, "4e: brightness thumb tracks value"

    app_js = APP_JS
    assert "updateBrightnessThumb" in app_js, "4e: thumb color updated from value"
    assert "stopPropagation" in app_js and "appbar-slider" in app_js, "4d slider drag-fix"


def test_r11_scoreboard_restyle_blue_over_red():
    """Phase 4 (5b): scoreboard is a stacked display with BLUE above RED."""
    html = INDEX_HTML.read_text()
    m = re.search(r'<div class="scoreboard-display">(.+?)</div>\s*<button', html, re.DOTALL)
    assert m is not None, "scoreboard-display wrapper missing"
    block = m.group(1)
    assert block.index("scoreboard-row blue") < block.index("scoreboard-row red"), \
        "BLUE row must come before RED"
    assert 'id="scoreboard-blue"' in block and 'id="scoreboard-red"' in block
    css = _channels_css()
    assert ".scoreboard-score" in css and ".scoreboard-row" in css


def test_r11_wall_toolbar_unified():
    """Phase 5 (item 6): single wall toolbar, icons+labels, editable preset name,
    no 'Canvas'/'Layout & Presets' headings."""
    html = INDEX_HTML.read_text()
    wall = re.search(r'id="display-wall".+?id="arranger-canvas"', html, re.DOTALL).group(0)
    assert "wall-toolbar" in wall
    assert 'id="preset-name-input"' in wall, "editable preset name field missing"
    for ctrl in ('id="add-arranger-screen-btn"', 'id="clear-arranger-btn"',
                 'id="save-preset-btn"', 'id="presets-select"'):
        assert ctrl in wall, f"{ctrl} missing from unified toolbar"
    assert ">Canvas<" not in wall, "'Canvas' heading should be gone"
    assert "Layout &amp; Presets" not in wall, "'Layout & Presets' heading should be gone"
    assert "save-preset-btn" in APP_JS


def test_r18_subtabs_have_icons_and_fit_content():
    """R18 a/b + R33: Settings sub-tab buttons carry a .tab-icon (consistency
    with the channel row), Routines sub-tabs also carry icons, and the pill row
    sizes to its content rather than the full window width."""
    src = TEMPLATES_JS
    for did in ("settings-devices",
                "settings-divoom", "settings-connectivity",
                "settings-appearance"):
        m = re.search(rf'data-(?:tools|settings)-tab="{did}"[^>]*>(.*?)</button>', src, re.DOTALL)
        assert m and "tab-icon" in m.group(1), f"{did} tab button is missing a .tab-icon"
    # R33: Routines sub-tab icons live in the routines template.
    routines = ROUTINES_JS.read_text()
    for did in ("routines-schedule", "routines-time"):
        m = re.search(rf'data-routines-tab="{did}"[^>]*>(.*?)</button>', routines, re.DOTALL)
        assert m and "tab-icon" in m.group(1), f"{did} tab button is missing a .tab-icon"
    tabs_css = (REPO_ROOT / "divoom_gui" / "web_ui" / "tabs.css").read_text()
    assert "fit-content" in tabs_css, ".tabs-row should size to content (item b)"
    settings_css = (REPO_ROOT / "divoom_gui" / "web_ui" / "settings.css").read_text()
    assert re.search(r"\.theme-buttons\s*\{[^}]*inline-flex", settings_css), \
        "theme selector should size to content (item b)"


# ──────────────────────────────────────────────────────────────────
# 6. Playwright integration smoke (sanity check, optional)
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gallery_and_hot_channel_layouts_render_cleanly():
    """Smoke test: load index.html in headless Chromium, click the Gallery
    and Hot Channel tabs, and assert the right layout elements exist."""
    require_browser()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await launch_browser(p)
        page = await browser.new_page()
        await page.goto(f"file://{INDEX_HTML}")
        await page.wait_for_load_state("domcontentloaded")

        # R39+: Gallery + Hot Channel are sub-tabs of the Pixel Art section.
        await page.click('.nav-btn[data-tab="pixel-art"]', timeout=2000)
        await page.wait_for_selector("#pixel-art.active", timeout=2000)

        # ── Gallery sub-tab ──
        await page.click('[data-pixel-tab="pixel-gallery"]', timeout=2000)
        await page.wait_for_selector("#pixel-gallery.active", timeout=2000)
        assert await page.locator("#gallery-classify-tabs").count() == 1, (
            "Gallery sub-tab should have classify tabs."
        )
        assert await page.locator("#gallery-container").count() == 1, (
            "Gallery sub-tab should have the gallery container."
        )

        # ── Hot Channel sub-tab ──
        await page.click('[data-pixel-tab="pixel-hot-channel"]', timeout=2000)
        await page.wait_for_selector("#pixel-hot-channel.active", timeout=2000)
        assert await page.locator("#hot-update-btn").count() == 1, (
            "Hot Channel sub-tab should have the update button."
        )
        assert await page.locator("#hot-preview-list").count() == 1, (
            "Hot Channel sub-tab should have the preview list."
        )

        # The appbar volume slider must still exist.
        assert await page.locator("#appbar-volume-slider").count() == 1, (
            "appbar-volume-slider not found in the rendered DOM"
        )
        # And the Control Panel must have the Scoreboard tab.
        await page.click('[data-tab="control-panel"]', timeout=2000)
        await page.wait_for_selector("#control-panel.active", timeout=2000)
        assert await page.locator(
            '.tab-btn[data-channel="scoreboard"]'
        ).count() == 1, "Scoreboard tab-btn not found in Control Panel"

        await browser.close()


# ──────────────────────────────────────────────────────────────────
# 5e. Round 12 §A Phase 7 — tools regroup + unified segmented-pill
# ──────────────────────────────────────────────────────────────────

SETTINGS_CSS = REPO_ROOT / "divoom_gui" / "web_ui" / "settings.css"


def test_r33_tools_content_moved_to_channels_and_routines():
    """R33: the old Tools tab content is split — Sessions moved to Channels
    (as a channel tab), Time moved to Routines (as a sub-tab)."""
    # Sessions tab button exists in Channels (index.html, inline).
    idx = INDEX_HTML.read_text()
    assert re.search(
        r'<button[^>]*data-tab="sessions"[^>]*>'
        r'(?:\s*<svg.*?</svg>)?\s*<span>\s*Sessions\s*</span>\s*</button>',
        idx, re.DOTALL,
    ), "Sessions channel tab missing from index.html."
    assert 'id="panel-sessions"' in idx, "Sessions panel missing from index.html."
    # Time sub-tab exists in Routines.
    routines = ROUTINES_JS.read_text()
    assert re.search(
        r'<button[^>]*data-routines-tab="routines-time"[^>]*>'
        r'(?:\s*<svg.*?</svg>)?\s*Time\s*</button>',
        routines, re.DOTALL,
    ), "Routines Time sub-tab is missing — it should contain Alarms + Anniversary."
    # Old Tools tab no longer navigable (no sidebar button).
    assert 'data-tab="tools"' not in idx.split('<!-- R33')[0], (
        "Tools nav button still in sidebar."
    )

def test_r15_unified_segmented_pill_css():
    """R15 §1+§7: tab chrome lives in `tabs.css` as the single source of
    truth (`.tabs-row` + `.tab-btn`), shared across Channels / Tools /
    Settings / Theme. `settings.css` keeps the legacy class names as
    aliases so older markup (or external themes) still render."""
    repo_root = Path(__file__).parent.parent
    tabs_css = (repo_root / "divoom_gui" / "web_ui" / "tabs.css").read_text()
    settings_css = SETTINGS_CSS.read_text()

    # tabs.css defines the unified `.tabs-row` and `.tab-btn` rules.
    assert re.search(r"\.tabs-row\s*\{", tabs_css), (
        "tabs.css is missing the .tabs-row wrapper rule."
    )
    assert re.search(r"\.tabs-row\s+\.tab-btn\s*\{", tabs_css), (
        "tabs.css is missing the .tabs-row .tab-btn rule."
    )
    assert re.search(r"\.tabs-row\s+\.tab-btn\.active\s*\{", tabs_css), (
        "tabs.css is missing the .tabs-row .tab-btn.active rule."
    )

    # settings.css still aliases the legacy class names so old markup
    # (theme buttons, etc.) keeps rendering — no functional regression.
    assert re.search(
        r"\.settings-tab-btn\s*,\s*\n\s*\.tools-subtab-btn\s*,\s*\n\s*\.theme-mode-btn\s*\{",
        settings_css,
    ), (
        "settings.css should still group the legacy class names "
        "(.settings-tab-btn, .tools-subtab-btn, .theme-mode-btn) so "
        "older markup keeps rendering."
    )
    assert re.search(
        r"\.settings-tab-content\s*,\s*\n\s*\.tools-subtab-content\s*,\s*\n\s*\.routines-subtab-content\s*\{",
        settings_css,
    ), (
        "settings.css should group .settings-tab-content, "
        ".tools-subtab-content, and .routines-subtab-content "
        "in a single shared visibility rule."
    )


def test_r33_anniversary_moved_into_routines_time():
    """R33: the Anniversary/Memorial card moved to the Routines → Time sub-tab."""
    routines = ROUTINES_JS.read_text()
    assert 'id="routines-time"' in routines, "Routines Time sub-tab not found"
    assert 'id="memorial-save"' in routines, (
        "Anniversary/Memorial card (memorial-save button) is missing from the Routines Time sub-tab."
    )
    # Anniversary MUST NOT be in the Sessions panel (in index.html channels).
    idx = INDEX_HTML.read_text()
    assert 'id="panel-sessions"' in idx, "Sessions panel not found"
    assert 'id="memorial-save"' not in idx.split('id="panel-sessions"')[1].split('</div>\n                            </div>\n                        </div>')[0], (
        "Anniversary/Memorial must not be in the Sessions panel."
    )


def test_r12_weather_moved_into_live_widgets():
    """The Weather card now lives in Live Widgets, not in the Tools tab.
    R15 §3: the card uses the 128x128 preview (#weather-device-preview)
    — the old push-weather-btn was removed and replaced with an
    auto-push on card selection."""
    src = TEMPLATES_JS
    # Live Widgets template block: inside window.DivoomTemplates.widgets assignment.
    lw = re.search(r"window\.DivoomTemplates\.widgets\s*=\s*`(.+?)`;", src, re.DOTALL)
    assert lw is not None, "Live Widgets (widgets:) block not found in templates.js"
    lw_block = lw.group(1)
    assert 'id="widget-card-weather"' in lw_block, (
        "Weather card (widget-card-weather) is missing from Live Widgets."
    )
    assert 'id="weather-device-preview"' in lw_block, (
        "Weather preview box (#weather-device-preview) is missing from Live Widgets."
    )
    # The old push-weather-btn is GONE.
    assert 'id="push-weather-btn"' not in lw_block, (
        "Old push-weather-btn is still in Live Widgets — should be removed in R15 §3."
    )
    # Weather MUST NOT still be in the Tools tab.
    tools = re.search(r"window\.DivoomTemplates\.tools\s*=\s*`(.+?)`;", src, re.DOTALL)
    assert tools is not None, "Tools tab block not found in templates.js"
    tools_block = tools.group(1)
    assert 'id="push-weather-btn"' not in tools_block, (
        "Weather card is still in the Tools tab — should have moved to Live Widgets."
    )


def test_r40_device_settings_section_one_pane_with_segmented_pills():
    """R40 §8: clock/temp/power/name/auto-off/orientation/mirror/update-time
    live in the dedicated Device Settings section (deviceSettings template),
    in ONE glass pane, with the clock/temp/power controls as segmented pills
    (not toggles), and the Danger zone block at the bottom."""
    src = re.search(
        r"window\.DivoomTemplates\.deviceSettings\s*=\s*`(.+?)`;",
        TEMPLATES_JS, re.DOTALL,
    )
    assert src is not None, "deviceSettings template not found"
    block = src.group(1)
    # Exactly one glass card pane.
    assert block.count("card glass-card") == 1, "Device Settings must be one glass pane."
    # Segmented pills (not the old checkbox toggles).
    for seg in ["hour24-seg", "tempf-seg", "lowpower-seg"]:
        assert f'id="{seg}"' in block, f"missing segmented pill {seg}"
    for old in ["hour24-toggle", "tempf-toggle", "lowpower-toggle"]:
        assert f'id="{old}"' not in block, f"old toggle {old} should be a segmented pill now"
    # Other controls preserved, plus the renamed update-time button.
    for _id in ["device-name-input", "auto-off-min", "screen-dir-tabs",
                "screen-mirror-toggle", "sync-time-btn", "factory-reset-btn"]:
        assert f'id="{_id}"' in block, f"Device Settings missing {_id}"
    assert "Update device time" in block, "sync button must read 'Update device time'"
    # Danger zone is the last block.
    assert block.rfind("danger-card") > block.rfind('id="screen-mirror-toggle"'), \
        "Danger zone must come at the bottom of the pane"
