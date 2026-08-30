#!/usr/bin/env python3
"""check_positional_args.py — the R67/C7 gate.

`device_call` builds its numeric positional list with `filter_map(as_i64)`,
which **compacts**: strings, bools and lists are dropped, so `args[i]` is the
i-th NUMBER, not the i-th ARGUMENT. A handler that reads `args[N]` while a
non-numeric parameter sits at or before position N reads a neighbouring
argument's value — with complete confidence, and only when the caller passes
positionally, which is why keyword callers never noticed.

That shipped for months. `display.show_light` transmitted the ambient MODE as
the brightness; `control.set_hot(True)` sent FALSE; `design.set_eq` read the
wrong number as `mode`; `send_net_temp_disp` lost `time_minutes` entirely; and
both sleep handlers mis-mapped several fields. Found only by a wire trace.

The fix for a flagged handler is `pos_i64` / `pos_bool` from
`divoomd/src/device_call/args.rs`, which read TRUE positions out of `raw_args`.

This gate pairs the Rust arms with the Python signatures they implement and
fails when a compacted read is shadowed by a non-numeric parameter. Only TYPE
ANNOTATIONS are used — an earlier version also guessed from parameter names and
produced false positives, which is how a gate stops being believed.
"""
from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _srcscan import strip_rust_comments  # noqa: E402
from _tui import err, info, ok  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
RUST_DIR = REPO / "divoomd" / "src" / "device_call"
PY_DIR = REPO / "divoom_lib"

# Annotations that are NOT a single JSON number, and therefore vanish from the
# compacted list.
#
# `None` is deliberately ABSENT: `int | None` is still a number when a caller
# passes one, and treating Optional as non-numeric flagged two safe handlers.
# A gate that cries wolf stops being read.
NON_NUMERIC = ("str", "bytes", "bool", "list", "dict", "Path", "tuple")

# MCP tool wrappers share method NAMES with device methods but have their own
# signatures (`set_alarm(enabled: bool, ...)` vs the device layer's all-int
# form). Matching against the wrapper produced a false positive, so the device
# layer is the authority.
SIGNATURE_EXCLUDE = ("mcp_tools.py", "mcp_server.py")


def python_signatures() -> dict[str, list[tuple[str, str]]]:
    """method name -> [(param, annotation)], self excluded.

    A name can be defined more than once (`show_light` exists in both
    `display/__init__.py`, fully annotated, and `display/light.py`, bare). This
    used to be `rglob` + `setdefault` — FIRST ONE WINS, over an unsorted
    directory walk — so the winner depended on filesystem order: APFS handed
    back the unannotated one and the gate passed, ext4 handed back the
    annotated one and it failed. Same commit, opposite verdicts, which is how a
    CI failure became unreproducible on the machine that has to fix it.

    Deterministic now, and it prefers the definition carrying the MOST
    annotations: this gate reasons only from annotations, so the richest
    signature is the one with something to say.
    """
    sigs: dict[str, list[tuple[str, str]]] = {}
    for path in sorted(PY_DIR.rglob("*.py")):
        if "__pycache__" in str(path) or path.name in SIGNATURE_EXCLUDE:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            params = [
                (a.arg, ast.unparse(a.annotation) if a.annotation else "")
                for a in node.args.args[1:]
            ]
            annotated = sum(1 for _, ann in params if ann)
            prev = sigs.get(node.name)
            if prev is None or annotated > sum(1 for _, ann in prev if ann):
                sigs[node.name] = params
    return sigs


ARM_RE = re.compile(r'\n        ((?:"[a-z_.0-9]+"\s*\|?\s*)+)=>')
GET_RE = re.compile(r"\bargs\s*\.\s*get\((\d+)\)")
FIRST_RE = re.compile(r"\bargs\s*\.\s*first\(\)")


def balanced_body(src: str, start: int, hard_end: int) -> str:
    """The arm body, ending where its own braces close."""
    depth = 0
    seen = False
    for i in range(start, min(hard_end, len(src))):
        c = src[i]
        if c == "{":
            depth += 1
            seen = True
        elif c == "}":
            depth -= 1
            if seen and depth <= 0:
                return src[start:i + 1]
    return src[start:hard_end]


def rust_arms() -> list[tuple[str, list[str], set[int], Path]]:
    """(primary method, all aliases, compacted indices read, file)."""
    out = []
    for path in sorted(RUST_DIR.rglob("*.rs")):
        src = strip_rust_comments(path.read_text(encoding="utf-8"))
        marks = [(m.start(), m.end(), re.findall(r'"([a-z_.0-9]+)"', m.group(1)))
                 for m in ARM_RE.finditer(src)]
        for i, (_, end, names) in enumerate(marks):
            # Bound the body by BRACE DEPTH, not by the next arm. Taking
            # everything up to the next arm made the LAST arm in a file swallow
            # the helper functions after the match, whose `args` reads then got
            # attributed to it.
            body_end = marks[i + 1][0] if i + 1 < len(marks) else len(src)
            body = balanced_body(src, end, body_end)
            idxs = {int(g.group(1)) for g in GET_RE.finditer(body)}
            if FIRST_RE.search(body):
                idxs.add(0)
            if idxs and names:
                out.append((names[0], names, idxs, path))
    return out


def main() -> int:
    sigs = python_signatures()
    offenders = []
    checked = 0

    for method, _aliases, idxs, path in rust_arms():
        base = method.split(".")[-1]
        params = sigs.get(base)
        if params is None:
            continue
        checked += 1
        for n in sorted(idxs):
            shadow = next(
                ((pos, nm, ann) for pos, (nm, ann) in enumerate(params)
                 if pos <= n and any(t in ann for t in NON_NUMERIC)),
                None,
            )
            if shadow:
                pos, nm, ann = shadow
                offenders.append(
                    f"{path.relative_to(REPO)}: {method} reads args[{n}], but "
                    f"`{nm}: {ann}` at position {pos} is dropped from the "
                    f"compacted list — use pos_i64/pos_bool(raw_args, {n}, ...)")
                break

    if offenders:
        err(f"[positional] {len(offenders)} handler(s) index the COMPACTED args list")
        for o in offenders:
            info(o)
        return 1
    ok(f"[positional] OK — {checked} handlers read positional args safely")
    return 0


if __name__ == "__main__":
    sys.exit(main())
