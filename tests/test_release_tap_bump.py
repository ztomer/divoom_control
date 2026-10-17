"""P1.9: the release bumps the cask through the tap's own gate.

`scripts/release.sh` used to rewrite the cask with `gh api -X PUT`, so the
tap's gate never ran on the bump. It now delegates to goh's `tap_bump.sh`,
which clones the tap, commits, runs the tap's `tools/gate.sh --full`, and
pushes the commit pinned. A red gate pushes nothing.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "release.sh"


def test_release_delegates_the_tap_bump_to_tap_bump_sh():
    text = SCRIPT.read_text()
    assert "tap_bump.sh" in text, "release.sh must call tap_bump.sh"
    assert 'gh api -X PUT "repos/${TAP}/contents/${CASK_PATH}"' not in text, (
        "the cask must not be pushed with a raw gh api PUT"
    )


def test_release_supports_dry_run():
    text = SCRIPT.read_text()
    assert "--dry-run" in text, "release.sh must accept --dry-run"
    assert "TAP_BUMP_ARGS" in text or "tap_bump.sh" in text
