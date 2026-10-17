"""One answer to "what does this panel have?" (P4.1).

The daemon's feature table (`divoomd/src/panel_features.rs`) is the output of
`tools/derive_panel_features.py`, which runs the decompiled vendor app's own
`setDeviceMode` per model. Two things hold it there:

* `divoom_lib`'s `has_sd` answers the same question and is held to the
  daemon's `sd_card`, as `test_panel_model_parity.py` holds its resolution.
  The other `has_*` flags are not: the app has no per-model switch that means
  "has an FM radio" (`FmModeEnum` only allows FM as an alarm sound),
  `AlarmEnum` has no consumer, and `MicEnum` has one -- there is nothing
  sourced to hold them to.
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
PIXELS = REPO / "divoomd" / "src" / "panel_model.rs"
FLAG_KEYS = ("speaker", "sd_card", "temp_sensor", "wifi")

sys.path.insert(0, str(REPO / "tools"))
import derive_panel_features as derive  # noqa: E402


def _rust_features() -> dict[str, dict]:
    src = RUST.read_text()
    block = src[src.index("pub const FEATURES"):]
    block = block[: block.index("];")]
    out = {}
    for model, on, clock in re.findall(r'\("([A-Za-z0-9_]+)",\s*([A-Z_| ]+),\s*"(\w+)"\)', block):
        names = {n.strip().lower() for n in on.split("|")}
        out[model] = {**{k: k in names for k in FLAG_KEYS}, "clock": clock}
    return out


def _rust_pixels() -> dict[str, int]:
    src = PIXELS.read_text()
    block = src[src.index("pub const LARGER_THAN_16"):]
    block = block[: block.index("];")]
    return {m: int(px) for m, px in re.findall(r'\("([A-Za-z0-9_]+)",\s*(\d+)\)', block)}


def test_the_rust_table_was_read():
    rows = _rust_features()
    assert len(rows) == 50, len(rows)
    assert rows["TivooMax"]["speaker"] and rows["TivooMax"]["sd_card"]
    assert rows["Pixoo64Wifi"]["wifi"] and not rows["Pixoo64Wifi"]["speaker"]


def test_divoom_lib_has_sd_is_the_daemons_sd_card():
    rows = _rust_features()
    wrong = {m: (c.has_sd, rows[m]["sd_card"])
             for m, c in DEVICE_CAPABILITIES.items() if c.has_sd != rows[m]["sd_card"]}
    assert not wrong, f"model: (divoom_lib, daemon/APK) -> {wrong}"


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
