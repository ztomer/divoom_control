"""
R15 §4 — tests for the Settings refactor.

The §4 contract is three-fold:
1. The Display card no longer contains the danger zone — it is its
   own card.
2. The Routines auto-sync interval select has 6 options (1h, 6h, 12h,
   24h, 7d, 30d) and the long-interval values round-trip through
   the config.
3. The config has a MAX_INTERVAL guardrail (30 days) so a typo in
   the JSON file doesn't disable syncing for years.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
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
    REPO_ROOT / "divoom_gui" / "web_ui" / "templates_device_settings.js",
])
SETTINGS_CSS = REPO_ROOT / "divoom_gui" / "web_ui" / "settings.css"

from divoom_lib.hotchannel_config import (
    DEFAULTS,
    MAX_INTERVAL,
    MIN_INTERVAL,
    save_config,
    load_config,
)


# ── 1. Danger zone is its own card ────────────────────────────────────


def test_display_controls_separate_from_danger_zone() -> None:
    """R40 §8: the mirror toggle (Display) and the Danger zone block live in
    the same Device Settings pane, but the danger block comes strictly after
    the display controls."""
    src = TEMPLATES_JS
    mirror = src.find('id="screen-mirror-toggle"')
    danger = src.rfind("danger-card")
    assert mirror > 0, "mirror toggle not found"
    assert danger > mirror, "Danger zone must come after the display controls"


def test_danger_zone_block_exists() -> None:
    """R40 §8: Danger zone is a danger-card block at the bottom of the Device
    Settings pane (no longer a standalone glass card)."""
    src = TEMPLATES_JS
    assert re.search(
        r'class="danger-card"[\s\S]*?<h3[^>]*>Danger zone</h3>',
        src,
    ), "Danger zone block (danger-card + 'Danger zone' header) is missing."


def test_danger_card_visual_marker() -> None:
    """The danger-card class must have a red border treatment."""
    css = SETTINGS_CSS.read_text()
    assert re.search(
        r"\.card\.glass-card\.danger-card\s*\{[^}]*border:\s*1px solid rgba\(239,\s*68,\s*68",
        css,
        re.DOTALL,
    ), (
        ".card.glass-card.danger-card is missing a red border treatment "
        "in settings.css."
    )


def test_factory_reset_btn_still_present() -> None:
    """The factory reset button must still be in the DOM (just moved
    to its own card)."""
    src = TEMPLATES_JS
    assert re.search(
        r'<button\s+id="factory-reset-btn"[^>]*class="glow-btn danger"[^>]*>'
        r'\s*Factory reset device…\s*</button>',
        src,
    ), "factory-reset-btn is missing — should be in the new Danger zone card."


# ── 2. Routines interval options ──────────────────────────────────────


def test_routines_select_has_six_options() -> None:
    src = TEMPLATES_JS
    tabs_match = re.search(
        r'id="routines-interval-tabs"[^>]*>(.+?)</div>',
        src,
        re.DOTALL,
    )
    assert tabs_match, "routines-interval-tabs block is missing"
    body = tabs_match.group(1)
    values = re.findall(r'data-interval="(\d+)"', body)
    expected = ["3600", "21600", "43200", "86400", "604800", "2592000"]
    assert values == expected, (
        f"Expected interval tabs {expected}, got {values}."
    )


def test_routines_interval_labels_are_human_readable() -> None:
    """Spot-check that 7d and 30d have short labels."""
    src = TEMPLATES_JS
    tabs_match = re.search(
        r'id="routines-interval-tabs"[^>]*>(.+?)</div>',
        src,
        re.DOTALL,
    )
    body = tabs_match.group(1)
    assert re.search(r'data-interval="604800"[^>]*>7d<', body), (
        "7d interval tab should have label '7d'."
    )
    assert re.search(r'data-interval="2592000"[^>]*>30d<', body), (
        "30d interval tab should have label '30d'."
    )


# ── 3. Config round-trip + MAX_INTERVAL guardrail ─────────────────────


def test_long_interval_round_trips(tmp_path: Path, monkeypatch) -> None:
    """Saving 7d (604800) and 30d (2592000) round-trips through the
    config file."""
    cfg_file = tmp_path / "hotchannel.json"
    monkeypatch.setenv("DIVOOM_HOTCHANNEL_CONFIG", str(cfg_file))

    for value in (604800, 2592000):
        cfg = dict(DEFAULTS)
        cfg["enabled"] = True
        cfg["interval"] = value
        cfg["targets"] = ["11-75-58-3f-fd-aa"]
        save_config(cfg)
        loaded = load_config()
        assert loaded["interval"] == value, (
            f"Interval {value}s did not round-trip; got {loaded['interval']}."
        )
        assert loaded["enabled"] is True
        assert loaded["targets"] == ["11-75-58-3f-fd-aa"]


def test_max_interval_clamps_typos(tmp_path: Path, monkeypatch) -> None:
    """A typo (e.g. 6048000 instead of 604800) is clamped to MAX_INTERVAL
    on read, so the daemon doesn't end up waiting 70 days."""
    cfg_file = tmp_path / "hotchannel.json"
    monkeypatch.setenv("DIVOOM_HOTCHANNEL_CONFIG", str(cfg_file))
    cfg_file.write_text(json.dumps({"enabled": True, "interval": 6048000}))

    loaded = load_config()
    assert loaded["interval"] == MAX_INTERVAL, (
        f"interval=6048000 should be clamped to MAX_INTERVAL ({MAX_INTERVAL}); "
        f"got {loaded['interval']}."
    )


def test_min_interval_unchanged(tmp_path: Path, monkeypatch) -> None:
    """Belt-and-braces: MIN_INTERVAL still clamps the floor."""
    cfg_file = tmp_path / "hotchannel.json"
    monkeypatch.setenv("DIVOOM_HOTCHANNEL_CONFIG", str(cfg_file))
    cfg_file.write_text(json.dumps({"enabled": True, "interval": 5}))

    loaded = load_config()
    assert loaded["interval"] == MIN_INTERVAL, (
        f"interval=5 should be clamped to MIN_INTERVAL ({MIN_INTERVAL}); "
        f"got {loaded['interval']}."
    )


def test_max_interval_constant_value() -> None:
    """The constant is exactly 30 days in seconds — guards against
    typos in the constant itself."""
    assert MAX_INTERVAL == 30 * 24 * 60 * 60, (
        f"MAX_INTERVAL should be 30 days = 2592000, got {MAX_INTERVAL}."
    )
