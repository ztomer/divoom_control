"""DV.SHIPCUT (2): a stale local build names the ONE command that makes it current.

`tools/check_built_binaries.py` fails the full gate when a binary in this tree's target/ reports a
version other than the tree's. That is right (a stale target/release/divoomd once made spawn_daemon
kill and respawn the same stale daemon forever), but on 2026-11-13 (DV.GATE100) the gate went red on
target/release at 0.45.5 and target/debug at 0.45.3 against a 0.45.6 tree, and each line said
`cargo build -p X    (add --release to refresh target/release)`: a hint per binary, with the flag left
for the reader to work out. A gate red on a local artifact rather than on the tree must say exactly
what to run. It names one command, per flavour the stale binaries were built in, and running it is the
whole fix.

TEETH (watched red): the old per-binary hint gives no `Fix:` line; drop `--release` for a release
binary and the release row goes red; list a current binary and the current-binary row goes red.
"""

from __future__ import annotations

import importlib.util
import shlex
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def gate(monkeypatch):
    spec = importlib.util.spec_from_file_location("check_built_binaries", REPO / "tools" / "check_built_binaries.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "expected_daemon_version", lambda: "0.45.6")
    return mod


def binary(root: Path, flavour: str, name: str, version: str) -> None:
    path = root / "target" / flavour / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\necho '{name} {version}'\n")
    path.chmod(0o755)


def fix_lines(text: str) -> list[str]:
    return [ln.split("Fix:", 1)[1].strip() for ln in text.splitlines() if "Fix:" in ln]


def builds(command: str) -> list[list[str]]:
    """The `cargo build` invocations of a `a && b` command, as argv lists."""
    return [shlex.split(part) for part in command.split("&&")]


def test_the_0_45_6_shape_names_one_command_that_rebuilds_each_stale_flavour(gate, tmp_path, monkeypatch, capsys):
    binary(tmp_path, "release", "divoomd", "0.45.5")
    binary(tmp_path, "debug", "divoom-menubar", "0.45.3")
    monkeypatch.setattr(gate, "REPO", tmp_path)
    assert gate.main() == 1
    cap = capsys.readouterr()
    text = cap.out + cap.err
    fixes = fix_lines(text)
    assert len(fixes) == 1, text
    runs = builds(fixes[0])
    assert all(r[:2] == ["cargo", "build"] and "--locked" in r for r in runs), fixes
    release = [r for r in runs if "--release" in r]
    debug = [r for r in runs if "--release" not in r]
    assert len(release) == 1 and release[0][release[0].index("-p") + 1] == "divoomd", fixes
    assert len(debug) == 1 and debug[0][debug[0].index("-p") + 1] == "divoom-menubar", fixes
    assert "add --release" not in text


def test_a_current_binary_is_not_rebuilt(gate, tmp_path, monkeypatch, capsys):
    binary(tmp_path, "release", "divoomd", "0.45.6")
    binary(tmp_path, "release", "divoom-menubar", "0.45.5")
    binary(tmp_path, "debug", "divoomd", "0.45.6")
    monkeypatch.setattr(gate, "REPO", tmp_path)
    assert gate.main() == 1
    cap = capsys.readouterr()
    (fix,) = fix_lines(cap.out + cap.err)
    assert builds(fix) == [["cargo", "build", "--locked", "--release", "-p", "divoom-menubar"]]


def test_current_binaries_pass(gate, tmp_path, monkeypatch, capsys):
    binary(tmp_path, "release", "divoomd", "0.45.6")
    binary(tmp_path, "debug", "divoom-menubar", "0.45.6")
    monkeypatch.setattr(gate, "REPO", tmp_path)
    assert gate.main() == 0
    assert not fix_lines(capsys.readouterr().out)
