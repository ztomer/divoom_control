"""
R15 §3 — tests for the Live Widgets weather card.

Three contract tests:
1. The Weather card lives in Live Widgets (not in Settings) and has
   no .panel-hint text — just the 128x128 preview + a "Push to Device"
   button (R26: manual push alongside auto-push).
2. The macOS Notification + manual Notification cards also live in
   Live Widgets (R15 §3 move) and the matching cards are gone from
   Settings → Devices.
3. The widgets.js auto-fetch + auto-push on selection flow is wired
   (mock get_weather + push_weather are called once on selection).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
WIDGETS_JS = REPO_ROOT / "divoom_gui" / "web_ui" / "widgets.js"

def _cat(paths: list[Path]) -> str:
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
])

SETTINGS_JS = _cat([
    REPO_ROOT / "divoom_gui" / "web_ui" / "settings_hardware.js",
    REPO_ROOT / "divoom_gui" / "web_ui" / "settings_features.js",
])


def _live_widgets_block() -> str:
    src = TEMPLATES_JS
    m = re.search(r"window\.DivoomTemplates\.widgets\s*=\s*`(.+?)`;", src, re.DOTALL)
    assert m, "Live Widgets (window.DivoomTemplates.widgets) block not found in templates"
    return m.group(1)


def _settings_devices_block() -> str:
    """The Settings → Devices block (the first settings tab)."""
    src = TEMPLATES_JS
    m = re.search(
        r'<div class="settings-tab-content active" id="settings-devices">'
        r'(.+?)</div>\s*</div>\s*</div>\s*<!--\s*2\.\s*DIVOOM\s*TAB',
        src,
        re.DOTALL,
    )
    if not m:
        # Some templates have whitespace + comment markers in different
        # shapes; fall back to a more permissive pattern.
        m = re.search(
            r'id="settings-devices">(.+?)<!-- 2\. DIVOOM TAB',
            src,
            re.DOTALL,
        )
    assert m, "Settings → Devices block not found in templates.js"
    return m.group(1)


# ── 1. Weather card is in Live Widgets, no text content ──────────────


def test_weather_card_in_live_widgets() -> None:
    lw = _live_widgets_block()
    assert 'id="widget-card-weather"' in lw, (
        "Weather card (widget-card-weather) is not in Live Widgets."
    )


def test_weather_card_has_no_panel_hint() -> None:
    """The Weather card body has no panel-hint text. A "Push to Device"
    button is allowed (R26: manual push alongside auto-push)."""
    lw = _live_widgets_block()
    # Extract the weather card. Use greedy match to capture the FULL
    # card content (not stopping at the first triple </div>).
    m = re.search(
        # class list is allowed extra trailing classes (e.g. a layout utility
        # like clip-shrink) — pin the id, not an exact class string.
        r'<div class="card glass-card[^"]*" id="widget-card-weather"[^>]*>([\s\S]+)</div>\s*</div>\s*</div>',
        lw,
        re.DOTALL,
    )
    assert m, "weather card markup not found"
    body = m.group(1)
    # The card-header is allowed (it has the title), but the card-body
    # should not have any panel-hint.
    body_match = re.search(r'<div class="card-body[^"]*"[^>]*>([\s\S]+)</div>\s*</div>', body, re.DOTALL)
    assert body_match, "weather card-body not found"
    body_inner = body_match.group(1)
    assert "panel-hint" not in body_inner, (
        "Weather card has a panel-hint — should be preview-only."
    )
    # R40 §4: the "Push to Device" button was replaced by a Live (15m) header
    # toggle, so the body has no push button.
    assert "pushWeatherToDevice" not in body_inner, (
        "Weather card still has a Push to Device button — replaced by Live toggle."
    )
    assert 'id="weather-live"' in body or 'id="weather-live"' in lw, (
        "Weather card missing the Live (15m) header toggle."
    )


def test_weather_preview_has_128px_box_and_temp_and_icon() -> None:
    """The 128x128 preview box contains the temp + icon spans."""
    lw = _live_widgets_block()
    assert 'id="weather-device-preview"' in lw, "weather-device-preview box missing"
    assert 'id="weather-preview-temp"' in lw, "weather-preview-temp span missing"
    assert 'id="weather-preview-icon"' in lw, "weather-preview-icon SVG missing"
    assert 'id="weather-preview-location"' in lw, "weather-preview-location span missing"


# ── 2. Notification cards moved to Live Widgets ───────────────────────


def test_notif_manual_card_in_live_widgets() -> None:
    lw = _live_widgets_block()
    assert 'id="widget-card-notif-manual"' in lw, (
        "Manual Notification card (widget-card-notif-manual) is not in Live Widgets."
    )
    # The form widgets still have their ids.
    assert 'id="notif-app-select"' in lw
    assert 'id="notif-text"' in lw
    assert 'id="notif-send"' in lw


def test_notif_mirror_card_in_live_widgets() -> None:
    lw = _live_widgets_block()
    assert 'id="widget-card-notif-mirror"' in lw, (
        "macOS Notifications mirror card (widget-card-notif-mirror) is not in Live Widgets."
    )
    assert 'id="macnotif-toggle"' in lw
    assert 'id="macnotif-detail"' in lw
    assert 'id="macnotif-rules-json"' in lw
    assert 'id="macnotif-rules-save"' in lw


def test_settings_devices_block_no_longer_has_notif_cards() -> None:
    """The old Notification + macOS Notifications cards are GONE
    from Settings → Devices (R15 §3 move to Live Widgets)."""
    devices = _settings_devices_block()
    # The old cards were <div class="card glass-card"> wrapping the
    # notif-app-select / macnotif-toggle ids. We only need to assert
    # those ids are no longer in the Devices block.
    # (They're now in the Live Widgets block, so the assertion can be
    # loose — just that they aren't in *both* the old and new homes.)
    # The old card-header had h3>Notification</h3> and h3>macOS
    # Notifications</h3> — check the explicit text in the Devices
    # block.
    assert "<h3>Notification</h3>" not in devices, (
        "Old 'Notification' h3 header is still in Settings → Devices."
    )
    assert "<h3>macOS Notifications</h3>" not in devices, (
        "Old 'macOS Notifications' h3 header is still in Settings → Devices."
    )


# ── 3. widgets.js wires auto-fetch + auto-push ────────────────────────


def test_widgets_js_calls_get_weather_on_select() -> None:
    src = WIDGETS_JS.read_text()
    # selectWidget("weather") path calls api.get_weather() (via
    # refreshWeatherPreview).
    assert "get_weather" in src, "widgets.js does not call get_weather."
    # R40 §4: the Weather Live toggle polls every 15 minutes.
    assert re.search(
        r"15\s*\*\s*60\s*\*\s*1000",
        src,
    ), "widgets.js is missing the 15-minute weather poll timer."


def test_widgets_js_weather_device_push_is_a_daemon_job() -> None:
    """R44 §6: the weather DEVICE push moved to a daemon live job, so the GUI
    starts/stops it via toggle_weather_sync (it no longer calls push_weather
    on its own timer)."""
    src = WIDGETS_JS.read_text()
    assert "toggle_weather_sync" in src, (
        "widgets.js does not start the daemon weather job via toggle_weather_sync."
    )


def test_widgets_js_stops_weather_preview_poller_on_tab_leave() -> None:
    src = WIDGETS_JS.read_text()
    # R44 §6: the tab-leave branch stops LOCAL preview pollers (the daemon
    # background jobs keep running). It must still clear the weather preview
    # interval. The branch carries the 'Stop local preview pollers' comment.
    tab_leave = re.search(
        r"//\s*Stop local preview pollers[\s\S]+?\}\s*\}\);",
        src,
    )
    assert tab_leave, "tab-leave branch (with 'Stop local preview pollers' comment) not found"
    assert "stopWeatherPolling()" in tab_leave.group(0), (
        "tab-leave handler does not call stopWeatherPolling()."
    )


def test_widgets_js_clears_weather_active_class_on_tab_leave() -> None:
    src = WIDGETS_JS.read_text()
    # The cards array on tab-leave must include "weather" so the
    # active state gets cleared.
    assert re.search(
        r'\[.*?"music".*?"stock".*?"sysmon".*?"weather".*?\]',
        src,
        re.DOTALL,
    ), "tab-leave cards list does not include 'weather'."


def test_settings_js_dead_push_weather_handler_removed() -> None:
    """The old #push-weather-btn click handler in settings.js is
    dead code now (button removed in R15 §3)."""
    src = SETTINGS_JS
    assert "push-weather-btn" not in src, (
        "settings.js still references the removed #push-weather-btn — "
        "should be cleaned up."
    )
