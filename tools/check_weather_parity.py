#!/usr/bin/env python3
"""check_weather_parity.py — the Rust and Python weather maps must agree.

R67/C2: weather is implemented twice — `divoom_lib/weather_provider.py` feeds
the GUI's preview card, and `divoomd/src/weather.rs` feeds the device push.
What the user sees and what reaches the panel therefore come from different
code that can disagree.

They do NOT disagree today: diffed 2026-08-29, both map the same 48 wttr codes
to the same icons. That is exactly when a gate is worth adding — before the
drift, not after. The now-playing duplication in the same round had already
drifted, and nobody noticed until a symptom reached the user.

This compares the two tables by code and fails on any difference: a code only
one side knows, or a code both know and disagree about. It is deliberately a
comparison of DATA — the Rust side is a `const` table rather than a `match` for
this reason, since a match arm is invisible to any checker.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.environ.get("GOH_DIR", os.path.expanduser("~/Projects/gates_of_heck")))
from tui.lib import err, info, ok  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
RUST_TABLE = REPO / "divoomd" / "src" / "weather.rs"

# (113, WeatherType::Clear),
ENTRY_RE = re.compile(r"\((\d+),\s*WeatherType::(\w+)\)")
# The Rust enum's discriminants, so both sides compare as the same integers.
RUST_TYPE_VALUES = {
    "Clear": 1,
    "CloudySky": 3,
    "Thunderstorm": 5,
    "Rain": 6,
    "Snow": 8,
    "Fog": 9,
}


def rust_map() -> dict[int, int]:
    text = RUST_TABLE.read_text(encoding="utf-8")
    start = text.index("WEATHER_CODE_TO_DIVOOM")
    end = text.index("];", start)
    out: dict[int, int] = {}
    for code, name in ENTRY_RE.findall(text[start:end]):
        if name not in RUST_TYPE_VALUES:
            raise SystemExit(f"unknown WeatherType::{name} — update RUST_TYPE_VALUES")
        out[int(code)] = RUST_TYPE_VALUES[name]
    return out


def python_map() -> dict[int, int]:
    sys.path.insert(0, str(REPO))
    from divoom_lib.weather_provider import WEATHER_CODE_TO_DIVOOM

    return {int(k): int(v) for k, v in WEATHER_CODE_TO_DIVOOM.items()}


def main() -> int:
    rust = rust_map()
    py = python_map()

    only_rust = sorted(set(rust) - set(py))
    only_py = sorted(set(py) - set(rust))
    disagree = sorted(c for c in set(rust) & set(py) if rust[c] != py[c])

    if only_rust or only_py or disagree:
        err("[weather] the Rust and Python weather maps disagree")
        if only_rust:
            info(f"only in divoomd/src/weather.rs: {only_rust}")
        if only_py:
            info(f"only in divoom_lib/weather_provider.py: {only_py}")
        for c in disagree:
            info(f"code {c}: rust={rust[c]} python={py[c]}")
        info("the GUI preview and the device would show different weather")
        return 1

    ok(f"[weather] OK — {len(rust)} codes, Rust and Python agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
