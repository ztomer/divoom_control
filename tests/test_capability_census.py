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

# **Calibrated against SYNTHETIC reproductions, not the live tree.**
#
# The first version of these asserted that F1 and F2 were still present in
# `gui_api.py` and `api/tools.py`. That is a self-destroying calibration: it
# passed only while the round had not yet succeeded, and the moment P1.1 routed
# the auth sites to the daemon, the test that proved the census WORKS went red
# because the census's job was done.
#
# The durable property is "this instrument can detect F1's shape", not "F1 is
# still here". So each shape is reproduced in a fixture. These keep biting
# forever, including for the fifth defect of the same shape that nobody has
# written yet.

def test_the_census_detects_F1s_shape_the_auth_bypass(tmp_path, monkeypatch):
    """`mod.capability(...)` through a divoom_lib module."""
    direct, _w, _r = _scan_one(
        tmp_path, monkeypatch,
        "from divoom_lib import divoom_auth\n"
        "class Api:\n"
        "    def __init__(self):\n"
        "        self.cached = divoom_auth.get_cached_credentials()\n",
        {"get_cached_credentials"})
    assert [n for _w2, n, _l in direct] == ["get_cached_credentials"], direct


def test_the_census_detects_F2s_shape_a_reimplementation(tmp_path, monkeypatch):
    """A function whose OWN name is a capability, reaching into divoom_lib.

    Name-matching alone would miss this: the daemon calls it `sync_time` and the
    Python spelling is `DateTimeCommand.update_date_time`.
    """
    _d, wrapped, _r = _scan_one(
        tmp_path, monkeypatch,
        "class Api:\n"
        "    def sync_time(self):\n"
        "        from divoom_lib.system.date_time import DateTimeCommand\n"
        "        return DateTimeCommand(self.dev).update_date_time()\n",
        {"sync_time"})
    assert [n for _w2, n, _l in wrapped] == ["sync_time"], wrapped


def test_the_live_tree_no_longer_has_F1(tmp_path, monkeypatch):
    """The other half: P1.1 actually removed it, not just moved the test.

    Separate from the calibration on purpose. If this ever goes red, the
    duplicate came back; if the calibration above goes red, the instrument
    broke. Collapsing them into one test is what made the first version
    ambiguous.
    """
    direct, _w, _r = census.scan_python(census.daemon_capabilities())
    gui_auth = [w for w, n, lib in direct
                if "divoom_auth" in lib and w.startswith("divoom_gui/")]
    assert gui_auth == [], f"the auth bypass is back in the GUI: {gui_auth}"


def test_the_census_finds_more_than_its_seed():
    """A census returning exactly what it was seeded with was transcribed.

    R72's plan says this explicitly. The scan found `get_credentials` in
    `scripts/` -- a directory R70's gate never looked at -- so the scope
    widening is doing work rather than being decorative.
    """
    direct, wrapped, reaches = census.scan_python(census.daemon_capabilities())
    where = {w.split(":")[0] for w, _, _ in direct + wrapped + reaches}
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
    direct, wrapped, reaches = _scan_one(
        tmp_path, monkeypatch,
        "from divoom_client.daemon_protocol import DaemonClient\n"
        "def sync_time(self):\n"
        "    return DaemonClient().send_command('sync_time')\n",
        {"sync_time"})
    assert direct == [] and wrapped == [] and reaches == [], (direct, wrapped, reaches)


def test_client_owned_helpers_are_deliberately_not_flagged(tmp_path, monkeypatch):
    """`atomic_io` / `lifecycle_config` write config the CLIENT owns.

    Flagging them would bury the real findings under noise, which is how a
    report stops being read.
    """
    direct, wrapped, reaches = _scan_one(
        tmp_path, monkeypatch,
        "from divoom_lib.utils.atomic_io import atomic_write_config\n"
        "from divoom_lib.lifecycle_config import get_keep_daemon_alive\n"
        "def sync_time(self):\n"
        "    atomic_write_config('x', {})\n"
        "    return get_keep_daemon_alive()\n",
        {"sync_time"})
    assert wrapped == [], wrapped
    assert direct == [], direct
    assert reaches == [], reaches


def test_a_new_duplicate_would_be_caught(tmp_path, monkeypatch):
    """Prove it bites without waiting for someone to write the bug."""
    direct, wrapped, reaches = _scan_one(
        tmp_path, monkeypatch,
        "from divoom_lib import divoom_auth\n"
        "def whatever():\n"
        "    return divoom_auth.get_credentials()\n",
        {"get_credentials"})
    assert [n for _w, n, _l in direct] == ["get_credentials"], direct
    assert reaches == [], reaches


def test_reaches_catches_F4_the_weather_resolver():
    """The category exists because the name-based rules could not see this.

    `_resolve_location` is not a daemon command name and it is bare-imported,
    so DIRECT and WRAPPED both miss it -- while it is unmistakably weather
    resolution, which the daemon owns. A census that reported clean with this
    standing would be measuring its own rules, not the invariant.
    """
    _d, _w, reaches = census.scan_python(census.daemon_capabilities())
    hits = [w for w, n, _lib in reaches if n == "_resolve_location"]
    assert hits, "F4 not caught by REACHES"
    assert any("media_sync.py" in w for w in hits), hits


def test_reaches_catches_the_shared_hotchannel_config():
    """Two parsers for one file is a duplication even without a command name.

    `divoomd/src/monthly_best.rs` reads hotchannel.json in Rust; the GUI reads
    and WRITES it through divoom_lib in Python. That is shared state with two
    independent implementations, which is the drift shape this round is about.
    """
    _d, _w, reaches = census.scan_python(census.daemon_capabilities())
    assert any(n.startswith("hotchannel_config.") for _w2, n, _l in reaches), reaches
