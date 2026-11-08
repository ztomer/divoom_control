"""No tracked file names a path under the shipped library tree that is not there (D.DEADDYLIB).

The class: a deletion leaves a path behind in a file that still names it. L4
(2026-09-25) deleted the compiled encoder library, and for six weeks four
loaders under `examples/` and `setup_app.py` kept testing for it. Each loader
asked "does it exist?" and took its fallback, so no test failed and the dead
branch read like live code. The same sweep found `make test-hardware` depending
on a `native` target that no longer exists.

Two rules, because the tree holds two different kinds of reference:

* A file that RUNS or CONFIGURES something (Makefile, shell, TOML, spec,
  setup scripts, CI) may not name a missing path at all. No allowlist: a build
  file pointing at nothing is a build that silently skips or fails.
* Prose and provenance (a Rust comment saying where a routine was ported from,
  a changelog entry, a doc) names deleted files on purpose -- that is the
  history. These are counted per file and may only go DOWN: a new dangling
  reference fails, and so does a count that has dropped without the ledger being
  lowered, so the ledger cannot rot into a rug.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# The tree name is assembled so this file does not name a path itself.
TREE = "divoom" + "_lib"
REFERENCE = re.compile(r"(?<![\w/.-])" + TREE + r"/([A-Za-z0-9_.\-/]*[A-Za-z0-9_])")

# Files whose references are operational: no dangling path is ever acceptable.
OPERATIONAL_SUFFIXES = (".sh", ".toml", ".spec", ".cfg", ".yml", ".yaml", ".plist")
OPERATIONAL_NAMES = ("Makefile", "setup_app.py")

# Dangling references per file, all of them prose, provenance or history.
# Seeded 2026-11-07 with exactly what the tree held. Lower an entry (or delete
# it at 0) as references are fixed; never raise one.
KNOWN_PROSE_DANGLING: dict[str, int] = {
    "ARCHITECTURE.md": 1,
    "CHANGELOG.md": 65,
    "README.md": 2,
    "divoom_gui/aid_sleep.py": 1,
    "divoom_gui/api/lighting.py": 4,
    "divoom_gui/clock_faces.py": 1,
    "divoom_gui/photo_albums.py": 1,
    "divoom_gui/playlists.py": 1,
    "divoom_lib/divoom_auth.py": 1,
    "divoom_lib/models/capability_model.py": 1,
    "divoomd/src/art.rs": 2,
    "divoomd/src/art_codec.rs": 1,
    "divoomd/src/art_hot.rs": 1,
    "divoomd/src/autoprobe.rs": 1,
    "divoomd/src/ble.rs": 2,
    "divoomd/src/cloud.rs": 1,
    "divoomd/src/cloud_category.rs": 2,
    "divoomd/src/cloud_photo.rs": 1,
    "divoomd/src/cloud_playlist.rs": 1,
    "divoomd/src/device_call/aid_sleep.rs": 1,
    "divoomd/src/device_call/animation.rs": 1,
    "divoomd/src/device_call/drawing.rs": 1,
    "divoomd/src/device_call/music.rs": 1,
    "divoomd/src/device_call/system.rs": 1,
    "divoomd/src/image_encode.rs": 1,
    "divoomd/src/image_proc.rs": 1,
    "divoomd/src/lan.rs": 1,
    "divoomd/src/live_jobs/render.rs": 1,
    "divoomd/src/live_jobs/sysmon.rs": 1,
    "divoomd/src/mcp_tools.rs": 1,
    "divoomd/src/mock_device_tests.rs": 1,
    "divoomd/src/mock_device_tests2.rs": 2,
    "divoomd/src/packets.rs": 4,
    "divoomd/src/packets_tests.rs": 1,
    "divoomd/src/response.rs": 1,
    "divoomd/src/wall.rs": 2,
    "divoomd/tests/lan_behavior.rs": 1,
    "divoomd/tests/live_jobs_stress.rs": 1,
    "docs/APK_COMPARISON.md": 2,
    "docs/CAPABILITY_MAP.md": 1,
    "docs/CHANNEL_ARCHITECTURE.md": 3,
    "docs/cloud_api/README.md": 1,
    "docs/cloud_api/misc_small.md": 1,
    "docs/cloud_api/toplevel_a.md": 1,
    "docs/release_notes_v0.40.0.md": 1,
    "examples/divoom_legacy/ble_transport.py": 2,
    "examples/divoom_legacy/connection.py": 1,
    "examples/divoom_legacy/display/__init__.py": 1,
    "examples/divoom_legacy/divoom.py": 1,
    "examples/divoom_legacy/spp_connection.py": 1,
    "examples/divoom_legacy/system/temp_weather.py": 1,
    "examples/divoom_legacy/system/weather.py": 1,
    "examples/tests/test_ble_transport_coverage.py": 1,
    "examples/tests/test_hot_update_coverage.py": 1,
    "examples/tests/test_push_protocol_diagnostic.py": 1,
    "examples/tests/test_scheduling_mock.py": 1,
    "examples/tests/test_tool_mock.py": 1,
    "scripts/hw_e2e.py": 1,
    "tests/test_binary_resolver.py": 1,
    "tests/test_check_launchd_jobs.py": 2,
    "tests/test_no_native_encoder_chain.py": 4,
    "tools/check_launchd_jobs.py": 4,
}


def tracked() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL
    )
    return out.stdout.splitlines()


def exists(relative: str) -> bool:
    """A reference resolves if it is a path, a module without its suffix, or a
    `module.attribute` pointer into a module."""
    path = REPO / TREE / relative
    if path.exists() or path.with_name(path.name + ".py").exists():
        return True
    stem, dot, _attr = relative.rpartition(".")
    return bool(dot) and (REPO / TREE / (stem + ".py")).exists()


def dangling(text: str) -> list[str]:
    return [m.group(0) for m in REFERENCE.finditer(text) if not exists(m.group(1))]


def scan() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for name in tracked():
        try:
            text = (REPO / name).read_text(encoding="utf-8")
        except UnicodeDecodeError, OSError:
            continue
        hits = dangling(text)
        if hits:
            found[name] = hits
    return found


def is_operational(name: str) -> bool:
    return name.endswith(OPERATIONAL_SUFFIXES) or Path(name).name in OPERATIONAL_NAMES


def test_the_detector_sees_a_missing_path_and_passes_a_real_one() -> None:
    assert dangling(f"{TREE}/no_such_module_here.py and {TREE}/nothing/at/all") == [
        f"{TREE}/no_such_module_here.py",
        f"{TREE}/nothing/at/all",
    ]
    assert (
        dangling(f"see {TREE}/framing.py and the {TREE}/framing module, {TREE}/framing.parse_ios_le_notification") == []
    )
    assert dangling(f"{TREE}/") == []


def test_no_build_or_config_file_names_a_missing_path() -> None:
    bad = {name: hits for name, hits in scan().items() if is_operational(name)}
    assert not bad, "build/config files name paths that do not exist:\n" + "\n".join(
        f"  {name}: {', '.join(hits)}" for name, hits in sorted(bad.items())
    )


def test_prose_references_to_missing_paths_only_shrink() -> None:
    counts = {name: len(hits) for name, hits in scan().items() if not is_operational(name)}
    grew = {n: c for n, c in counts.items() if c > KNOWN_PROSE_DANGLING.get(n, 0)}
    assert not grew, "new dangling references (file: now > allowed):\n" + "\n".join(
        f"  {n}: {c} > {KNOWN_PROSE_DANGLING.get(n, 0)}  {', '.join(scan()[n])}" for n, c in sorted(grew.items())
    )
    stale = {n: allowed for n, allowed in KNOWN_PROSE_DANGLING.items() if counts.get(n, 0) < allowed}
    assert not stale, "ledger entries above the real count; lower or delete them:\n" + "\n".join(
        f"  {n}: ledger {a}, tree {counts.get(n, 0)}" for n, a in sorted(stale.items())
    )
