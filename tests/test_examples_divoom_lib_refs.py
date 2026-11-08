"""Every `divoom_lib` name the examples use exists in the real package (D.LEGACY).

The class: a shipped module drops a name (L4c removed the Python encoder from
`divoom_lib/framing.py`) and a caller outside the shipped packages keeps using
it. `examples/divoom_legacy` called `framing.encode_ios_le_payload` for a
month after it was gone, and every legacy test mocked the send, so nothing
imported the dead attribute. This reads every module under `examples/` with
`ast` -- no import, so a lazy function-level import is seen too -- and resolves
each `from divoom_lib.x import y`, `import divoom_lib.x`, and
`<alias>.<attr>` hop on a name bound to a `divoom_lib` module against the
REAL package.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "examples"


def _resolve(dotted: str) -> object | None:
    parts = dotted.split(".")
    for cut in range(len(parts), 0, -1):
        try:
            obj: object = importlib.import_module(".".join(parts[:cut]))
        except ModuleNotFoundError:
            continue
        for attr in parts[cut:]:
            if not hasattr(obj, attr):
                try:
                    obj = importlib.import_module(f"{obj.__name__}.{attr}")  # type: ignore[attr-defined]
                except ModuleNotFoundError, AttributeError:
                    return None
            else:
                obj = getattr(obj, attr)
        return obj
    return None


def references(source: str) -> list[tuple[int, str]]:
    """(line, dotted name) for every divoom_lib reference in one module."""
    tree = ast.parse(source)
    aliases: dict[str, str] = {}
    refs: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module == "divoom_lib" or node.module.startswith("divoom_lib."):
                for name in node.names:
                    dotted = f"{node.module}.{name.name}"
                    refs.append((node.lineno, dotted))
                    aliases[name.asname or name.name] = dotted
        elif isinstance(node, ast.Import):
            for name in node.names:
                if name.name.split(".")[0] == "divoom_lib":
                    refs.append((node.lineno, name.name))
                    aliases[name.asname or name.name.split(".")[0]] = name.asname and name.name or "divoom_lib"
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
            base = _resolve(aliases[node.value.id])
            if base is not None and type(base).__name__ == "module":
                refs.append((node.lineno, f"{aliases[node.value.id]}.{node.attr}"))
    return refs


def unresolved(root: Path) -> list[str]:
    misses: list[str] = []
    for path in sorted(root.rglob("*.py")):
        for line, dotted in references(path.read_text(encoding="utf-8")):
            if _resolve(dotted) is None:
                misses.append(f"{path.relative_to(REPO)}:{line}: {dotted}")
    return misses


def test_every_examples_reference_to_divoom_lib_resolves() -> None:
    misses = unresolved(EXAMPLES)
    assert not misses, "examples/ names divoom_lib attributes that do not exist:\n" + "\n".join(misses)


def test_the_scan_sees_a_dead_attribute_and_a_lazy_import(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text(
        "from divoom_lib import framing\n"
        "def send(p):\n"
        "    from divoom_lib.framing import gone_function\n"
        "    return framing.encode_ios_le_payload(p)\n"
        "ok = framing.parse_basic_protocol_frames\n"
    )
    misses = [m.split(": ", 1)[1] for m in unresolved_in(tmp_path)]
    assert misses == ["divoom_lib.framing.gone_function", "divoom_lib.framing.encode_ios_le_payload"]


def test_the_scan_is_not_empty() -> None:
    total = sum(len(references(p.read_text(encoding="utf-8"))) for p in EXAMPLES.rglob("*.py"))
    assert total > 50, f"only {total} divoom_lib references found under examples/; the scan is blind"


def unresolved_in(root: Path) -> list[str]:
    misses: list[str] = []
    for path in sorted(root.rglob("*.py")):
        for line, dotted in sorted(references(path.read_text(encoding="utf-8"))):
            if _resolve(dotted) is None:
                misses.append(f"{path.name}:{line}: {dotted}")
    return misses
