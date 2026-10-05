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
transient rate limit retries instead of poisoning the run) and reported by
scripts/ci_local.sh so a local green does not silently mean "all 15 e2e suites
skipped".
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
            f"camoufox browser is {version}, expected {EXPECTED_BUILD}. The e2e "
            f"suite is pinned to a build whose page.evaluate reaches the MAIN "
            f"world; a newer build isolates it and fails ~60 tests with the app "
            f"working fine. Run: python -m camoufox set "
            f"official/stable/{EXPECTED_BUILD}  (see tests/support/browser.py)",
            file=sys.stderr,
        )
        return 1
    print(f"camoufox browser present: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
