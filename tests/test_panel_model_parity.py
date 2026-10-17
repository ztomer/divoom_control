"""One answer to "how many pixels is this panel?" (P3.1).

The daemon resolves a panel's model and resolution in
`divoomd/src/panel_model.rs`, from the decompiled vendor app's
`setDeviceMode`. `divoom_lib`'s capability table (read by the Python CLI's
`info`/`caps` output) answered the same question from memory and got it wrong
for a third of the lineup -- a Tivoo-Max at 32x32, a CyberBag at 16, an LCD
panel at 32 where the vendor app draws 128. Two owners of one fact drift; this
holds the second to the first.
"""
from __future__ import annotations

import re
from pathlib import Path

from divoom_lib.models.capabilities import DEVICE_CAPABILITIES

RUST = Path(__file__).resolve().parents[1] / "divoomd" / "src" / "panel_model.rs"


def _rust_table() -> tuple[dict[str, int], int]:
    src = RUST.read_text()
    block = src[src.index("pub const LARGER_THAN_16"):]
    block = block[: block.index("];")]
    larger = {m: int(px) for m, px in re.findall(r'\("([A-Za-z0-9_]+)",\s*(\d+)\)', block)}
    default = int(re.search(r"pub const DEFAULT_PIXELS: u32 = (\d+);", src).group(1))
    return larger, default


def test_the_rust_table_was_read():
    larger, default = _rust_table()
    assert default == 16
    assert larger["PIXOO_MAX"] == 32 and larger["Pixoo64Wifi"] == 64
    assert len(larger) >= 20


def test_every_python_capability_has_the_daemons_resolution():
    larger, default = _rust_table()
    wrong = {
        model: (caps.panel_resolution, larger.get(model, default))
        for model, caps in DEVICE_CAPABILITIES.items()
        if caps.panel_resolution != larger.get(model, default)
    }
    assert not wrong, f"model: (divoom_lib, daemon/APK) -> {wrong}"
