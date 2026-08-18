"""Playwright + static-analysis regression tests for the Round 6 layout
changes documented in `docs/PLANNING_ROUND5.md` §3 and §4.

What this test file covers:

1. **Monthly Best layout (Option B):** the right card is now 23% width
   (grid `1.6fr 0.6fr`), the MAC address is gone from the sync-target
   rows, and the schedule block is removed from Monthly Best.
2. **Routines sub-tab:** Settings has a new "Routines" sub-tab that
   contains the auto-sync schedule, renamed from "Hot-Channel Schedule"
   to "Auto-Sync Gallery" per user pick.
3. **Volume slider in appbar:** the new appbar volume slider exists
   with a 0-15 range and the right label format.
4. **Scoreboard channel-card:** the new Scoreboard channel-card is
   in the Control Panel with the right number inputs and Show/Hide
   buttons.

Why static-analysis + Playwright, not full behavioral tests:
- The drag behavior already has its own dedicated test file
  (`test_gui_drag_instrumented.py`).
- These tests are about *layout existence and shape*, not user
  interaction. Static analysis catches regressions at the source
  level; Playwright catches them at the rendered DOM level.
- Hardware-gated BLE interactions (volume, scoreboard) cannot be
  tested headlessly; their transport-level correctness is covered
  by the existing `test_e2e_mock_device.py` test file.
"""
import re
import sys
from pathlib import Path

import pytest
from tests.support.browser import launch as launch_browser, require_browser

REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = REPO_ROOT / "divoom_gui" / "web_ui" / "index.html"
GALLERY_CSS = REPO_ROOT / "divoom_gui" / "web_ui" / "gallery.css"
GALLERY_JS = REPO_ROOT / "divoom_gui" / "web_ui" / "gallery.js"
GUI_API_PY = REPO_ROOT / "divoom_gui" / "gui_api.py"
LIGHTING_FORWARD_PY = REPO_ROOT / "divoom_gui" / "lighting_forward.py"

def _cat(paths: list[Path]) -> str:
    """Read and concatenate multiple source files."""
    parts = []
    for p in paths:
        if p.exists():
            parts.append(p.read_text())
    return "\n".join(parts)

TEMPLATES_JS = _cat([
    REPO_ROOT / "divoom_gui" / "web_ui" / "templates_tools.js",
    REPO_ROOT / "divoom_gui" / "web_ui" / "templates_gallery.js",
    REPO_ROOT / "divoom_gui" / "web_ui" / "templates_hot_channel.js",
    REPO_ROOT / "divoom_gui" / "web_ui" / "templates_widgets.js",
    REPO_ROOT / "divoom_gui" / "web_ui" / "templates_settings.js",
    REPO_ROOT / "divoom_gui" / "web_ui" / "templates_routines.js",
    # R40 §8: device settings (clock/temp/power/display/danger) moved here.
    REPO_ROOT / "divoom_gui" / "web_ui" / "templates_device_settings.js",
])
ROUTINES_JS = REPO_ROOT / "divoom_gui" / "web_ui" / "templates_routines.js"

SETTINGS_JS = _cat([
    REPO_ROOT / "divoom_gui" / "web_ui" / "settings_hardware.js",
    REPO_ROOT / "divoom_gui" / "web_ui" / "settings_features.js",
])

APP_JS = _cat([
    REPO_ROOT / "divoom_gui" / "web_ui" / "app_globals.js",
    REPO_ROOT / "divoom_gui" / "web_ui" / "app_init.js",
])

CHANNELS_JS = _cat([
    REPO_ROOT / "divoom_gui" / "web_ui" / "channels_core.js",
    REPO_ROOT / "divoom_gui" / "web_ui" / "channels_grids.js",
])


# ──────────────────────────────────────────────────────────────────
# 1. Gallery + Hot Channel layouts
# ──────────────────────────────────────────────────────────────────


def test_gallery_has_no_device_list():
    """The Gallery panel has classify tabs + gallery grid but NO
    device list or sync-targets (those are in Routines)."""
    src = TEMPLATES_JS
    g_match = re.search(
        r'<div class="gallery-full-layout">(.*?)</div>\s*`;',
        src, re.DOTALL,
    )
    assert g_match is not None, "gallery-full-layout block not found in templates"
    block = g_match.group(1)
    assert "sync-targets-list" not in block, (
        "Gallery must not embed the sync-targets-list — it lives in Routines."
    )
    assert 'id="gallery-classify-tabs"' in block, (
        "Gallery should have classify tabs (#gallery-classify-tabs)."
    )
    assert 'id="gallery-container"' in block, (
        "Gallery should have the gallery container."
    )


def test_hot_channel_has_no_gallery_grid():
    """Hot Channel has the hot preview + update button but NO gallery
    grid or classify tabs."""
    src = TEMPLATES_JS
    hc_match = re.search(
        r'<div class="hot-channel-layout">(.*?)</div>\s*`;',
        src, re.DOTALL,
    )
    assert hc_match is not None, "hot-channel-layout block not found in templates"
    block = hc_match.group(1)
    assert 'class="gallery-grid"' not in block, (
        "Hot Channel must not have a gallery grid."
    )
    assert 'id="gallery-classify-tabs"' not in block, (
        "Hot Channel must not have gallery classify tabs."
    )
    assert 'id="hot-update-btn"' in block, (
        "Hot Channel must have the hot update button."
    )
    assert 'id="hot-preview-list"' in block, (
        "Hot Channel must have the hot preview list."
    )


def test_both_layouts_full_width():
    """Both gallery-full-layout and hot-channel-layout are single-column
    (full width, in a combined CSS rule)."""
    css = GALLERY_CSS.read_text()
    m = re.search(
        r"\.hot-channel-layout,\s*\.gallery-full-layout\s*\{[^}]*grid-template-columns:\s*([^;]+);",
        css,
    )
    assert m is not None, (
        "Combined .hot-channel-layout, .gallery-full-layout rule not found in CSS"
    )
    cols = m.group(1).strip()
    assert cols == "1fr", (
        f"Expected single-column '1fr', got {cols!r}."
    )


def test_target_row_has_no_mac_or_style_tabs():
    """The renderSyncTargets function in gallery.js creates a simple
    row (dot + name + toggle) — no MAC address and no gallery style
    chooser tabs."""
    src = GALLERY_JS.read_text()
    fn_match = re.search(r"window\.renderSyncTargets\s*=\s*function[^{]*\{(.+?)\n\s*\}", src, re.DOTALL)
    assert fn_match is not None, "renderSyncTargets not found in gallery.js"
    fn_body = fn_match.group(1)
    assert "target-addr" not in fn_body, (
        "renderSyncTargets still creates a .target-addr element — "
        "the MAC address should be removed."
    )
    assert "styleTabs" not in fn_body and 'class="tabs-row"' not in fn_body, (
        "renderSyncTargets still creates a gallery style chooser — "
        "it was removed per user request."
    )


def test_target_addr_css_class_removed():
    """The .target-addr CSS class should be gone from gallery.css — it
    was only used by the MAC-address element we removed."""
    css = GALLERY_CSS.read_text()
    # The selector should not exist (or be empty if it does).
    m = re.search(r"\.target-addr\s*\{[^}]*\}", css)
    assert m is None, (
        f".target-addr CSS class still defined in gallery.css: {m.group(0)!r}. "
        f"Remove it; the element is no longer created."
    )


# ──────────────────────────────────────────────────────────────────
# 2. Routines sub-tab in Settings
# ──────────────────────────────────────────────────────────────────



def test_routines_panel_content_exists():
    """R33: the Routines panel (own top-level panel) must exist with
    the 'Auto-Sync Gallery' card (renamed from Hot-Channel Schedule)."""
    src = ROUTINES_JS.read_text()
    assert "DivoomTemplates.routines" in src, (
        "routines template not found"
    )
    assert "Auto-Sync Gallery" in src, (
        "Routines panel should be titled 'Auto-Sync Gallery' "
        "(user picked this over 'Hot-Channel Schedule' in planning doc §8)."
    )
    # Old terminology must NOT appear.
    assert "Hot-Channel" not in src, (
        "Routines panel still mentions 'Hot-Channel' — should be "
        "renamed to 'Auto-Sync Gallery' per user pick."
    )
    # The form elements must exist.
    assert 'id="routines-auto-sync-enabled"' in src, "Missing routines-auto-sync-enabled toggle"
    assert 'id="routines-interval-tabs"' in src, "Missing routines-interval-tabs"
    assert 'id="sync-all-btn"' not in src, "sync-all-btn should be removed"
    assert 'id="sync-targets-list"' in src, "Missing sync-targets-list"


def test_settings_js_wires_routines_form():
    """settings.js must wire the routines auto-save handlers."""
    src = SETTINGS_JS
    assert "routines-auto-sync-enabled" in src, (
        "settings.js doesn't reference the routines enabled toggle."
    )
    assert "routines-interval-tabs" in src, (
        "settings.js doesn't reference the interval tabs."
    )
    assert "saveSchedule" in src, (
        "settings.js should define saveSchedule() for auto-save."
    )
    assert "loadRoutinesAutoSync" in src, (
        "settings.js should define loadRoutinesAutoSync() to load the config."
    )


def test_gallery_js_drops_schedule_handlers():
    """The schedule-related handlers (loadHotChannelSchedule + save button
    click) must be REMOVED from gallery.js — they moved to settings.js.
    We check for actual function definitions / call sites, not comments."""
    src = GALLERY_JS.read_text()
    # No actual call to the (now undefined) loadHotChannelSchedule function.
    assert not re.search(r"\b(loadHotChannelSchedule\s*\()", src), (
        "gallery.js still CALLS loadHotChannelSchedule() — this function "
        "moved to settings.js as loadRoutinesAutoSync. Remove the dead call "
        "or update it to call the new name."
    )
    # No function DEFINITION for loadHotChannelSchedule.
    assert not re.search(r"function\s+loadHotChannelSchedule\b", src), (
        "gallery.js still DEFINES loadHotChannelSchedule — it moved to settings.js."
    )
    # No reference to the old save-button id (active code path).
    assert not re.search(r"(getElementById|querySelector)\s*\(\s*[\"']hc-save-schedule-btn[\"']\s*\)", src), (
        "gallery.js still binds the old hc-save-schedule-btn click handler — "
        "it moved to settings.js."
    )


# ──────────────────────────────────────────────────────────────────
# 3. Volume slider in appbar
# ──────────────────────────────────────────────────────────────────


def test_appbar_volume_slider_exists():
    """The appbar must have a new volume slider with id
    'appbar-volume-slider' and a value display."""
    html = INDEX_HTML.read_text()
    assert 'id="appbar-volume-slider"' in html, (
        "appbar-volume-slider element not found in index.html"
    )
    assert 'id="appbar-volume-value"' in html, (
        "appbar-volume-value display not found in index.html"
    )
    # Range should be 0-15 (the protocol's actual range).
    m = re.search(
        r'<input[^>]*id="appbar-volume-slider"[^>]*>',
        html, re.DOTALL,
    )
    assert m is not None
    slider_html = m.group(0)
    assert 'min="0"' in slider_html, "Volume slider min should be 0"
    assert 'max="15"' in slider_html, (
        "Volume slider max should be 15 — the protocol's actual range "
        "(divoom.music.set_volume, 0x08). Kare: show the raw value."
    )


def test_appbar_volume_handler_in_app_js():
    """app.js must handle the volume slider's change event and call
    set_volume / get_volume on the API."""
    src = APP_JS
    assert "appbar-volume-slider" in src, (
        "app.js doesn't reference the volume slider id."
    )
    assert "set_volume" in src, (
        "app.js doesn't call window.pywebview.api.set_volume — the "
        "slider's change handler must push the value to the device."
    )
    assert "get_volume" in src, (
        "app.js doesn't call window.pywebview.api.get_volume — the "
        "slider should initialize to the device's current volume."
    )


def test_gui_api_exposes_set_volume_and_get_volume():
    """DivoomGuiAPI must have set_volume(volume: int) -> bool and
    get_volume() -> int | None methods. set_volume is a one-line forward to
    LightingApi, defined in the LightingForwardMixin (divoom_gui/
    lighting_forward.py) that DivoomGuiAPI inherits — gui_api.py itself was
    split to stay under the 500-line house limit, so check both files."""
    src = GUI_API_PY.read_text() + LIGHTING_FORWARD_PY.read_text()
    assert re.search(r"def\s+set_volume\s*\(\s*self\s*,\s*volume:\s*int\s*\)", src), (
        "Neither gui_api.py nor lighting_forward.py has set_volume(self, volume: int)."
    )
    assert re.search(r"def\s+get_volume\s*\(\s*self\s*\)", src), (
        "gui_api.py is missing get_volume(self) method."
    )


# ──────────────────────────────────────────────────────────────────
# 4. Scoreboard channel-card
# ──────────────────────────────────────────────────────────────────


def test_scoreboard_channel_card_exists():
    """The Control Panel must have a Scoreboard tab-btn with
    data-channel='scoreboard'. (R15 §1+§7: `.channel-card` → `.tab-btn`.)"""
    html = INDEX_HTML.read_text()
    assert re.search(
        r'<button class="tab-btn"[^>]*data-channel="scoreboard"',
        html,
    ), "Scoreboard tab-btn not found in index.html"


def test_scoreboard_panel_has_number_inputs_and_no_buttons():
    """The #panel-scoreboard block must have red/blue number inputs.
    Show/Hide/Enabled buttons were REMOVED in the user feedback pass
    (Round 6.1) — scoreboard should behave like the other channels:
    click the card to switch, edit a number to apply."""
    html = INDEX_HTML.read_text()
    m = re.search(
        r'<div class="channel-panel" id="panel-scoreboard">(.+?)</div>\s*</div>\s*</div>',
        html, re.DOTALL,
    )
    assert m is not None, "panel-scoreboard not found in index.html"
    block = m.group(1)
    assert 'id="scoreboard-red"' in block, "Missing scoreboard-red input"
    assert 'id="scoreboard-blue"' in block, "Missing scoreboard-blue input"
    # Show / Hide / Enabled buttons must NOT exist.
    assert 'id="scoreboard-show-btn"' not in block, (
        "scoreboard-show-btn is back in the panel — it should be removed. "
        "Scoreboard should auto-apply on number-input change, like the other channels."
    )
    assert 'id="scoreboard-hide-btn"' not in block, (
        "scoreboard-hide-btn is back in the panel — it should be removed. "
        "Setting both scores to 0 happens automatically when the user clears them."
    )
    assert 'id="scoreboard-enabled"' not in block, (
        "scoreboard-enabled checkbox is back in the panel — it should be removed. "
        "Editing any number always enables the scoreboard tool."
    )
    # Range should be 0-999 (divoom.scoreboard clamps to 999).
    red_input = re.search(r'<input[^>]*id="scoreboard-red"[^>]*>', block)
    assert red_input is not None
    assert 'min="0"' in red_input.group(0)
    assert 'max="999"' in red_input.group(0)


def test_scoreboard_now_switches_channel():
    """The channel-card click handler must ALLOW scoreboard to call
    switch_channel (Round 6.1: it was previously in the skip list along
    with ambient). The scoreboard is a tool on channel 0x06, so
    switch_channel('scoreboard') switches the device to that channel
    and the user can then edit scores."""
    src = CHANNELS_JS
    # The scoreboard-specific skip must be GONE (only ambient is skipped now).
    assert 'activeChannel === "scoreboard"' not in src, (
        "channels.js: scoreboard is still in the skip list — the user "
        "wants clicking the card to switch the device to the scoreboard "
        "channel (0x06), not skip the switch."
    )
    # Ambient must remain skipped — now alongside Text (Round 7), since each
    # has its own Apply/Push button rather than a channel switch.
    assert ('activeChannel === "ambient"' in src
            or '["ambient", "text"].includes' in src
            or '["ambient", "text", "sessions"].includes' in src), (
        "channels.js: ambient must remain in the skip list (it has its own Apply button)."
    )


def test_scoreboard_handler_in_channels_js():
    """channels.js must wire the number inputs' `change` event to call
    set_scoreboard(1, red, blue)."""
    src = CHANNELS_JS
    assert "scoreboard-red" in src, "channels.js doesn't reference scoreboard-red"
    assert "scoreboard-blue" in src, "channels.js doesn't reference scoreboard-blue"
    # The change handler must exist and call set_scoreboard.
    assert re.search(
        r"addEventListener\s*\(\s*[\"']change[\"']\s*,\s*pushScoreboard",
        src,
    ), "channels.js: scoreboard number inputs must listen to 'change' and call pushScoreboard."
    # Show/Hide handlers must be gone.
    assert "scoreboard-show-btn" not in src, (
        "channels.js still references scoreboard-show-btn — the Show button was removed."
    )
    assert "scoreboard-hide-btn" not in src, (
        "channels.js still references scoreboard-hide-btn — the Hide button was removed."
    )
    # set_scoreboard is still called (just from the change handler now).
    assert "set_scoreboard" in src, (
        "channels.js doesn't call window.pywebview.api.set_scoreboard — "
        "the change handler must push the score values to the device."
    )


def test_gui_api_exposes_set_scoreboard():
    """gui_api.py must have set_scoreboard(on_off, red=0, blue=0) -> bool."""
    src = GUI_API_PY.read_text()
    assert re.search(
        r"def\s+set_scoreboard\s*\(\s*self\s*,\s*on_off:\s*int\s*,\s*red:\s*int\s*=\s*0\s*,\s*blue:\s*int\s*=\s*0\s*\)",
        src,
    ), "gui_api.py is missing set_scoreboard(self, on_off: int, red: int = 0, blue: int = 0) method."


# ──────────────────────────────────────────────────────────────────
# 5. Battery badge — DOCUMENTED GAP (intentionally not implemented)
# ──────────────────────────────────────────────────────────────────


def test_no_battery_badge_intentionally_not_implemented():
    """The user requested a battery badge in the appbar (planning
    doc §6.1 Phase 1). We intentionally did NOT implement it because
    divoom_lib has no device-battery protocol command — the only
    related commands are 0xB2/0xB3 (low-power auto-dim, not battery
    level). This test guards against someone adding a fake
    battery badge (e.g. showing the laptop's battery) without
    first finding a real device-battery command.

    If you want a device-battery indicator, you need to:
    1. Find a protocol command (possibly in Divoom Cloud over HTTPS).
    2. Implement it in divoom_lib.
    3. Add a GUI badge in index.html + handler in app.js.
    4. Add a get_battery() method in gui_api.py.
    5. Update this test to assert the new badge exists.
    """
    html = INDEX_HTML.read_text()
    assert "battery" not in html.lower(), (
        "Found 'battery' in index.html. The Round 6 plan called for a "
        "battery badge, but divoom_lib has no device-battery protocol "
        "command. Do not add a battery badge without first finding a "
        "real source for the device's battery level."
    )
    appjs = APP_JS
    assert "battery" not in appjs.lower(), (
        "Found 'battery' in app.js. See comment in "
        "test_no_battery_badge_intentionally_not_implemented."
    )
    api = GUI_API_PY.read_text()
    assert "get_battery" not in api, (
        "Found 'get_battery' in gui_api.py. See comment in "
        "test_no_battery_badge_intentionally_not_implemented."
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
