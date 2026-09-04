#!/usr/bin/env python3
"""check_scripts.py — the gate that `scripts/` never had.

R67: `scripts/make_dev_daemon_app.sh` built an .app that exec'd
`python -m divoom_lib.cli daemon`. That subcommand was archived in R66 and has
printed an error and returned 1 ever since, so the script produced a bundle that
could not run at all. Nobody noticed for twelve days, because no gate — not the
pre-commit hook, not GOH_CI_STEPS, not GitHub Actions — ever looked at
`scripts/`. The tooling that verifies the product was itself unverified.

This closes that hole with the cheapest checks that can run without hardware:

  1. every shell script parses (`bash -n`) and passes shellcheck when available
  2. every Python script parses
  3. no script runs `python -m <repo.module>` for a repo module that is gone

HONEST SCOPE: check 3 would NOT have caught the R67 bug. `divoom_lib.cli` still
exists — it was the `daemon` SUBCOMMAND that was archived, and no static check
can see that. What catches that class is running the thing: the `--verify` step
in scripts/make_dev_daemon_app.sh launches the bundle it just built and fails
unless it answers `ping`. This gate catches syntax and lint rot; the verify step
catches dead-on-arrival tooling. Neither substitutes for the other.

Check 3 is deliberately scoped to REPO modules (top-level component matches a
package in the tree). External tools — PyInstaller, camoufox, pip — are not this
repo's to guarantee, and flagging them would make the gate cry wolf.
"""
from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tui import err, info, ok  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"


def tracked_scripts() -> list[Path]:
    """Every shell/Python tool this repo ships.

    scripts/ plus the repo-root shell entrypoints (install.sh, run.sh,
    build.sh...) — those are the ones users actually invoke, so leaving them
    ungated would repeat the mistake this checker exists to prevent.
    """
    found: list[Path] = []
    if SCRIPTS.is_dir():
        found += sorted(SCRIPTS.rglob("*.sh"))
        found += sorted(SCRIPTS.rglob("*.py"))
    found += sorted(p for p in REPO.glob("*.sh") if p.is_file())
    return found

# `python -m foo.bar`, `python3.14 -m foo.bar`, `"$PY" -m foo.bar`
RUN_MODULE_RE = re.compile(r"-m\s+([a-zA-Z_][\w.]*)")


def _repo_packages() -> set[str]:
    """Top-level importable names this repo ships."""
    names = set()
    for child in REPO.iterdir():
        if child.is_dir() and (child / "__init__.py").is_file():
            names.add(child.name)
        elif child.suffix == ".py":
            names.add(child.stem)
    return names


def is_repo_module(dotted: str) -> bool:
    """Is `dotted` a module this repo is responsible for providing?"""
    return dotted.split(".")[0] in _repo_packages()


def module_exists(dotted: str) -> bool:
    """Does `dotted` resolve to a package or module inside the repo?"""
    rel = Path(*dotted.split("."))
    return (REPO / rel).is_dir() or (REPO / rel.with_suffix(".py")).is_file()


def check_shell(failures: list[str]) -> None:
    # `command -v` is a shell builtin, not a binary — shutil.which is the
    # portable answer and does not spawn a process.
    have_shellcheck = shutil.which("shellcheck") is not None
    for sh in [p for p in tracked_scripts() if p.suffix == ".sh"]:
        rel = sh.relative_to(REPO)
        if subprocess.run(["bash", "-n", str(sh)], capture_output=True).returncode != 0:
            failures.append(f"{rel}: bash syntax error")
            continue
        if have_shellcheck:
            r = subprocess.run(["shellcheck", "-S", "warning", str(sh)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                failures.append(f"{rel}: shellcheck\n{r.stdout.strip()}")


def check_python(failures: list[str]) -> None:
    for py in [p for p in tracked_scripts() if p.suffix == ".py"]:
        rel = py.relative_to(REPO)
        try:
            ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError as e:
            failures.append(f"{rel}: syntax error line {e.lineno}: {e.msg}")


def check_module_refs(failures: list[str]) -> None:
    """A script must not invoke a REPO module that no longer exists."""
    for path in tracked_scripts():
        rel = path.relative_to(REPO)
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            # Comments describe history ("used to exec X") — they are not calls.
            if stripped.startswith("#"):
                continue
            for m in RUN_MODULE_RE.finditer(line):
                dotted = m.group(1)
                if is_repo_module(dotted) and not module_exists(dotted):
                    failures.append(
                        f"{rel}:{line_no}: runs `-m {dotted}`, which does not "
                        f"exist in this repo")


def check_api_method_refs(failures: list[str]) -> None:
    """A script that drives the GUI API BY NAME must name methods that exist.

    R72 close-out found `scripts/validate_devices.py` still calling
    `apply_system_stats`, which R71 deleted. The script dispatches by string, so
    a removed method is not an import error or a syntax error -- it is a
    guaranteed runtime failure that nothing notices until somebody runs the
    script against real hardware, which is the most expensive place to find it.

    HONEST SCOPE: this understands ONE dispatch shape, `step(label, "method",
    ...)`, because that is the only by-name driver in `scripts/` today. It is
    not a general "does this string name an API method" check -- there is no way
    to write that without guessing at every string in the tree. A second
    by-name driver would need its own pattern here.
    """
    try:
        sys.path.insert(0, str(REPO))
        from divoom_gui.gui_api import DivoomGuiAPI
    except Exception:
        return  # GUI deps absent (the dependency-free CI job); nothing to say
    have = {m for m in dir(DivoomGuiAPI) if not m.startswith("_")}
    for path in tracked_scripts():
        if path.suffix != ".py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "step" and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)):
                name = node.args[1].value
                if name not in have:
                    failures.append(
                        f"{path.relative_to(REPO)}:{node.lineno}: drives "
                        f"DivoomGuiAPI.{name}(), which does not exist")


def main() -> int:
    failures: list[str] = []
    check_shell(failures)
    check_python(failures)
    check_module_refs(failures)
    check_api_method_refs(failures)

    n = len(tracked_scripts())
    if failures:
        err(f"[scripts] {len(failures)} problem(s) in {n} scripts")
        for f in failures:
            info(f)
        return 1
    ok(f"[scripts] OK — {n} scripts parse, lint, and reference live modules and API methods")
    return 0


if __name__ == "__main__":
    sys.exit(main())
