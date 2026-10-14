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

Override with CAMOUFOX_EXPECTED_BUILD when deliberately testing another build;
set it empty to skip the build check and only require presence.

Exit 0 when the expected browser is active (prints the version), non-zero
otherwise.

Used by .github/workflows/tests.yml (as the retry's loop condition, so a
transient rate limit retries instead of poisoning the run). scripts/py_ci.sh
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
import sys

# Keep in step with `camoufox set` in .github/workflows/tests.yml and the
# rationale in tests/support/browser.py.
# KEEP THIS CURRENT. The pin exists for DETERMINISM -- a specific build, so a
# red run means a code change and not "the browser moved under you" -- NOT to
# hold the browser back. It was last moved off 152.0.4-beta.29 on 2026-10-04,
# two releases late: beta.29 was superseded by 152.0.4-beta.31 (2026-09-24) and
# then by this one (2026-10-03), and by then the pin named a build that was no
# longer installed on the machine running the suite.
#
# The move was verified, not assumed: on 156.0.1-beta.34 the browser suites run
# 165 passed / 1 failed and tests/test_main_world_bridge.py is 14/14, so the
# `mw:` bridge absorbs the world split exactly as tests/support/browser.py
# claims it would ("when the browser next moves the goalposts, it is one
# function again"). The one failure is unrelated stale test drift.
#
# So the claim that a newer build "fails ~60 tests" is HISTORICAL: it was true
# of beta.29, which is the build that INTRODUCED the isolated world, before the
# three holes below were closed. Do not use it to justify staying behind again.
EXPECTED_BUILD = os.environ.get("CAMOUFOX_EXPECTED_BUILD", "156.0.1-beta.34")


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


def main() -> int:
    version = installed_version()
    if version is None:
        print(
            "camoufox browser NOT installed — `camoufox fetch` may have exited 0 "
            "without installing anything (check for GitHub API 403 rate limits "
            "above). The 15 GUI e2e suites cannot run.",
            file=sys.stderr,
        )
        return 1
    if EXPECTED_BUILD and version != EXPECTED_BUILD:
        print(
            f"camoufox browser is {version}, expected {EXPECTED_BUILD}. The active "
            f"build is machine-wide ({cache_dir()}): any project using camoufox can "
            f"switch it, and the browser suites are pinned to one build so a red run "
            f"means a code change. Either run them on {version} "
            f"(pytest --run-browser) and move the pin in its own commit "
            f"(tools/camoufox_installed.py, .github/workflows/tests.yml, "
            f"tests/support/browser.py), or restore the pinned build -- for every "
            f"project on this machine: python3 -m camoufox fetch "
            f"official/stable/{EXPECTED_BUILD} && python3 -m camoufox set "
            f"official/stable/{EXPECTED_BUILD}",
            file=sys.stderr,
        )
        return 1
    print(f"camoufox browser present: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
