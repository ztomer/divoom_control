"""R67: ensure_daemon must VERIFY the daemon's version, not just its pulse.

A daemon left over from an older install answers `get_status` perfectly well and
then silently lacks whatever was added since. During R67 that cost three
debugging cycles — most memorably a `players` call that returned an empty list
because the running daemon predated the command, with nothing in the reply to
say so.

The guard is deliberately conservative: it restarts only on a KNOWN mismatch.
Killing a daemon that might be current is worse than tolerating one that might
be stale, and the first draft of this check did exactly that — it read the
version from `importlib.metadata` (stale dist-info from an old editable install,
0.22.21) instead of pyproject (0.26.0), and would have restarted the correct
daemon on every startup.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

import divoom_client.daemon_client as dc


def test_expected_version_prefers_pyproject_over_stale_metadata(monkeypatch):
    """pyproject is the gated source of truth; dist-info is routinely stale."""
    monkeypatch.setattr(dc, "__file__", dc.__file__)  # keep the real path
    expected = dc.expected_daemon_version()

    import tomllib
    root = Path(dc.__file__).resolve().parent.parent
    with open(root / "pyproject.toml", "rb") as f:
        pyproject_version = tomllib.load(f)["project"]["version"]

    assert expected == pyproject_version, (
        "expected_daemon_version must read pyproject, not installed metadata — "
        "metadata lags a working checkout and would condemn a current daemon")


def test_a_matching_version_is_left_alone(monkeypatch):
    calls = {"stopped": 0, "spawned": 0}
    monkeypatch.setattr(dc, "daemon_alive", lambda *a, **k: True)
    monkeypatch.setattr(dc, "expected_daemon_version", lambda: "1.2.3")
    monkeypatch.setattr(dc, "running_daemon_version", lambda *a, **k: "1.2.3")
    monkeypatch.setattr(dc, "_stop_stale_daemon",
                        lambda *a: calls.__setitem__("stopped", calls["stopped"] + 1) or True)
    monkeypatch.setattr(dc, "spawn_daemon",
                        lambda *a, **k: calls.__setitem__("spawned", calls["spawned"] + 1))

    assert dc.ensure_daemon("/tmp/x.sock") is not None
    assert calls == {"stopped": 0, "spawned": 0}, "a current daemon must not be touched"


def test_a_stale_version_is_restarted(monkeypatch):
    calls = {"stopped": 0, "spawned": 0}
    monkeypatch.setattr(dc, "daemon_alive", lambda *a, **k: True)
    monkeypatch.setattr(dc, "expected_daemon_version", lambda: "0.26.0")
    monkeypatch.setattr(dc, "running_daemon_version", lambda *a, **k: "0.22.21")
    monkeypatch.setattr(dc, "_stop_stale_daemon",
                        lambda *a: calls.__setitem__("stopped", calls["stopped"] + 1) or True)
    monkeypatch.setattr(dc, "spawn_daemon",
                        lambda *a, **k: calls.__setitem__("spawned", calls["spawned"] + 1))

    dc.ensure_daemon("/tmp/x.sock")
    assert calls["stopped"] == 1, "a stale daemon must be stopped"
    assert calls["spawned"] == 1, "and replaced"


def test_a_daemon_with_no_version_counts_as_stale(monkeypatch):
    """Pre-R67 daemons report no version at all — older than versioning itself."""
    calls = {"stopped": 0}
    monkeypatch.setattr(dc, "daemon_alive", lambda *a, **k: True)
    monkeypatch.setattr(dc, "expected_daemon_version", lambda: "0.26.0")
    monkeypatch.setattr(dc, "running_daemon_version", lambda *a, **k: None)
    monkeypatch.setattr(dc, "_stop_stale_daemon",
                        lambda *a: calls.__setitem__("stopped", calls["stopped"] + 1) or True)
    monkeypatch.setattr(dc, "spawn_daemon", lambda *a, **k: None)

    dc.ensure_daemon("/tmp/x.sock")
    assert calls["stopped"] == 1


def test_an_unknown_expectation_never_kills(monkeypatch):
    """If we cannot tell what version to expect, leave the daemon alone.

    Restarting on uncertainty would turn a diagnostic into an outage.
    """
    calls = {"stopped": 0}
    monkeypatch.setattr(dc, "daemon_alive", lambda *a, **k: True)
    monkeypatch.setattr(dc, "expected_daemon_version", lambda: None)
    monkeypatch.setattr(dc, "running_daemon_version", lambda *a, **k: "who knows")
    monkeypatch.setattr(dc, "_stop_stale_daemon",
                        lambda *a: calls.__setitem__("stopped", calls["stopped"] + 1) or True)

    assert dc.ensure_daemon("/tmp/x.sock") is not None
    assert calls["stopped"] == 0


def test_check_can_be_disabled(monkeypatch):
    calls = {"checked": 0}
    monkeypatch.setattr(dc, "daemon_alive", lambda *a, **k: True)
    monkeypatch.setattr(dc, "expected_daemon_version", lambda: "0.26.0")
    monkeypatch.setattr(dc, "running_daemon_version",
                        lambda *a, **k: calls.__setitem__("checked", 1) or "old")
    dc.ensure_daemon("/tmp/x.sock", check_version=False)
    assert calls["checked"] == 0


# ── R70 P4.1: the same trap, in the BUNDLE, where it actually shipped ────────

def test_a_frozen_bundle_reads_its_version_stamp(monkeypatch, tmp_path):
    """The shipped app must know its own version without pyproject.

    v0.28.3 did not. With no pyproject inside the bundle, `expected_daemon_version`
    fell through to `importlib.metadata`, which read the `divoom_control.egg-info`
    PyInstaller collects from the source tree — stale at 0.22.21. The installed
    app logged "daemon reports version 0.28.3 but 0.22.21 is expected —
    restarting it" and killed a healthy daemon on EVERY launch, dropping its BLE
    connection with it.
    """
    from divoom_client import daemon_version as dv

    (tmp_path / "BUNDLE_VERSION").write_text("9.9.9\n", encoding="utf-8")
    monkeypatch.setattr(dv.Path, "is_file", lambda self: "BUNDLE_VERSION" in str(self))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    # Force the pyproject branch to miss, as it does inside a real bundle.
    monkeypatch.setattr(dv, "__file__", str(tmp_path / "divoom_client" / "daemon_version.py"))

    assert dv.expected_daemon_version() == "9.9.9"


def test_a_bundle_without_a_stamp_refuses_to_guess(monkeypatch, tmp_path):
    """No stamp means NO expectation — never a stale one.

    The `importlib.metadata` fallback is gone on purpose. It produced exactly
    one answer in the wild and that answer was wrong; an unknown expectation
    must never justify killing something that might be fine, so returning None
    (no check) beats a check that is confidently stale.
    """
    from divoom_client import daemon_version as dv

    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(dv, "__file__", str(tmp_path / "divoom_client" / "daemon_version.py"))
    assert dv.expected_daemon_version() is None


def test_the_metadata_fallback_is_gone():
    """Structural: the branch that shipped the bug must not come back.

    Nothing else in this module may consult installed package metadata — that
    is the source that read 0.22.21 out of a stale egg-info.
    """
    import re

    src = (Path(__file__).resolve().parent.parent
           / "divoom_client" / "daemon_version.py").read_text()
    code = re.sub(r'"""(?:.|\n)*?"""', "", src)   # docstrings may NAME it
    code = re.sub(r"#.*", "", code)                # so may comments
    assert "importlib.metadata" not in code, (
        "the stale-metadata fallback is back in daemon_version.py")


def test_the_spec_stamps_the_version_it_puts_in_the_plist():
    """One version, two consumers. If the stamp and CFBundleShortVersionString
    could disagree, the app would be checked against a version it does not
    claim to be."""
    spec = (Path(__file__).resolve().parent.parent / "divoom.spec").read_text()
    assert "BUNDLE_VERSION" in spec, "divoom.spec no longer writes the stamp"
    assert "_f.write(VERSION" in spec, "the stamp must be written from VERSION"
    assert '"CFBundleShortVersionString": VERSION' in spec
