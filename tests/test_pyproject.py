"""
R14 §4 — packaging tests.

The full `pip install -e .` is verified manually in dev. These tests
guard the things that have to stay true in CI:

  1. ``pyproject.toml`` exists and parses as valid TOML.
  2. ``pyproject.toml`` declares the ``divoom-control`` entry point.
  3. The CLI module's ``main()`` is callable (the entry point
     ``divoom-control = divoom_lib.cli:main`` would crash otherwise).
  4. The package list matches what the repo ships (no stale entries).
  5. The legacy shell wrapper ``./divoom-control`` is still in place
     so in-tree dev still works without a pip install.
  6. ``requirements.txt`` is still in sync with ``dependencies`` in
     ``pyproject.toml`` (no drift).
"""
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


# ── pyproject.toml basics ──────────────────────────────────────────────


def test_pyproject_toml_exists() -> None:
    p = REPO_ROOT / "pyproject.toml"
    assert p.exists(), f"missing: {p}"


def test_pyproject_toml_is_valid_toml() -> None:
    p = REPO_ROOT / "pyproject.toml"
    data = tomllib.loads(p.read_text())
    assert "project" in data
    assert "build-system" in data


def test_pyproject_project_metadata() -> None:
    p = REPO_ROOT / "pyproject.toml"
    data = tomllib.loads(p.read_text())
    proj = data["project"]
    assert proj["name"] == "divoom-control"
    # version is a positive semver-ish string
    v = proj["version"]
    assert re.match(r"^\d+\.\d+\.\d+", v), f"bad version: {v}"
    assert proj["requires-python"].startswith(">=")


# ── entry points ──────────────────────────────────────────────────────


def test_pyproject_declares_cli_entry_point() -> None:
    p = REPO_ROOT / "pyproject.toml"
    data = tomllib.loads(p.read_text())
    scripts = data["project"].get("scripts", {})
    assert "divoom-control" in scripts
    assert scripts["divoom-control"] == "divoom_lib.cli:main"


def test_cli_main_callable() -> None:
    """The entry point must point at a callable."""
    from divoom_lib import cli
    assert callable(cli.main)


# ── dependencies ──────────────────────────────────────────────────────


def test_pyproject_core_dependencies() -> None:
    """The required core deps are declared."""
    p = REPO_ROOT / "pyproject.toml"
    data = tomllib.loads(p.read_text())
    deps = data["project"].get("dependencies", [])
    dep_names = [d.split(";")[0].split(">=")[0].split("==")[0].strip() for d in deps]
    for must_have in ("bleak", "aiohttp", "pillow"):
        assert must_have in dep_names, f"missing core dep: {must_have}"


def test_pyproject_gui_extra_is_darwin_only() -> None:
    """The GUI extra must be macOS-only; ``pywebview`` is darwin-only."""
    p = REPO_ROOT / "pyproject.toml"
    data = tomllib.loads(p.read_text())
    extras = data["project"].get("optional-dependencies", {})
    gui = extras.get("gui", [])
    # The string "pywebview" must appear with a darwin marker.
    has_pywebview = any("pywebview" in d for d in gui)
    assert has_pywebview, "pywebview must be in the [gui] extra"
    # And at least one entry must be gated on darwin.
    darwin_gated = any("sys_platform" in d and "darwin" in d for d in gui)
    assert darwin_gated, "gui extra must be gated on sys_platform == 'darwin'"


def test_requirements_txt_still_in_sync() -> None:
    """The legacy requirements.txt is still required by some docs /
    CI scripts; make sure it doesn't drift from pyproject.toml."""
    p = REPO_ROOT / "pyproject.toml"
    data = tomllib.loads(p.read_text())
    deps = data["project"].get("dependencies", [])
    pyproject_pkgs = {d.split(";")[0].split(">=")[0].split("==")[0].strip() for d in deps}
    reqtxt_pkgs = set()
    for line in (REPO_ROOT / "requirements.txt").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # strip markers (after ;)
        line = line.split(";")[0]
        # strip version specifiers
        line = re.split(r"[><=!~]", line, maxsplit=1)[0].strip()
        # drop comments that survive
        if not line or line.startswith("#"):
            continue
        reqtxt_pkgs.add(line)
    # requirements.txt is a *superset* — it includes test deps.
    # The core deps in pyproject must all be in requirements.txt.
    missing = pyproject_pkgs - reqtxt_pkgs
    assert not missing, f"requirements.txt missing core deps: {missing}"


# ── package discovery ─────────────────────────────────────────────────


def test_pyproject_packages_include_divoom_lib() -> None:
    p = REPO_ROOT / "pyproject.toml"
    data = tomllib.loads(p.read_text())
    find = data.get("tool", {}).get("setuptools", {}).get("packages", {}).get("find", {})
    include = find.get("include", [])
    # Patterns are wildcards ("divoom_lib*", "gui*") to include sub-packages.
    assert any("divoom_lib" in pat for pat in include)
    assert any("gui" in pat for pat in include)


def test_pyproject_package_data_includes_dylib_and_web_ui() -> None:
    p = REPO_ROOT / "pyproject.toml"
    data = tomllib.loads(p.read_text())
    pd = data.get("tool", {}).get("setuptools", {}).get("package-data", {})
    # R17: the native lib ships with divoom_lib (its true home); web_ui with gui.
    # R20: per-platform extensions are all shipped (.dylib/.so/.dll).
    assert "*.dylib" in pd.get("divoom_lib", [])
    assert "*.so" in pd.get("divoom_lib", [])
    assert "web_ui/*" in pd.get("divoom_gui", [])


# ── legacy shell wrapper ──────────────────────────────────────────────


def test_shell_wrapper_still_present() -> None:
    """The in-tree ``./divoom-control`` shell wrapper is kept for
    development without an editable install."""
    wrapper = REPO_ROOT / "divoom-control"
    assert wrapper.exists()
    # It should be executable on macOS/Linux (chmod +x).
    import stat
    mode = wrapper.stat().st_mode
    assert mode & stat.S_IXUSR, "./divoom-control is not executable"


def test_shell_wrapper_invoces_python_module() -> None:
    """The wrapper must end up calling ``python -m divoom_lib.cli``."""
    wrapper = (REPO_ROOT / "divoom-control").read_text()
    assert "divoom_lib.cli" in wrapper
