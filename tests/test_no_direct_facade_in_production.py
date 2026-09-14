"""No direct-facade use in production code.

`divoomd` (Rust) is the sole device owner. The CLI/GUI/MCP are thin daemon
clients (`DaemonDeviceProxy`) — they must never instantiate the legacy
direct-connection facade (`Divoom(...)`), subclass its protocol
(`DivoomProtocol`), or import the orphan device-I/O modules (`wall`,
`monthly_best_daemon`, both ported to `divoomd/src/`).

Scope is AST-based, so docstrings and comments never trip it (the old
`mcp_server.py` usage example named `Divoom(mac=...)` in prose while the code
had already cut over — that docstring is now fixed, and this gate would not
have seen it either way). What remains in `divoom_lib` (transports, C ext,
`native/`, `fonts/`, pure helpers) plus `examples/` is the retirement backlog
itself and is excluded here; `tests/` may still drive the facade until they
are re-targeted at the proxy.

Seed: zero production hits (verified 2026-09-14). Any new one fails.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROD_DIRS = [REPO / "divoom_gui", REPO / "divoom_client"]
PROD_FILES = [
    REPO / "divoom_lib" / name
    for name in ("cli.py", "cli_commands.py", "mcp_server.py", "mcp_tools.py")
]
ORPHAN_MODULES = {"divoom_lib.wall", "divoom_lib.monthly_best_daemon"}


def find_facade_uses(source: str) -> list[str]:
    """Return human-readable descriptions of direct-facade uses in `source`."""
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
        elif isinstance(node, ast.ImportFrom) and (node.module or "") in ORPHAN_MODULES:
            hits.append(f"line {node.lineno}: imports orphan {node.module}")
        elif isinstance(node, ast.ImportFrom) and (node.module or "") == "divoom_lib":
            for alias in node.names:
                if alias.name in ("wall", "monthly_best_daemon"):
                    hits.append(f"line {node.lineno}: imports orphan divoom_lib.{alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in ORPHAN_MODULES:
                    hits.append(f"line {node.lineno}: imports orphan {alias.name}")
    return hits


def _prod_files() -> list[Path]:
    files: list[Path] = list(PROD_FILES)
    for directory in PROD_DIRS:
        files.extend(sorted(directory.rglob("*.py")))
    return files


def test_no_direct_facade_in_production() -> None:
    violations: list[str] = []
    for path in _prod_files():
        if not path.exists():
            continue
        for hit in find_facade_uses(path.read_text()):
            violations.append(f"{path.relative_to(REPO)}: {hit}")
    assert violations == [], "direct-facade use in production:\n" + "\n".join(violations)


def test_scanner_sees_instantiation() -> None:
    assert find_facade_uses('divoom = Divoom(mac="...")\n') != []


def test_scanner_sees_subclass() -> None:
    assert find_facade_uses("class P(DivoomProtocol):\n    pass\n") != []


def test_scanner_sees_orphan_import() -> None:
    assert find_facade_uses("from divoom_lib.wall import Wall\n") != []
    assert find_facade_uses("from divoom_lib import monthly_best_daemon\n") != []


def test_scanner_ignores_docs_comments_and_daemon_client() -> None:
    source = (
        '"""\nUsage:\n    divoom = Divoom(mac="...")\n"""\n'
        "# divoom = Divoom(mac=\"...\")\n"
        "proxy = DaemonDeviceProxy(client)\n"
        "reply = client.wall_configure(slots)\n"
        "server.tools = build_tool_catalog(proxy)\n"
    )
    assert find_facade_uses(source) == []
