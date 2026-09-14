"""Production never imports the retired library.

`divoomd` (Rust) is the sole device owner. The CLI/GUI/MCP are thin daemon
clients (`DaemonDeviceProxy`). The direct-to-device Python library -- the
`Divoom` facade, its transports, `wall`, `monthly_best_daemon`, every command
group -- was retired to `examples/divoom_legacy/` on 2026-09-14 (77 modules
the production import closure never reached). What stays in `divoom_lib` is
the shared core (framing, models, transport interface, auth, native_lib) the
daemon clients and the legacy package both use.

So the rule is one line: no production module imports `divoom_legacy`, or
instantiates `Divoom(...)`, or subclasses `DivoomProtocol`. Scope is
AST-based, so docstrings and comments never trip it. Seed: zero hits.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROD_DIRS = [REPO / "divoom_gui", REPO / "divoom_client", REPO / "nowplaying", REPO / "divoom_lib"]
RETIRED_PKG = "divoom_legacy"


def find_facade_uses(source: str) -> list[str]:
    """Return human-readable descriptions of retired-library uses in `source`."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"unparseable: {exc}"]
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Divoom":
            hits.append(f"line {node.lineno}: instantiates Divoom(...)")
        elif isinstance(node, ast.ClassDef):
            for base in node.bases:
                if (isinstance(base, ast.Name) and base.id == "DivoomProtocol") or (
                    isinstance(base, ast.Attribute) and base.attr == "DivoomProtocol"
                ):
                    hits.append(f"line {node.lineno}: subclasses DivoomProtocol")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == RETIRED_PKG or mod.startswith(RETIRED_PKG + "."):
                hits.append(f"line {node.lineno}: imports retired {mod}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == RETIRED_PKG or alias.name.startswith(RETIRED_PKG + "."):
                    hits.append(f"line {node.lineno}: imports retired {alias.name}")
    return hits


def _prod_files() -> list[Path]:
    files: list[Path] = []
    for directory in PROD_DIRS:
        if directory.exists():
            files.extend(sorted(directory.rglob("*.py")))
    return files


def test_production_never_imports_the_retired_library() -> None:
    files = _prod_files()
    assert len(files) > 50, "the production scope moved; fix the paths"
    violations: list[str] = []
    for path in files:
        for hit in find_facade_uses(path.read_text()):
            violations.append(f"{path.relative_to(REPO)}: {hit}")
    assert violations == [], "retired-library use in production:\n" + "\n".join(violations)


def test_scanner_sees_instantiation() -> None:
    assert find_facade_uses('divoom = Divoom(mac="...")\n') != []


def test_scanner_sees_subclass() -> None:
    assert find_facade_uses("class P(DivoomProtocol):\n    pass\n") != []


def test_scanner_sees_retired_imports() -> None:
    assert find_facade_uses("from divoom_legacy.wall import Wall\n") != []
    assert find_facade_uses("from divoom_legacy import Divoom\n") != []
    assert find_facade_uses("import divoom_legacy.display.light\n") != []
    # The retained core is not retired.
    assert find_facade_uses("from divoom_lib import framing, models\n") == []


def test_scanner_ignores_docs_comments_and_daemon_client() -> None:
    source = (
        '"""\nUsage:\n    divoom = Divoom(mac="...")\n"""\n'
        "# divoom = Divoom(mac=\"...\")\n"
        "proxy = DaemonDeviceProxy(client)\n"
        "reply = client.wall_configure(slots)\n"
        "server.tools = build_tool_catalog(proxy)\n"
    )
    assert find_facade_uses(source) == []
