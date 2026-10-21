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
# The settings' `[gallery]` table -- the ONE home for the device list. Both
# sides read it, so both sides' idea of "which keys are settings, not
# devices" has to be the same list.
SETTINGS_PY = REPO / "divoom_lib" / "settings_devices.py"
SETTINGS_RS = REPO / "divoomd" / "src" / "settings_devices.rs"
CLOUD_CATEGORY_RS = REPO / "divoomd" / "src" / "cloud_category.rs"


def python_side() -> tuple[set[str], dict, tuple[int, int]]:
    """Fields, defaults and clamp bounds, read from the Python source."""
    tree = ast.parse(PY.read_text(encoding="utf-8"))
    defaults: dict = {}
    consts: dict = {}
    # Module-level constants first: a DEFAULTS value may be a NAME
    # (`"interval": DEFAULT_INTERVAL`), and a gate that cannot resolve a name
    # reports "no default" instead of the default -- which reads as "nothing
    # to compare" and quietly stops pinning the very number it exists to pin.
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not node.targets:
            continue
        name = getattr(node.targets[0], "id", "")
        if name in ("DEFAULTS",):
            continue
        try:
            consts[name] = ast.literal_eval(node.value)
        except (ValueError, TypeError):
            continue
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not node.targets:
            continue
        name = getattr(node.targets[0], "id", "")
        if name == "DEFAULTS" and isinstance(node.value, ast.Dict):
            for k, v in zip(node.value.keys, node.value.values):
                try:
                    key = ast.literal_eval(k)
                except ValueError:
                    continue
                if isinstance(v, ast.Name):
                    defaults[key] = consts.get(v.id)
                else:
                    try:
                        defaults[key] = ast.literal_eval(v)
                    except ValueError:
                        defaults[key] = None
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
    # The literal may carry `_` separators: `clippy::unreadable_literal` ADDS
    # them, so `86400` is written `86_400` in a pedantic crate. The old
    # pattern here was `(-?\d+)`, which stopped MATCHING the moment the
    # default became five digits -- and a pattern that matches nothing
    # reports no divergence, which is the worst way for a gate to fail: the
    # interval default was silently unpinned. Same reasoning as the clamp
    # below.
    for fn, val in re.findall(r"fn (default_\w+)\(\) -> \w+ \{\s*(-?[\d_]+)\s*\}", src):
        defaults[fn.removeprefix("default_")] = int(val.replace("_", ""))
    # `#[serde(default)]` with no function means the type's zero value.
    for field in fields:
        defaults.setdefault(field, None)

    # Rust literals may carry `_` separators, and `clippy::unreadable_literal`
    # ADDS them -- adopting pedantic rewrote `2592000` to `2_592_000` and this
    # gate reported a clamp divergence that did not exist, because it reads
    # source TEXT and a linter had legitimately changed the text. An instrument
    # that greps source has to accept every spelling the toolchain may produce.
    clamp = re.search(r"\.clamp\(([\d_]+),\s*([\d_]+)\)", src)
    bounds = (
        (int(clamp.group(1).replace("_", "")), int(clamp.group(2).replace("_", "")))
        if clamp
        else (None, None)
    )
    return fields, defaults, bounds


def settings_side() -> tuple[set[str], int | None]:
    """The `[gallery]` table's reserved keys and default classify, Python side."""
    tree = ast.parse(SETTINGS_PY.read_text(encoding="utf-8"))
    reserved: set[str] = set()
    classify: int | None = None
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not node.targets:
            continue
        name = getattr(node.targets[0], "id", "")
        if name == "RESERVED_KEYS":
            try:
                reserved = set(ast.literal_eval(node.value))
            except ValueError:
                reserved = set()
        elif name == "DEFAULT_CLASSIFY":
            try:
                classify = ast.literal_eval(node.value)
            except ValueError:
                classify = None
    return reserved, classify


def settings_rust_side() -> tuple[set[str], int | None]:
    """The same two things, read from the Rust side."""
    src = SETTINGS_RS.read_text(encoding="utf-8")
    reserved: set[str] = set()
    m = re.search(r"pub const RESERVED_KEYS: &\[&str\] = &\[(.*?)\];", src, re.S)
    if m:
        reserved = set(re.findall(r'"([^"]+)"', m.group(1)))
    # The daemon's fallback classify is the cloud's own default, which lives
    # in cloud_category.rs -- that is where the number is, so that is where it
    # is read.
    classify = None
    cm = re.search(
        r"pub const DEFAULT_GALLERY_CLASSIFY: i64 = (\d+);",
        CLOUD_CATEGORY_RS.read_text(encoding="utf-8"),
    )
    if cm:
        classify = int(cm.group(1))
    return reserved, classify


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

    # The settings' `[gallery]` table is the OTHER half of the same fact: the
    # GUI writes it, the daemon reads it, and the keys that are settings
    # rather than devices must be the same list on both sides — otherwise the
    # daemon connects to "gallery_sort".
    py_reserved, py_classify = settings_side()
    rs_reserved, rs_classify = settings_rust_side()
    if py_reserved != rs_reserved:
        problems.append(
            f"the [gallery] table's reserved keys differ: python={sorted(py_reserved)} "
            f"rust={sorted(rs_reserved)} — one side would treat the other's "
            f"settings as devices")
    if py_classify != rs_classify:
        problems.append(
            f"the fallback gallery differs: python={py_classify!r} rust={rs_classify!r}")

    if problems:
        err(f"[hotchannel-parity] {len(problems)} divergence(s) in hotchannel.json")
        for p in problems:
            info(p)
        info("One file, two parsers: they must agree or the settings card lies.")
        return 1

    ok(f"[hotchannel-parity] OK — {len(py_fields)} fields, defaults and "
       f"clamp {py_bounds[0]}..{py_bounds[1]}s agree; "
       f"{len(py_reserved)} reserved gallery keys agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
