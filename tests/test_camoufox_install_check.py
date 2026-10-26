"""The camoufox install check must be able to FAIL, in both absent shapes.

`tools/camoufox_installed.py` exists because `python -m camoufox fetch`
exits 0 when it installs nothing: CI run 32654312489 hit GitHub's
unauthenticated API rate limit, printed three 403s and "Synced 0 versions from
0 repos.", and still reported its workflow step green. The failure surfaced
later inside pytest, reading as a test regression instead of a failed install.

That makes this checker a GATE, and an unverified gate is exactly the defect it
was written to close -- so these tests prove it bites. Both directions are
covered deliberately: a checker that always failed would be just as useless as
one that always passed, and only the accept direction proves it is not.

The absent state is driven through camoufox's OWN signals rather than a stub of
our function, for the reason the sibling browser-guard suite documents: stubbing
your own probe proves your branch works without proving reality reaches it.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKER = REPO_ROOT / "tools" / "camoufox_installed.py"


def _run_checker_under(preamble: str) -> subprocess.CompletedProcess[str]:
    """Run the REAL checker script in a subprocess after `preamble` has run.

    A subprocess keeps the import-system surgery out of the test session, and
    runs the script unmodified rather than importing a patched copy of it.
    """
    src = textwrap.dedent(preamble) + textwrap.dedent(
        f'''
        import runpy, sys
        sys.argv = ["camoufox_installed.py"]
        try:
            runpy.run_path({str(CHECKER)!r}, run_name="__main__")
        except SystemExit as exc:
            sys.exit(exc.code)
        '''
    )
    return subprocess.run(
        [sys.executable, "-c", src], capture_output=True, text=True, cwd=REPO_ROOT, timeout=120, stdin=subprocess.DEVNULL,
        check=False,
    )


def test_fails_when_camoufox_reports_no_active_install() -> None:
    """The exact shape of the CI failure: package present, browser absent."""
    pytest.importorskip("camoufox.multiversion")
    result = _run_checker_under(
        '''
        import camoufox.multiversion as mv
        mv.get_active_path = lambda: None
        '''
    )
    assert result.returncode != 0, "a missing browser binary must fail the check"
    assert "NOT installed" in result.stderr


def test_fails_when_the_camoufox_package_is_absent() -> None:
    """A machine without the package at all must fail too, not crash."""
    result = _run_checker_under(
        '''
        import sys
        from importlib.abc import MetaPathFinder

        class _Blocker(MetaPathFinder):
            def find_spec(self, name, path=None, target=None):
                if name == "camoufox" or name.startswith("camoufox."):
                    raise ImportError(f"blocked: {name}")
                return None

        sys.meta_path.insert(0, _Blocker())
        for _mod in [k for k in sys.modules if k.startswith("camoufox")]:
            del sys.modules[_mod]
        '''
    )
    assert result.returncode != 0, "an absent camoufox package must fail the check"
    assert "NOT installed" in result.stderr


# The active build is faked through camoufox's own pkgman, not by stubbing the
# checker: these tests are about the checker's verdict on a build, and they must
# not depend on which build the MACHINE-WIDE cache happens to have active. The
# old accept test asked the real cache, so when another project switched it to
# 156.0.1-beta.36 on 2026-10-10 every push from this repo was refused.
_ACTIVE_BUILD = """
import camoufox.pkgman as pkgman
pkgman.installed_verstr = lambda: {build!r}
"""


def _checker():
    import importlib.util

    spec = importlib.util.spec_from_file_location("_camoufox_check", CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # loaded by path: tools/ is not a package
    return module


def _pinned_build() -> str:
    return _checker().pinned_build()


def test_passes_when_the_pinned_build_is_active() -> None:
    """It must not over-reject: the pinned build reports its version and exits 0.

    Without this the checker could hard-fail every run and still look like a
    working gate -- which would block CI permanently instead of catching a
    silent install.
    """
    pytest.importorskip("camoufox.pkgman")
    result = _run_checker_under(_ACTIVE_BUILD.format(build=_pinned_build()))
    assert result.returncode == 0, f"the pinned build must pass: {result.stderr}"
    assert "camoufox browser present" in result.stdout


def test_fails_when_another_build_is_active_and_names_the_shared_cache() -> None:
    """A switched build is refused, and the refusal says whose state it is.

    The active build is machine-wide, so the message names the cache and both
    ways out (move the pin after running the suites, or restore the build for
    every project), instead of reading as this repo's regression.
    """
    pytest.importorskip("camoufox.pkgman")
    result = _run_checker_under(_ACTIVE_BUILD.format(build="0.0.0-beta.0"))
    assert result.returncode != 0, "a build other than the pin must fail the check"
    assert f"camoufox browser is 0.0.0-beta.0, expected {_pinned_build()}" in result.stderr
    assert "machine-wide" in result.stderr
    assert f"camoufox set {_checker().pinned_spec()}" in result.stderr


# ── One declared build (P1.13, 2026-10-19) ─────────────────────────────────
# CI pinned beta.34 while the dev machine ran beta.39, because the build was a
# literal in three places and the machine cache was an undeclared fourth. The
# pin now lives in `.camoufox-build` only; these tests hold that shape.

BUILD_LITERAL = re.compile(r"\b\d+\.\d+(?:\.\d+)?-(?:alpha|beta)\.\d+\b")


def test_the_pin_file_is_the_expected_build_and_the_spec_ci_installs() -> None:
    """`--spec` prints the pin verbatim: what CI fetches is what the gate requires."""
    pin = (REPO_ROOT / ".camoufox-build").read_text().strip()
    result = subprocess.run(
        [sys.executable, str(CHECKER), "--spec"],
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=60, stdin=subprocess.DEVNULL, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == pin
    assert pin.endswith("/" + _pinned_build())


@pytest.mark.parametrize(
    "content",
    ["", "156.0.1-beta.39\n", "official/nightly/156.0.1-beta.39\n", "official/stable/1.0-beta.1\nofficial/stable/1.0-beta.2\n"],
)
def test_a_malformed_pin_is_refused_not_defaulted(tmp_path: Path, content: str) -> None:
    """No fallback build: a default here would be a second copy of the pin."""
    pin = tmp_path / ".camoufox-build"
    pin.write_text(content)
    checker = _checker()
    with pytest.raises(checker.PinError):
        checker.pinned_spec(pin)


def test_the_workflow_installs_the_pin_and_runs_the_gates_script() -> None:
    """CI reads the pin through the checker and runs the same script as the local gate."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "tests.yml").read_text()
    assert 'SPEC="$(python3 tools/camoufox_installed.py --spec)"' in workflow
    assert 'camoufox fetch "$SPEC"' in workflow and 'camoufox set "$SPEC"' in workflow
    assert "./scripts/browser_e2e.sh" in workflow
    gatesrc = (REPO_ROOT / ".gatesrc").read_text()
    steps = re.search(r"^GOH_CI_STEPS='([^']*)'", gatesrc, re.MULTILINE)
    assert steps is not None
    assert "./scripts/browser_e2e.sh" in steps.group(1).split(":")


def _code_string_literals(path: Path) -> list[str]:
    """String constants in a Python file's CODE, docstrings excluded (they carry history)."""
    tree = ast.parse(path.read_text())
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)
    }
    return [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings
    ]


def test_no_camoufox_build_literal_outside_the_pin() -> None:
    """The CLASS gate: a build named anywhere operative is a second pin that can drift.

    Covers every file that installs, selects or checks a build -- workflows,
    shell scripts, the gate config, and the code (not docstrings) of tools/,
    scripts/ and tests/support/. Comments may record history; code may not pin.
    """
    offenders: list[str] = []
    shell_like = [*(REPO_ROOT / ".github" / "workflows").glob("*.yml"), *(REPO_ROOT / "scripts").glob("*.sh"),
                  *(REPO_ROOT / "tools").glob("*.sh"), REPO_ROOT / ".gatesrc"]
    for path in shell_like:
        for n, line in enumerate(path.read_text().splitlines(), 1):
            code = line.split("#", 1)[0] if not line.lstrip().startswith("#") else ""
            if BUILD_LITERAL.search(code):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{n}: {line.strip()}")
    for path in [*(REPO_ROOT / "tools").glob("*.py"), *(REPO_ROOT / "scripts").glob("*.py"),
                 *(REPO_ROOT / "tests" / "support").glob("*.py")]:
        offenders += [f"{path.relative_to(REPO_ROOT)}: {s!r}" for s in _code_string_literals(path) if BUILD_LITERAL.search(s)]
    assert not offenders, "camoufox build named outside .camoufox-build:\n" + "\n".join(offenders)
