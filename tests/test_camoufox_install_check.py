"""The camoufox install check must be able to FAIL, in both absent shapes.

`tools/check_camoufox_installed.py` exists because `python -m camoufox fetch`
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

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKER = REPO_ROOT / "tools" / "check_camoufox_installed.py"


def _run_checker_under(preamble: str) -> subprocess.CompletedProcess[str]:
    """Run the REAL checker script in a subprocess after `preamble` has run.

    A subprocess keeps the import-system surgery out of the test session, and
    runs the script unmodified rather than importing a patched copy of it.
    """
    src = textwrap.dedent(preamble) + textwrap.dedent(
        f'''
        import runpy, sys
        sys.argv = ["check_camoufox_installed.py"]
        try:
            runpy.run_path({str(CHECKER)!r}, run_name="__main__")
        except SystemExit as exc:
            sys.exit(exc.code)
        '''
    )
    return subprocess.run(
        [sys.executable, "-c", src], capture_output=True, text=True, cwd=REPO_ROOT, timeout=120
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


def test_passes_when_a_browser_is_really_installed() -> None:
    """It must not over-reject: a real install reports the version and exits 0.

    Without this the checker could hard-fail every run and still look like a
    working gate -- which would block CI permanently instead of catching a
    silent install.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("_camoufox_check", CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # loaded by path: tools/ is not a package

    if module.installed_version() is None:
        pytest.skip("no camoufox browser on this machine — nothing to assert")
    result = _run_checker_under("pass\n")
    assert result.returncode == 0, f"a real install must pass: {result.stderr}"
    assert "camoufox browser present" in result.stdout
