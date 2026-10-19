#!/usr/bin/env python3
"""Verify the EXPECTED camoufox browser build is the active one.

`python -m camoufox fetch` exits 0 when it installs nothing. CI run 32654312489
hit GitHub's unauthenticated API rate limit, printed three 403s and "Synced 0
versions from 0 repos.", and still reported its step green; the damage surfaced
later inside pytest, looking like a test regression rather than a failed
install. A step that cannot fail is not a gate, so check the artifact rather
than the exit code.

It also checks WHICH build is active, because the build is load-bearing.
From 152.0.4-beta.29 page scripting runs in an ISOLATED WORLD, so the app's
globals read as `undefined` unless the suite explicitly reaches the main world
(tests/support/browser.py). That transition turned CI red once already, with 60
failures and no code change -- before the bridge existed. Later builds, including
the current pin, pass; see EXPECTED_BUILD below. Pinning the pip package does
not prevent the class of problem --
camoufox accepts any build in [alpha.1, 1), so a bare `fetch` takes the newest.
Checking only that *a* browser exists would let the next such change drift in
silently, which is the same failure this file was written for one level down.

The expected build is the pin in `.camoufox-build`, the ONE declaration CI and
the local gate both read. Override with CAMOUFOX_EXPECTED_BUILD when
deliberately testing another build; set it empty to skip the build check and
only require presence.

Exit 0 when the expected browser is active (prints the version), 1 when it is
absent or another build, 2 when the pin itself is unreadable. `--spec` prints
the pinned spec (repo/channel/version-build) for an installer to consume.

Used by .github/workflows/tests.yml (`--spec` for what to fetch, then as the
retry's loop condition, so a transient rate limit retries instead of poisoning
the run) and by scripts/browser_e2e.sh, which the local gate runs. scripts/py_ci.sh
consulted it until 2026-10-14 to decide whether to enforce the coverage floor;
the browser suites never fed that number, and a wrong build read as "no
browser" and switched the floor off, so it no longer does.

The active build is MACHINE-WIDE state (camoufox's cache under the user's
cache directory). Any project that uses camoufox -- the house Gemini transport
does -- can switch it with `camoufox set`, so a wrong build here is usually
another project's doing, and the message says so rather than implying this
repo broke something.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# THE PIN LIVES IN ONE FILE: `.camoufox-build` at the repo root, read here and
# nowhere else (P1.13, 2026-10-19). CI installs exactly that spec through
# `python3 tools/camoufox_installed.py --spec`, and the local gate
# (scripts/browser_e2e.sh) refuses to run the suites on any other build. Before
# it, the build was a literal in three places -- this file, the workflow's
# fetch AND set lines -- and the machine-wide cache was a fourth copy nobody
# declared, which is how CI sat on beta.34 while every local run had beta.39.
# tests/test_camoufox_install_check.py fails any build literal outside the pin.
#
# KEEP IT CURRENT. The pin exists for DETERMINISM -- a specific build, so a red
# run means a code change and not "the browser moved under you" -- NOT to hold
# the browser back. Move it in its own commit, after the browser suites pass on
# the candidate. The claim that a newer build "fails ~60 tests" is HISTORICAL:
# it was true of 152.0.4-beta.29, the build that INTRODUCED the isolated world,
# before tests/support/browser.py's main-world bridges existed.
PIN_FILE = Path(__file__).resolve().parent.parent / ".camoufox-build"

# repo/channel/version-build, the 3-part form `camoufox set` accepts.
_SPEC = re.compile(r"^(?P<repo>[a-z0-9_-]+)/(?P<channel>stable|prerelease)/(?P<build>\d+(?:\.\d+)*-(?:alpha|beta)\.\d+)$")


class PinError(ValueError):
    """The pin file is missing or does not hold one well-formed spec."""


def pinned_spec(path: Path = PIN_FILE) -> str:
    """The declared browser spec, e.g. ``official/prerelease/156.0.1-beta.39``.

    Raises :class:`PinError` rather than returning a default: a fallback build
    here would be a second copy of the pin, which is the defect this replaces.
    """
    try:
        lines = [ln.strip() for ln in path.read_text().splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    except OSError as exc:
        raise PinError(f"cannot read the camoufox pin {path}: {exc}") from exc
    if len(lines) != 1 or not _SPEC.match(lines[0]):
        raise PinError(f"{path} must hold exactly one repo/channel/version-build spec, got {lines!r}")
    return lines[0]


def pinned_build(path: Path = PIN_FILE) -> str:
    """The version-build part of the pin, the string camoufox reports as active."""
    match = _SPEC.match(pinned_spec(path))
    assert match is not None  # pinned_spec validated it
    return match["build"]


def expected_build() -> str:
    """The build to require: CAMOUFOX_EXPECTED_BUILD if set (empty = presence only), else the pin."""
    override = os.environ.get("CAMOUFOX_EXPECTED_BUILD")
    return override if override is not None else pinned_build()


def installed_version() -> str | None:
    """Return the active camoufox version string, or None if nothing is installed.

    ``installed_verstr()`` RAISES ``CamoufoxNotInstalled`` when nothing has been
    fetched -- it does not return a falsy string -- so the except branch is the
    normal "absent" path, not an exotic one.
    """
    try:
        from camoufox.pkgman import installed_verstr
    except ImportError:
        return None
    try:
        return installed_verstr() or None
    except Exception:
        return None


def cache_dir() -> str:
    """Where camoufox keeps its builds and its active-build choice."""
    try:
        from camoufox.pkgman import INSTALL_DIR
    except ImportError:
        return "camoufox's cache"
    return str(INSTALL_DIR)


def install_command(spec: str) -> str:
    """The commands that make ``spec`` the active build on this machine.

    ``fetch`` asks before installing a prerelease (``click.confirm``) and dies
    with "Aborted!" on a closed stdin, so the answer is supplied.
    """
    return f"printf 'y\\n' | python3 -m camoufox fetch {spec} && python3 -m camoufox set {spec}"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        spec = pinned_spec()
        expected = expected_build()
    except PinError as exc:
        print(f"camoufox pin unreadable: {exc}", file=sys.stderr)
        return 2
    if args == ["--spec"]:
        print(spec)
        return 0
    if args:
        print("usage: camoufox_installed.py [--spec]", file=sys.stderr)
        return 2
    version = installed_version()
    if version is None:
        print(
            "camoufox browser NOT installed — `camoufox fetch` may have exited 0 "
            "without installing anything (check for GitHub API 403 rate limits "
            f"above). The browser suites cannot run. Install the pinned build: "
            f"{install_command(spec)}",
            file=sys.stderr,
        )
        return 1
    if expected and version != expected:
        print(
            f"camoufox browser is {version}, expected {expected} (pinned in "
            f"{PIN_FILE.name}, the one source CI installs from). The active build is "
            f"machine-wide ({cache_dir()}): any project using camoufox can switch it. "
            f"Either restore the pinned build -- for every project on this machine: "
            f"{install_command(spec)} -- or run the browser suites on {version} "
            f"(scripts/browser_e2e.sh with CAMOUFOX_EXPECTED_BUILD={version}) and "
            f"move the pin in {PIN_FILE.name}, in its own commit.",
            file=sys.stderr,
        )
        return 1
    print(f"camoufox browser present: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
