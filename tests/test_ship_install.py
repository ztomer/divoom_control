"""DV.SHIPINSTALL: `goh ship` ends with the new Divoom.app installed and running.

goh shipped 0.45.2 and left 0.45.1 installed, because `.gatesrc` declared a release kit and no
install step. `scripts/ship_install.sh` is that step: refresh the tap clone, refuse a cask that does
not declare HEAD's version, `brew upgrade --cask`, prove the installed bundle reports the version,
launch it when nothing of it runs.

SEAMS: DIVOOM_BREW is a stub brew that records its calls and, for `upgrade`, writes the bundle at
the version STUB_INSTALLS names; DIVOOM_TAP_DIR is a throwaway clone of a throwaway "tap" origin;
DIVOOM_APP a bundle under tmp; DIVOOM_OPEN a stub launcher. No real brew, tap or app is touched.

TEETH (each watched red): drop the version proof and the stale-upgrade row goes red; drop the cask
check and the stale-cask row goes red; drop the `git pull` and the refresh row goes red; delete the
.gatesrc line and the declaration row goes red.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GOH = Path(os.environ.get("GOH_DIR") or Path.home() / "Projects" / "gates_of_heck")

PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>CFBundleShortVersionString</key><string>{v}</string></dict></plist>
"""
BREW_STUB = """#!/usr/bin/env bash
echo "brew $*" >> "$STUB_LOG"
case "$1" in
  list) [ -n "${STUB_LISTED:-}" ] ;;
  upgrade|install)
    mkdir -p "$DIVOOM_APP/Contents"
    sed "s/{v}/$STUB_INSTALLS/" "$STUB_PLIST" > "$DIVOOM_APP/Contents/Info.plist" ;;
esac
"""
OPEN_STUB = """#!/usr/bin/env bash
echo "open $*" >> "$STUB_LOG"
"""
CASK = '  version "{v}"\n'


def git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}  # fmt: skip
    done = subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)  # fmt: skip
    return done.stdout.strip()


@pytest.fixture
def box(tmp_path: Path) -> Path:
    """A repo copy declaring 1.0.1, a tap origin whose cask declares 1.0.0, and its local clone."""
    work = tmp_path / "work"
    (work / "scripts").mkdir(parents=True)
    (work / "scripts" / "ship_install.sh").write_text((REPO / "scripts" / "ship_install.sh").read_text())
    (work / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1.0.1"\n')
    origin = tmp_path / "tap-origin"
    (origin / "Casks").mkdir(parents=True)
    git(origin, "init", "-q", "-b", "main")
    (origin / "Casks" / "divoom-control.rb").write_text(CASK.format(v="1.0.0"))
    git(origin, "add", ".")
    git(origin, "commit", "-q", "-m", "1.0.0")
    git(tmp_path, "clone", "-q", str(origin), str(tmp_path / "tap"))
    for name, body in (("brew", BREW_STUB), ("open", OPEN_STUB)):
        p = tmp_path / name
        p.write_text(body)
        p.chmod(0o755)
    (tmp_path / "plist.tmpl").write_text(PLIST)
    app = tmp_path / "Applications" / "Divoom.app" / "Contents"
    app.mkdir(parents=True)
    (app / "Info.plist").write_text(PLIST.format(v="1.0.0"))
    return tmp_path


def bump_tap(box: Path, v: str) -> None:
    """What release.sh does on GitHub: the tap ORIGIN's cask moves; the local clone does not."""
    origin = box / "tap-origin"
    (origin / "Casks" / "divoom-control.rb").write_text(CASK.format(v=v))
    git(origin, "commit", "-q", "-am", v)


def run(box: Path, *, installs: str = "1.0.1", listed: bool = True) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ, "GOH_DIR": str(GOH), "NO_COLOR": "1",
        "DIVOOM_BREW": str(box / "brew"), "DIVOOM_OPEN": str(box / "open"),
        "DIVOOM_TAP_DIR": str(box / "tap"), "DIVOOM_APP": str(box / "Applications" / "Divoom.app"),
        "STUB_LOG": str(box / "stub.log"), "STUB_PLIST": str(box / "plist.tmpl"),
        "STUB_INSTALLS": installs, "STUB_LISTED": "1" if listed else "",
    }  # fmt: skip
    return subprocess.run(["bash", "scripts/ship_install.sh"], cwd=box / "work", env=env, capture_output=True,
                          text=True, timeout=60, stdin=subprocess.DEVNULL, check=False)  # fmt: skip


def log(box: Path) -> list[str]:
    p = box / "stub.log"
    return p.read_text().splitlines() if p.exists() else []


def test_refreshes_the_tap_upgrades_proves_the_version_and_launches(box):
    bump_tap(box, "1.0.1")
    r = run(box)
    assert r.returncode == 0, r.stdout + r.stderr
    calls = log(box)
    assert "brew upgrade --cask ztomer/tap/divoom-control" in calls
    assert any(c.startswith("open -g ") and c.endswith("Divoom.app") for c in calls), calls
    assert "1.0.1" in (box / "tap" / "Casks" / "divoom-control.rb").read_text()  # the clone was pulled


def test_a_cask_the_release_did_not_bump_installs_nothing(box):
    r = run(box)
    assert r.returncode != 0
    assert "not 1.0.1" in r.stdout + r.stderr
    assert not any(c.startswith(("brew upgrade", "brew install")) for c in log(box))


def test_an_upgrade_that_leaves_the_old_app_fails_the_ship(box):
    bump_tap(box, "1.0.1")
    r = run(box, installs="1.0.0")
    assert r.returncode != 0
    assert "reports '1.0.0', not 1.0.1" in r.stdout + r.stderr
    assert not any(c.startswith("open ") for c in log(box))


def test_an_app_brew_does_not_know_is_installed_not_upgraded(box):
    bump_tap(box, "1.0.1")
    r = run(box, listed=False)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "brew install --cask ztomer/tap/divoom-control" in log(box)


def test_gatesrc_declares_the_install_step_the_way_goh_reads_it():
    script = '. ./.gatesrc >/dev/null 2>&1; printf "%s" "$GOH_SHIP_INSTALL"'
    done = subprocess.run(["bash", "-c", script], cwd=REPO, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, check=True)  # fmt: skip
    assert done.stdout == "scripts/ship_install.sh"
