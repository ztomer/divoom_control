#!/usr/bin/env python3
"""check_examples.py — examples/ documents the shipped library; pin it.

`pyproject.toml` ships `divoom_lib` as the `divoom-control` package with a
console script, and `examples/README.md` presents these 7 scripts as the
public usage docs. R73 proved untested public API rots (three methods
nobody had ever called, two broken) — and nothing imports these examples,
so a facade rename breaks the only library docs silently.

This gate pins them structurally, without hardware:

  1. every example module imports cleanly (catches moved helpers —
     including the function-level lazy imports — renamed modules, and
     enum members, which resolve at import time);
  2. every `divoom.<facade>.<method>` / `divoom.capabilities.<flag>`
     chain in example code resolves against the REAL classes. Facade
     wiring comes from `Divoom.__init__`'s own `self.X = Y(...)`
     assignments (parsed, not duplicated); method hops use
     hasattr-or-annotation so annotation-only flags (`has_fm: bool`)
     resolve too.

HONEST SCOPE: constructor kwargs (`Divoom(device_name=...)`) are NOT
checked, nor calls on external libs (`BleakScanner`), nor data flow
(`d['address']`). What rots silently is facade/method renames — the
R73 class — and that is exactly what this pins.
"""
from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tui import err, info, ok  # noqa: E402
from _empty_scope import scope_is_empty  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "examples"

sys.path.insert(0, str(REPO))
import divoom_lib.divoom as _divoom_mod  # noqa: E402
from divoom_lib.models.capabilities import Capabilities  # noqa: E402

DIVOOM_SRC = REPO / "divoom_lib" / "divoom.py"


def facade_map() -> dict[str, type]:
    """Facade attr -> class, derived from Divoom.__init__ assignments."""
    tree = ast.parse(DIVOOM_SRC.read_text(encoding="utf-8"))
    mapping: dict[str, type] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == "__init__"):
            continue
        for stmt in ast.walk(node):
            if (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Attribute)
                and isinstance(stmt.targets[0].value, ast.Name)
                and stmt.targets[0].value.id == "self"
                and isinstance(stmt.value, ast.Call)
                and isinstance(stmt.value.func, ast.Name)
            ):
                cls = getattr(_divoom_mod, stmt.value.func.id, None)
                if isinstance(cls, type):
                    mapping[stmt.targets[0].attr] = cls
    # `capabilities` is a @property returning Capabilities (not a
    # self.X assignment), so it cannot be derived the same way. One
    # explicit seam, documented here rather than hidden.
    mapping["capabilities"] = Capabilities
    return mapping


def has_member(cls: type, name: str) -> bool:
    """Method or annotation-only field, walking the MRO."""
    if hasattr(cls, name):
        return True
    return any(name in getattr(base, "__annotations__", {}) for base in cls.__mro__)


def check_module(mod_name: str, facades: dict[str, type], failures: list[str]) -> None:
    """Import the example, then resolve its facade chains."""
    try:
        mod = importlib.import_module(mod_name)
    except Exception as e:
        failures.append(f"{mod_name}: import failed: {e!r}")
        return
    tree = ast.parse((EXAMPLES / (mod_name.rsplit(".", 1)[-1] + ".py")).read_text())
    # Track simple locals: `x = Divoom(...)` -> Divoom, `y = x.attr` -> facade.
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        types: dict[str, type] = {}
        for stmt in ast.walk(node):
            if not (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1):
                continue
            target = stmt.targets[0]
            if not isinstance(target, ast.Name):
                continue
            value = stmt.value
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "Divoom"
            ):
                types[target.id] = _divoom_mod.Divoom
            elif (
                isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.value.id in types
            ):
                base = types[value.value.id]
                if base is _divoom_mod.Divoom and value.attr in facades:
                    types[target.id] = facades[value.attr]
        # Resolve every attribute chain rooted at a tracked local.
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Attribute):
                continue
            chain: list[str] = []
            cur = sub
            while isinstance(cur, ast.Attribute):
                chain.append(cur.attr)
                cur = cur.value
            if not (isinstance(cur, ast.Name) and cur.id in types):
                continue
            chain.append(cur.id)
            chain.reverse()  # [var, hop1, hop2, ...]
            typ = types[chain[0]]
            for hop in chain[1:]:
                if typ is _divoom_mod.Divoom:
                    if hop not in facades and not has_member(typ, hop):
                        failures.append(
                            f"{mod_name}: `Divoom.{hop}` names no facade attr or method"
                        )
                        break
                    typ = facades.get(hop, typ)
                elif not has_member(typ, hop):
                    failures.append(
                        f"{mod_name}: `{typ.__name__}.{hop}` does not exist"
                    )
                    break
                else:
                    nxt = getattr(typ, hop, None)
                    typ = nxt if isinstance(nxt, type) else typ


def check_imports(failures: list[str]) -> int:
    """Every module an example names must still be importable."""
    count = 0
    for path in sorted(EXAMPLES.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    count += 1
                    try:
                        importlib.import_module(a.name)
                    except Exception as e:
                        failures.append(f"{path.name}: import {a.name}: {e!r}")
            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                count += 1
                try:
                    importlib.import_module(node.module)
                except Exception as e:
                    failures.append(f"{path.name}: from {node.module}: {e!r}")
    return count


def main() -> int:
    failures: list[str] = []
    facades = facade_map()
    if scope_is_empty("examples", len(facades), unit="facade wirings"):
        return 1
    n_imports = check_imports(failures)
    modules = [f"examples.{p.stem}" for p in sorted(EXAMPLES.glob("*.py"))]
    for mod_name in modules:
        check_module(mod_name, facades, failures)
    if scope_is_empty("examples", len(modules), unit="example modules"):
        return 1
    if failures:
        err(f"[examples] {len(failures)} problem(s)")
        for fl in failures:
            info(fl)
        return 1
    ok(f"[examples] OK — {len(modules)} modules import, "
       f"{n_imports} imports + facade chains resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
