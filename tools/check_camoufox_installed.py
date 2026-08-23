#!/usr/bin/env python3
"""Verify a camoufox browser BINARY is actually installed.

`python -m camoufox fetch` exits 0 when it installs nothing. CI run 32654312489
hit GitHub's unauthenticated API rate limit, printed three 403s and "Synced 0
versions from 0 repos.", and still reported its step green; the damage surfaced
later inside pytest, looking like a test regression rather than a failed
install. A step that cannot fail is not a gate, so check the artifact rather
than the exit code.

Exit 0 when a browser is present (prints the version), non-zero otherwise.

Used by .github/workflows/tests.yml (as the retry's loop condition, so a
transient rate limit retries instead of poisoning the run) and reported by
scripts/ci_local.sh so a local green does not silently mean "all 15 e2e suites
skipped".
"""

from __future__ import annotations

import sys


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
    print(f"camoufox browser present: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
