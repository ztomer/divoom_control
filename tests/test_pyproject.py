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
  6. ``requirements.txt`` and ``pyproject.toml`` declare the SAME set of
     packages, in BOTH directions, with a ratcheting allowlist for the
     packages intentionally in one file only.
  7. The browser e2e drivers are declared in the ``[e2e]`` extra, not
     hardcoded in a CI workflow.
"""
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent

# ── the one-sided-difference allowlist (a RATCHET) ─────────────────────────
#
# A package intentionally declared in ONE of the two files, and why. Anything
# one-sided that is not named here is drift, not a decision.
ALLOWED_ONE_SIDED: dict[str, str] = {
    "playwright": "the [e2e] extra; CI installs the extra, not requirements.txt",
    "camoufox": "the [e2e] extra; the pinned browser driver for the e2e suites",
}


def _pkg_name(spec: str) -> str:
    """Normalised distribution name (PEP 503) of one requirement specifier.

    Handles everything the two files actually write: environment markers
    (``pywebview; sys_platform == "darwin"``), extras (``foo[gui,test]``),
    version specifiers (``pillow>=12``, ``camoufox==0.5.5``) and trailing
    comments. Normalising case and separator runs means ``pyobjc-framework-Cocoa``
    and ``pyobjc-framework-cocoa`` are the SAME key — otherwise a rename of
    case reads as a difference in both directions and hides the real one.
    """
    name = spec.split(";")[0].strip()          # environment marker
    name = name.split("[")[0].strip()          # extras
    name = re.split(r"[<>=!~\s\[]", name, maxsplit=1)[0].strip()
    return re.sub(r"[-_.]+", "-", name).lower()


def _pyproject_packages() -> set[str]:
    """Every distribution pyproject.toml declares: core deps + every extra.

    ``dev = ["divoom-control[gui,test]"]`` is a self-reference, not a
    declaration of a third package, so the project's own name is dropped —
    it would otherwise show up as a phantom requirement in both directions.
    """
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    project = data["project"]
    specs: list[str] = list(project.get("dependencies", []))
    for entries in project.get("optional-dependencies", {}).values():
        specs.extend(entries)
    return {_pkg_name(s) for s in specs} - {_pkg_name(project["name"])}


def _requirements_packages() -> set[str]:
    """Every distribution requirements.txt declares, comments skipped."""
    packages: set[str] = set()
    for raw in (REPO_ROOT / "requirements.txt").read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name = _pkg_name(line)
        if name:
            packages.add(name)
    return packages


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
    """requirements.txt and pyproject.toml declare the SAME package set.

    requirements.txt is the CI bootstrap file; pyproject.toml is authoritative
    (its own header says it replaces keeping requirements.txt in sync with the
    install instructions). Two files describing one dependency set drift, so
    they must hold the same set.

    This was ONE-DIRECTIONAL: it asserted only ``pyproject_pkgs - reqtxt_pkgs``
    is empty — "requirements.txt is a superset" — which is structurally blind
    to the two failures that actually happened. ``pyobjc-framework-Cocoa`` (the
    ``gui`` extra, AppKit) was in pyproject and missing here, and ``numpy`` /
    ``psutil`` were here with no importer and no declaration anywhere. A
    superset check passes on all three. It is now a two-way comparison.
    """
    pyproject_pkgs = _pyproject_packages()
    reqtxt_pkgs = _requirements_packages()

    only_pyproject = pyproject_pkgs - reqtxt_pkgs
    only_reqtxt = reqtxt_pkgs - pyproject_pkgs

    used: set[str] = set()
    unexplained: list[str] = []
    for name in sorted(only_pyproject | only_reqtxt):
        if name in ALLOWED_ONE_SIDED:
            used.add(name)
        else:
            unexplained.append(name)

    # A fixed difference must take its allowlist entry with it. An entry that
    # describes no live difference is a hole standing open for the next one --
    # the same ratchet property tools/check_gui_is_a_client.py enforces on its
    # own ALLOWLIST, and the one that is easy to omit.
    stale = sorted(set(ALLOWED_ONE_SIDED) - used)
    assert not stale, (
        f"ALLOWED_ONE_SIDED entries that no longer describe a real difference: "
        f"{stale} — the two files agree about them now, so delete them"
    )

    assert not unexplained, (
        "requirements.txt and pyproject.toml have drifted; a package in exactly "
        f"one of them with no ALLOWED_ONE_SIDED entry is a defect.\n"
        f"  pyproject.toml only: {sorted(only_pyproject - set(used))}\n"
        f"  requirements.txt only: {sorted(only_reqtxt - set(used))}\n"
        f"  (one-sided on purpose: {sorted(used)})\n"
        f"  Fix the drift, or name the package in ALLOWED_ONE_SIDED with the "
        f"reason it belongs in one file only."
    )


# ── package discovery ─────────────────────────────────────────────────


def test_pyproject_packages_include_divoom_lib() -> None:
    p = REPO_ROOT / "pyproject.toml"
    data = tomllib.loads(p.read_text())
    find = data.get("tool", {}).get("setuptools", {}).get("packages", {}).get("find", {})
    include = find.get("include", [])
    # Patterns are wildcards ("divoom_lib*", "gui*") to include sub-packages.
    assert any("divoom_lib" in pat for pat in include)
    assert any("gui" in pat for pat in include)


def test_pyproject_package_data_ships_web_ui_and_no_native_binary() -> None:
    """The wheel ships the web UI, and no compiled artifact.

    Inverted on 2026-09-25 (phase L4). This used to assert `*.dylib` and `*.so`
    were shipped as package data for `divoom_lib` — the C encoder library, built
    per platform and committed to the tree. Those globs are gone with the library,
    and the assertion is now that they STAY gone: a per-platform binary in a
    wheel is wrong on every platform but the one that built it, which is the
    whole reason the C left.
    """
    p = REPO_ROOT / "pyproject.toml"
    data = tomllib.loads(p.read_text())
    pd = data.get("tool", {}).get("setuptools", {}).get("package-data", {})
    assert "web_ui/*" in pd.get("divoom_gui", [])
    shipped = " ".join(pd.get("divoom_lib", []))
    for glob in ("*.dylib", "*.so", "*.dll"):
        assert glob not in shipped, (
            f"pyproject still ships {glob} as package data: the C encoder library "
            "is deleted and a compiled artifact has no place in a wheel"
        )


def test_browser_driver_declared_in_the_extra_not_literal_in_ci() -> None:
    """The e2e driver versions live in ONE place: the ``[e2e]`` extra.

    ``playwright`` and ``camoufox`` were declared nowhere, yet 15 GUI e2e suites
    and ``scripts/gui_pov.py`` import them; they came only from a literal in
    ``.github/workflows/tests.yml``. That is the whole reason
    ``scripts/py_ci.sh`` could only WARN when the browser was missing — nothing
    declared the dependency, so nothing could hold it. A second copy of the pin
    in a workflow is the same drift the parity test above exists to prevent, one
    file further away and with nothing checking it, so the literal is banned
    rather than merely discouraged.

    Asserted in both directions: no workflow may pin the drivers, and the
    workflow that runs the browser suites must still install the extra, so
    deleting the install cannot pass as "nothing to pin any more".
    """
    workflows = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    offenders: list[str] = []
    for wf in workflows:
        for lineno, line in enumerate(wf.read_text().splitlines(), start=1):
            if re.search(r"(camoufox|playwright)\s*==", line):
                offenders.append(f"{wf.name}:{lineno}: {line.strip()}")

    assert not offenders, (
        "browser driver versions are hardcoded in a workflow; declare them in "
        "the [e2e] extra in pyproject.toml so there is exactly one copy:\n  "
        + "\n  ".join(offenders)
    )

    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    e2e = data["project"].get("optional-dependencies", {}).get("e2e", [])
    declared = {_pkg_name(s) for s in e2e}
    assert declared == {"playwright", "camoufox"}, (
        f"the [e2e] extra must declare playwright + camoufox, got {sorted(declared)}"
    )
    camoufox_spec = next(s for s in e2e if _pkg_name(s) == "camoufox")
    assert "==" in camoufox_spec, (
        f"camoufox must stay pinned in the extra, got {camoufox_spec!r}: the "
        "pin is what makes a red run mean a code change"
    )

    ci = (REPO_ROOT / ".github" / "workflows" / "tests.yml").read_text()
    assert ".[e2e]" in ci, (
        "no workflow installs the [e2e] extra, so the browser suites cannot "
        "have a browser — they would skip and read as green"
    )


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
