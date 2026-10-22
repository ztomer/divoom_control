"""One answer to "what does this panel have?" (P4.1, P3.4).

The daemon's feature table (`divoomd/src/panel_features.rs`) is the output of
`tools/derive_panel_features.py`, which runs the decompiled vendor app's own
`setDeviceMode` per model. Two things hold it there:

* `divoom_lib`'s `has_sd` answers the same question and is held to the
  daemon's `sd_card`, as `test_panel_model_parity.py` holds its resolution.
  The radio, the microphone and the alarm are held the same way, and were
  WRONG in `divoom_lib` until 2026-10-22: this file said the app has no
  per-model switch meaning "has an FM radio" (`FmModeEnum` only allows FM as
  an alarm sound), and that belief is what had the web UI offering the radio
  to every Tivoo and Ditoo by NAME. The app decides it twice over -- it
  offers the FM home screen to exactly the models whose `FmModeEnum` is
  `SupportFm`, and the alarm screen to exactly the models whose `AlarmEnum`
  is `SupportAlarm`.
* Where the decompiled sources and a JDK are present, the derivation is re-run
  and the whole Rust table compared, so a hand edit to the table cannot pass.
  They are local-only (`references/` is never published), so elsewhere that
  half says why it did not run.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from divoom_lib.models.capabilities import DEVICE_CAPABILITIES

REPO = Path(__file__).resolve().parents[1]
RUST = REPO / "divoomd" / "src" / "panel_features.rs"
SCREENS_RUST = REPO / "divoomd" / "src" / "panel_screens.rs"
PIXELS = REPO / "divoomd" / "src" / "panel_model.rs"
GUI = REPO / "divoom_gui" / "web_ui" / "panel_facts.js"
FLAG_KEYS = ("speaker", "sd_card", "temp_sensor", "wifi", "radio", "mic", "vj")

# The rows are matched with the whitespace normalised out: `cargo fmt` wraps
# the long ones across lines, and a gate that cried wolf over formatting
# would be ignored, and the next real drift would go with it. The VALUES are
# not normalised: a wrong flag is a wrong flag.
_ROW = (r'\(\s*"([A-Za-z0-9_]+)",\s*([A-Z_]+(?:\s*\|\s*[A-Z_]+)*),'
        r'\s*"(\w+)",\s*"(\w+)",\s*"(\w+)",?\s*\)')

sys.path.insert(0, str(REPO / "tools"))
import derive_panel_features as derive  # noqa: E402


def _rust_features() -> dict[str, dict]:
    src = RUST.read_text()
    block = src[src.index("pub const FEATURES"):]
    block = block[: block.index("];")]
    out = {}
    for model, on, clock, _discover, _arch in re.findall(_ROW, block, re.S):
        names = {n.strip().lower() for n in on.split("|")}
        out[model] = {**{k: k in names for k in FLAG_KEYS}, "clock": clock}
    return out


def _rust_pixels() -> dict[str, int]:
    src = PIXELS.read_text()
    block = src[src.index("pub const LARGER_THAN_16"):]
    block = block[: block.index("];")]
    return {m: int(px) for m, px in re.findall(r'\("([A-Za-z0-9_]+)",\s*(\d+)\)', block)}


def _rust_chassis() -> dict[str, tuple[str, float, float, float]]:
    src = PIXELS.read_text()
    block = src[src.index("pub const FAMILIES"):]
    block = block[: block.index("];")]
    out = {}
    for family, w, h, screen in re.findall(
        r'\("(\w+)",\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)\)', block
    ):
        out[family] = (family, float(w), float(h), float(screen))
    return out


def _rust_screens() -> dict[str, list[str]]:
    """`DiscoverFunEnum` -> the home screens the app offers for it."""
    src = SCREENS_RUST.read_text()
    block = src[src.index("pub const SCREENS"):]
    block = block[: block.index("];")]
    out = {}
    for name, screens in re.findall(r'\(\s*"(\w+)",\s*"([a-z_ ]*)"', block, re.S):
        out[name] = screens.split()
    return out


def _rust_model_screens() -> dict[str, list[str]]:
    """Model -> the screens the app offers it."""
    src = RUST.read_text()
    block = src[src.index("pub const FEATURES"):]
    block = block[: block.index("];")]
    screens = _rust_screens()
    out = {}
    for model, _on, _clock, discover, _arch in re.findall(_ROW, block, re.S):
        out[model] = screens.get(discover, [])
    return out


def test_the_rust_table_was_read():
    rows = _rust_features()
    assert len(rows) == 50, len(rows)
    assert rows["TivooMax"]["speaker"] and rows["TivooMax"]["sd_card"]
    assert rows["Pixoo64Wifi"]["wifi"] and not rows["Pixoo64Wifi"]["speaker"]


def test_divoom_lib_is_the_daemons_table():
    """The retired library's copy of the per-model facts, held to the daemon's.

    Four of them now: the SD card, the radio, the microphone and the alarm.
    The last three were wrong here before 2026-10-22, and the radio was the
    one that reached the screen -- the web UI showed the FM card to every
    panel whose NAME contained "tivoo" or "ditoo".
    """
    rows = _rust_features()
    wrong = {
        m: (c.has_sd, rows[m]["sd_card"])
        for m, c in DEVICE_CAPABILITIES.items()
        if m in rows and c.has_sd != rows[m]["sd_card"]
    }
    assert not wrong, f"model: (divoom_lib, daemon/APK) -> {wrong}"
    wrong = {
        m: (c.has_fm, rows[m]["radio"])
        for m, c in DEVICE_CAPABILITIES.items()
        if m in rows and c.has_fm != rows[m]["radio"]
    }
    assert not wrong, f"model: (divoom_lib, daemon/APK) -> {wrong}"
    wrong = {
        m: (c.has_mic, rows[m]["mic"])
        for m, c in DEVICE_CAPABILITIES.items()
        if m in rows and c.has_mic != rows[m]["mic"]
    }
    assert not wrong, f"model: (divoom_lib, daemon/APK) -> {wrong}"
    # The alarm is not a switch in the daemon's table but a screen in the
    # app's home list: the app offers an alarm to every model but the bags.
    screens = _rust_model_screens()
    wrong = {
        m: (c.has_alarm, "alarm" in screens.get(m, []))
        for m, c in DEVICE_CAPABILITIES.items()
        if m in screens and c.has_alarm != ("alarm" in screens[m])
    }
    assert not wrong, f"model: (divoom_lib, daemon/APK) -> {wrong}"


def test_the_web_ui_fallback_chassis_is_the_daemons_generic_one():
    """The GUI keeps ONE number -- the generic chassis, for a panel the daemon
    has not described -- and it must be the daemon's generic row."""
    gui = GUI.read_text()
    m = re.search(r"const GENERIC_CHASSIS = \{ w_mm: ([\d.]+), h_mm: ([\d.]+), screen_mm: ([\d.]+) \};", gui)
    assert m, "the web UI's generic chassis row is gone"
    generic = _rust_chassis()["panel"]
    assert (float(m.group(1)), float(m.group(2)), float(m.group(3))) == generic[1:], (
        f"the web UI's generic chassis {(m.group(1), m.group(2), m.group(3))} is not the "
        f"daemon's {generic[1:]}"
    )


def test_the_rust_table_is_what_the_vendor_app_computes():
    why = derive.available()
    if why:
        pytest.skip(f"cannot re-derive here: {why}")
    rows = derive.derive()
    derived = {r["model"]: {**{k: r[k] for k in FLAG_KEYS}, "clock": r["clock"]} for r in rows}
    assert derived == _rust_features()
    # The same run checks P3.1's pixel table independently of how it was
    # first transcribed.
    larger = _rust_pixels()
    assert {r["model"]: r["pixels"] for r in rows} == {
        r["model"]: larger.get(r["model"], 16) for r in rows}
    # ...and the app's home list, which is what the panel CAN SHOW (P3.4).
    screens = {r["model"]: r["screens"] for r in rows}
    assert screens["DITOO"], screens
    assert "fm_radio" in screens["TivooLcd"], screens["TivooLcd"]
    assert "fm_radio" not in screens["DITOO"], screens["DITOO"]
