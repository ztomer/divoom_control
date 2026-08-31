"""The census is calibrated before its silence is trusted (R72 P0.4).

**Why calibration is the deliverable, not a formality.** This is the third pass
at "does anything in Python do a job the daemon owns". The first two used
hand-written lists and both missed things -- R70's denylist could not see
`divoom_auth` because it named `divoom_lib.cloud`, and could not see the
notification stack because it was scoped to `divoom_gui/`. A census that reports
"nothing found" is worth exactly as much as its ability to find something, so
these tests require it to rediscover the two findings that were established
BEFORE it was written:

  F1  `divoom_gui/gui_api.py` calls `divoom_lib.divoom_auth.get_cached_credentials()`
      while the daemon answers `get_cached_credentials` and a wrapper exists
  F2  `divoom_gui/api/tools.py::sync_time` rebuilds the payload through
      `divoom_lib.system.date_time` -- and that Python path was BROKEN, an
      AttributeError swallowed into a silent False

If either stops being found, the census has stopped measuring what it claims.

The other direction matters too: a scan that flagged every divoom_lib import
would "find" both and be useless. So there are tests that clean code produces
nothing, and that the deliberately-excluded client-owned helpers stay excluded.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

census = pytest.importorskip("capability_census")


# ── the OWNED half: read out of Rust, never hand-maintained ──────────────────

def test_daemon_capabilities_are_extracted_from_the_rust():
    caps = census.daemon_capabilities()
    assert len(caps) > 200, f"only {len(caps)} — the match-arm scan is not working"
    for expected in ("sync_time", "get_cached_credentials", "save_credentials",
                     "set_auto_power_off", "probe_lan"):
        assert expected in caps, f"{expected} missing from the owned list"


def test_multi_line_match_arms_are_all_captured(tmp_path, monkeypatch):
    """Aliases wrap across lines; catching only the `=>` form drops all but one.

    That would silently shrink the owned list, which makes the census quieter
    and therefore look better -- the worst direction for a bug to go.
    """
    src = tmp_path / "device_call"
    src.mkdir()
    (src / "x.rs").write_text(
        '        "sound.set_thing"\n'
        '        | "system.set_thing"\n'
        '        | "set_thing" => {\n'
    )
    monkeypatch.setattr(census, "RUST", tmp_path)
    caps = census.daemon_capabilities()
    for expected in ("sound.set_thing", "system.set_thing", "set_thing"):
        assert expected in caps, f"{expected} lost from a multi-line arm: {caps}"


# ── calibration: the two findings that predate the instrument ────────────────

def test_the_census_rediscovers_F1_the_auth_bypass():
    _, _ = None, None
    direct, _wrapped = census.scan_python(census.daemon_capabilities())
    hits = [(w, n) for w, n, _lib in direct if n.endswith("credentials")]
    assert hits, "F1 not rediscovered — the census cannot see the auth bypass"
    assert any("gui_api.py" in w for w, _ in hits), hits


def test_the_census_rediscovers_F2_the_sync_time_duplicate():
    _direct, wrapped = census.scan_python(census.daemon_capabilities())
    hits = [(w, n) for w, n, _libs in wrapped if n == "sync_time"]
    assert hits, "F2 not rediscovered — the census cannot see a reimplementation"
    assert any("tools.py" in w for w, _ in hits), hits


def test_the_census_finds_more_than_its_seed():
    """A census returning exactly what it was seeded with was transcribed.

    R72's plan says this explicitly. The scan found `get_credentials` in
    `scripts/` -- a directory R70's gate never looked at -- so the scope
    widening is doing work rather than being decorative.
    """
    direct, wrapped = census.scan_python(census.daemon_capabilities())
    where = {w.split(":")[0] for w, _, _ in direct + wrapped}
    assert any(p.startswith("scripts/") for p in where), (
        f"nothing found outside divoom_gui/divoom_client: {sorted(where)}")


# ── the other direction: it must not flag everything ─────────────────────────

def _scan_one(tmp_path, monkeypatch, body: str, caps: set[str]):
    pkg = tmp_path / "divoom_gui"
    pkg.mkdir(exist_ok=True)
    (pkg / "m.py").write_text(body)
    monkeypatch.setattr(census, "PY_SURFACE", (pkg,))
    monkeypatch.setattr(census, "REPO", tmp_path)
    return census.scan_python(caps)


def test_clean_client_code_produces_no_findings(tmp_path, monkeypatch):
    direct, wrapped = _scan_one(
        tmp_path, monkeypatch,
        "from divoom_client.daemon_protocol import DaemonClient\n"
        "def sync_time(self):\n"
        "    return DaemonClient().send_command('sync_time')\n",
        {"sync_time"})
    assert direct == [] and wrapped == [], (direct, wrapped)


def test_client_owned_helpers_are_deliberately_not_flagged(tmp_path, monkeypatch):
    """`atomic_io` / `lifecycle_config` write config the CLIENT owns.

    Flagging them would bury the real findings under noise, which is how a
    report stops being read.
    """
    direct, wrapped = _scan_one(
        tmp_path, monkeypatch,
        "from divoom_lib.utils.atomic_io import atomic_write_config\n"
        "from divoom_lib.lifecycle_config import get_keep_daemon_alive\n"
        "def sync_time(self):\n"
        "    atomic_write_config('x', {})\n"
        "    return get_keep_daemon_alive()\n",
        {"sync_time"})
    assert wrapped == [], wrapped
    assert direct == [], direct


def test_a_new_duplicate_would_be_caught(tmp_path, monkeypatch):
    """Prove it bites without waiting for someone to write the bug."""
    direct, wrapped = _scan_one(
        tmp_path, monkeypatch,
        "from divoom_lib import divoom_auth\n"
        "def whatever():\n"
        "    return divoom_auth.get_credentials()\n",
        {"get_credentials"})
    assert [n for _w, n, _l in direct] == ["get_credentials"], direct
