"""
R15 §1+§7 — tests for the unified tab chrome (tabs.css).

These tests guard the design contract: the segmented-pill shape is
defined in exactly one place (tabs.css) and is shared across
Channels, Tools, Settings, and Theme. Legacy class names in
settings.css are aliases — the new `.tab-btn` / `.tabs-row` is the
source of truth.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
TABS_CSS = REPO_ROOT / "divoom_gui" / "web_ui" / "tabs.css"
SETTINGS_CSS = REPO_ROOT / "divoom_gui" / "web_ui" / "settings.css"
CHANNELS_CSS = REPO_ROOT / "divoom_gui" / "web_ui" / "channels.css"
STYLE_CSS = REPO_ROOT / "divoom_gui" / "web_ui" / "style.css"
STYLE_EXTRA_CSS = REPO_ROOT / "divoom_gui" / "web_ui" / "style_extra.css"
INDEX_HTML = REPO_ROOT / "divoom_gui" / "web_ui" / "index.html"
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
    REPO_ROOT / "divoom_gui" / "web_ui" / "templates_routines.js",
])
ROUTINES_JS = REPO_ROOT / "divoom_gui" / "web_ui" / "templates_routines.js"


# ── tabs.css basics ───────────────────────────────────────────────────


def test_tabs_css_exists() -> None:
    assert TABS_CSS.exists()


def test_tabs_css_uses_design_tokens() -> None:
    """tabs.css must reference the design tokens from style.css."""
    src = TABS_CSS.read_text()
    assert "--font-sans" in src, "tabs.css should use --font-sans"
    assert "--primary" in src, "tabs.css should use --primary for active state"
    assert "--text-muted" in src, "tabs.css should use --text-muted for inactive"


def test_tabs_css_defines_tabs_row() -> None:
    src = TABS_CSS.read_text()
    assert re.search(r"\.tabs-row\s*\{[^}]*display:\s*flex", src, re.DOTALL)


def test_tabs_css_defines_tab_btn() -> None:
    src = TABS_CSS.read_text()
    assert re.search(
        r"\.tabs-row\s+\.tab-btn\s*\{",
        src,
    ), "tabs.css is missing the .tabs-row .tab-btn rule"


def test_tabs_css_defines_active_state() -> None:
    """The active state contract: a translucent --primary tint (bg + text +
    border), matching the sidebar's .nav-btn.active pattern (sidebar.css) —
    a solid saturated fill here read as a different, heavier "selected"
    language than the rest of the app uses for the same state (R12 visual
    pass, 2026-07-14)."""
    src = TABS_CSS.read_text()
    m = re.search(
        r"\.tabs-row\s+\.tab-btn\.active\s*\{([^}]+)\}",
        src,
        re.DOTALL,
    )
    assert m, "tabs.css is missing .tabs-row .tab-btn.active"
    body = m.group(1)
    assert "var(--primary)" in body, "active text must use --primary"
    assert "rgba(255, 90, 31" in body, "active bg/border must be a translucent --primary tint"


def test_tabs_css_icon_slot() -> None:
    src = TABS_CSS.read_text()
    assert re.search(
        r"\.tabs-row\s+\.tab-icon\s*\{",
        src,
    ), "tabs.css is missing the .tab-icon prefix slot"


# ── legacy aliases in settings.css ────────────────────────────────────


def test_settings_css_keeps_legacy_aliases() -> None:
    """Older markup (theme buttons, etc.) still references the legacy
    class names — settings.css must alias them so they still render."""
    src = SETTINGS_CSS.read_text()
    # The three legacy classes appear in a single shared rule.
    assert re.search(
        r"\.settings-tab-btn\s*,\s*\n\s*\.tools-subtab-btn\s*,\s*\n\s*\.theme-mode-btn\s*\{",
        src,
    ), "settings.css should group legacy class names in a single shared rule"


def test_settings_css_does_not_duplicate_chrome() -> None:
    """The active-state rule must appear once (in tabs.css), not be
    duplicated in settings.css. The alias in settings.css should
    provide a fallback only for markup that hasn't been migrated yet."""
    src = SETTINGS_CSS.read_text()
    # The single .active rule in settings.css uses --primary + #ffffff.
    matches = re.findall(
        r"\.settings-tab-btn\.active\s*,\s*\n\s*\.tools-subtab-btn\.active\s*,\s*\n\s*\.theme-mode-btn\.active\s*\{[^}]+\}",
        src,
        re.DOTALL,
    )
    assert len(matches) == 1, (
        f"settings.css has {len(matches)} legacy-active rules; expected 1"
    )


def test_channels_css_dropped_chrome() -> None:
    """channels.css no longer defines the .channel-card chrome."""
    src = CHANNELS_CSS.read_text()
    # The old vertical-card chrome rule was removed in R15 §1.
    assert "background: rgba(255, 255, 255, 0.02)" not in src, (
        "channels.css still has the old .channel-card chrome background — "
        "should be removed; the chrome now lives in tabs.css."
    )


# ── markup uses the new classes ───────────────────────────────────────


def test_channel_row_uses_tabs_row() -> None:
    html = INDEX_HTML.read_text()
    assert re.search(
        r'<div class="tabs-row"[^>]*role="tablist"',
        html,
    ), "index.html channel row is missing the new .tabs-row wrapper"


def test_settings_subtabs_use_tabs_row() -> None:
    src = TEMPLATES_JS
    assert re.search(
        r'<div class="tabs-row"[^>]*aria-label="Settings"',
        src,
    ), "templates.js Settings sub-tab row is missing the new .tabs-row wrapper"


def test_routines_subtabs_use_tabs_row() -> None:
    src = ROUTINES_JS.read_text()
    assert re.search(
        r'<div class="tabs-row"[^>]*aria-label="Schedule"',
        src,
    ), "Schedule (ex-Routines) sub-tab row is missing the .tabs-row wrapper"


def test_theme_buttons_use_tabs_row() -> None:
    src = TEMPLATES_JS
    assert re.search(
        r'<div class="tabs-row theme-buttons"',
        src,
    ), "templates.js theme-mode row is missing .tabs-row"


def test_no_legacy_channel_card_in_index_html() -> None:
    """After R15 §1, the channel row uses .tab-btn, not .channel-card."""
    html = INDEX_HTML.read_text()
    # The new class is on all 7 channel buttons.
    assert html.count('class="tab-btn') >= 7
    # The old class should be gone from the channel row (it may still
    # appear in a comment, but not as an element class).
    assert 'class="channel-card' not in html, (
        "index.html still has a .channel-card element — should be .tab-btn"
    )


def test_no_legacy_settings_tab_btn_in_templates() -> None:
    """The Settings row uses .tab-btn, not .settings-tab-btn."""
    src = TEMPLATES_JS
    # Active state class is the same .tab-btn, so look for the data attr.
    assert re.search(
        r'<button class="tab-btn active"\s+data-settings-tab="settings-devices"',
        src,
    ), "Settings Devices tab is not using .tab-btn"


# ── R28: tab spacing is centralised in one place (style.css :root) ─────


def test_tab_spacing_tokens_defined_once_in_root() -> None:
    """The three tab-spacing tokens live in style.css :root and nowhere else."""
    style = STYLE_CSS.read_text()
    for tok in ("--tab-pane-pad-y", "--tab-pane-pad-x", "--tab-pane-gap"):
        # Defined exactly once (the `:root` declaration).
        assert style.count(f"{tok}:") == 1, f"{tok} must be declared once in style.css :root"


def test_tabs_section_uses_padding_tokens() -> None:
    """.tabs-section padding comes from the tokens, not hardcoded px."""
    src = TABS_CSS.read_text()
    m = re.search(r"\.tabs-section\s*\{([^}]*)\}", src)
    assert m, "tabs.css is missing the .tabs-section rule"
    body = m.group(1)
    assert "var(--tab-pane-pad-y)" in body and "var(--tab-pane-pad-x)" in body, (
        ".tabs-section padding must use --tab-pane-pad-y / --tab-pane-pad-x"
    )
    # No stray hardcoded padding/margin from earlier rounds.
    assert "10px 12px" not in body and "margin-bottom: 16px" not in body


def test_flex_panels_cancel_panel_gap_for_tab_pane() -> None:
    """In flex .tab-content (Tools/Settings) the pane→content gap is the panel
    flex gap cancelled + re-added as --tab-pane-gap (net == --tab-pane-gap)."""
    src = TABS_CSS.read_text()
    m = re.search(r"\.tab-content\s*>\s*\.tabs-section\s*\{([^}]*)\}", src)
    assert m, "tabs.css must scope a `.tab-content > .tabs-section` margin rule (R28 r2)"
    body = m.group(1)
    assert "var(--tab-pane-gap)" in body and "var(--panel-gap)" in body, (
        "the flex pane gap must be calc(--tab-pane-gap - --panel-gap)"
    )


def test_channels_grid_rows_pin_tab_pane() -> None:
    """The Channels grid must pin the tab-pane row to content height (auto 1fr),
    else align-content stretches it into a giant empty glass box; and the
    pane→content gap uses the --tab-pane-gap token."""
    src = STYLE_EXTRA_CSS.read_text()
    bodies = re.findall(r"#control-panel\s+\.grid-layout\s*\{([^}]*)\}", src)
    assert bodies, "#control-panel .grid-layout rule missing"
    joined = "\n".join(bodies)
    assert re.search(r"grid-template-rows:\s*auto\s+1fr", joined), (
        "#control-panel .grid-layout must set grid-template-rows: auto 1fr (R28 r2)"
    )
    assert "var(--tab-pane-gap)" in joined, "channels grid row-gap must use --tab-pane-gap"


def test_tabs_row_is_centered() -> None:
    """The tab row is centered (margin auto), with scrollbar-gutter:stable
    on .tab-content.active preventing horizontal shift when scrollbar toggles."""
    src = TABS_CSS.read_text()
    m = re.search(r"\.tabs-row\s*\{([^}]*)\}", src)
    assert m and "margin-left: auto" in m.group(1), (
        ".tabs-row should be centered with margin auto"
    )


def test_settings_tab_pane_does_not_wrap_content() -> None:
    """Regression: the Settings .tabs-section must close right after the tab row
    so the content panels are siblings, not nested inside the glass pane."""
    src = (REPO_ROOT / "divoom_gui" / "web_ui" / "templates_settings.js").read_text()
    pane_open = src.index('class="tabs-section"')
    first_content = src.index('class="settings-tab-content')
    between = src[pane_open:first_content]
    # The tabs-section opens, the tab row opens+closes, THEN the section closes —
    # so there must be >= 2 </div> between the pane open and the first content panel.
    assert between.count("</div>") >= 2, (
        "Settings .tabs-section is not closed before the content panels "
        "(it would wrap the whole panel)"
    )


# ── index.html links tabs.css ─────────────────────────────────────────


def test_index_html_links_tabs_css() -> None:
    html = INDEX_HTML.read_text()
    assert 'href="tabs.css"' in html, (
        "index.html is missing the <link rel='stylesheet' href='tabs.css'>"
    )
    # tabs.css must come after style.css (so it can override the design tokens).
    style_pos = html.find('href="style.css"')
    tabs_pos = html.find('href="tabs.css"')
    assert tabs_pos > style_pos, (
        "tabs.css must be linked AFTER style.css so its rules win over the base"
    )
