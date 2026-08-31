#!/usr/bin/env python3
"""check_hotchannel_parity.py — one config file, two parsers, no drift.

R72 P2.4. `~/.config/divoom-control/hotchannel.json` is read and WRITTEN by the
GUI through `divoom_lib/hotchannel_config.py`, and read INDEPENDENTLY by the
daemon in `divoomd/src/monthly_best.rs`. Neither side is wrong -- the GUI owns
the settings UI, the daemon needs the values to run auto-sync -- but two
implementations of one format is the drift shape this round exists to remove,
and here it cannot be removed by deleting a duplicate: both readers are load
bearing.

So it gets the same treatment R67/C2 gave weather: a gate, added while the two
still AGREE. Diffed 2026-08-31 -- identical defaults (interval 3600, classify
18) and identical clamping (60s to 30 days) on both sides. That is exactly when
a parity gate is worth writing. The now-playing duplication in R67 had already
drifted before anyone looked.

What drift would cost, concretely: the Python comment on MIN_INTERVAL says "the
daemon will read-back the clamped value". That is true only while the two clamps
match. Hand-edit the file to `interval: 1` and the GUI shows a clamped 60 while
the daemon hammers the cloud once a second -- a disagreement with no symptom on
the screen that is supposedly reporting it.

Compares DATA, not behaviour: the field set, the defaults, and the clamp bounds.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tui import err, info, ok  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
PY = REPO / "divoom_lib" / "hotchannel_config.py"
RS = REPO / "divoomd" / "src" / "monthly_best.rs"


def python_side() -> tuple[set[str], dict, tuple[int, int]]:
    """Fields, defaults and clamp bounds, read from the Python source."""
    tree = ast.parse(PY.read_text(encoding="utf-8"))
    defaults: dict = {}
    consts: dict = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not node.targets:
            continue
        name = getattr(node.targets[0], "id", "")
        if name == "DEFAULTS" and isinstance(node.value, ast.Dict):
            for k, v in zip(node.value.keys, node.value.values):
                try:
                    defaults[ast.literal_eval(k)] = ast.literal_eval(v)
                except ValueError:
                    defaults[ast.literal_eval(k)] = None
        elif name in ("MIN_INTERVAL", "MAX_INTERVAL"):
            try:
                consts[name] = ast.literal_eval(node.value)
            except ValueError:
                pass
    return set(defaults), defaults, (consts.get("MIN_INTERVAL"), consts.get("MAX_INTERVAL"))


def rust_side() -> tuple[set[str], dict, tuple[int, int]]:
    """The same three things, read from the Rust struct and its clamp."""
    src = RS.read_text(encoding="utf-8")
    m = re.search(r"pub struct HotchannelConfig \{(.*?)\n\}", src, re.S)
    if not m:
        return set(), {}, (None, None)
    fields = set(re.findall(r"pub (\w+):", m.group(1)))

    defaults: dict = {}
    for fn, val in re.findall(r"fn (default_\w+)\(\) -> \w+ \{\s*(-?\d+)\s*\}", src):
        defaults[fn.removeprefix("default_")] = int(val)
    # `#[serde(default)]` with no function means the type's zero value.
    for field in fields:
        defaults.setdefault(field, None)

    clamp = re.search(r"\.clamp\((\d+),\s*(\d+)\)", src)
    bounds = (int(clamp.group(1)), int(clamp.group(2))) if clamp else (None, None)
    return fields, defaults, bounds


def main() -> int:
    py_fields, py_defaults, py_bounds = python_side()
    rs_fields, rs_defaults, rs_bounds = rust_side()
    problems: list[str] = []

    if not py_fields or not rs_fields:
        err("[hotchannel-parity] could not read one of the two sides")
        info(f"  python fields: {sorted(py_fields)}")
        info(f"  rust fields:   {sorted(rs_fields)}")
        return 1

    only_py = py_fields - rs_fields
    only_rs = rs_fields - py_fields
    if only_py:
        problems.append(f"fields the GUI writes and the daemon ignores: {sorted(only_py)}")
    if only_rs:
        problems.append(f"fields the daemon reads and the GUI never writes: {sorted(only_rs)}")

    # Only compare defaults the Rust states explicitly; `#[serde(default)]`
    # means "the type's zero value", which is not a number to diff against.
    for field, rs_val in sorted(rs_defaults.items()):
        if rs_val is None:
            continue
        py_val = py_defaults.get(field)
        if py_val != rs_val:
            problems.append(f"default for {field!r}: python={py_val!r} rust={rs_val!r}")

    if py_bounds != rs_bounds:
        problems.append(
            f"interval clamp differs: python={py_bounds} rust={rs_bounds} — the GUI "
            f"would display a clamped value the daemon does not honour")

    if problems:
        err(f"[hotchannel-parity] {len(problems)} divergence(s) in hotchannel.json")
        for p in problems:
            info(p)
        info("One file, two parsers: they must agree or the settings card lies.")
        return 1

    ok(f"[hotchannel-parity] OK — {len(py_fields)} fields, defaults and "
       f"clamp {py_bounds[0]}..{py_bounds[1]}s agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
