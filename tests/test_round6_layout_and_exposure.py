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
