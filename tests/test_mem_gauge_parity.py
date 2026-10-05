"""The sysmon `mem` gauge must keep meaning Activity Monitor's App + Wired + Compressed.

`sysinfo::System::used_memory()` changed which quantity it measures between
0.30 and 0.39 with no change to its signature or units, and the comment that
recorded the bump drew the wrong conclusion from two byte snapshots.
`tools/mem_gauge_compare.py` re-derives the answer by compiling the locked
sysinfo and rebuilding Activity Monitor's definition from raw Mach counters.

Two layers, because only one of them can run everywhere:

* ALWAYS: the call-site comment in sysmon.rs still names the vendored source
  file of the sysinfo version Cargo.lock pins, the formula, and the tool. A
  sysinfo bump therefore fails here on Linux CI too, until someone re-runs the
  harness on a Mac and updates the comment -- the comment cannot silently
  outlive the code it describes.
* macOS: the real measurement agrees within the harness's tolerance.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "mem_gauge_compare.py"
SYSMON = REPO / "divoomd" / "src" / "live_jobs" / "sysmon.rs"
sys.path.insert(0, str(REPO / "tools"))

gauge = pytest.importorskip("mem_gauge_compare")

FORMULA = "(internal_page_count - purgeable_count + wire_count + compressor_page_count) * page"


def _locked_version() -> str:
    return gauge.locked_sysinfo_version((REPO / "Cargo.lock").read_text())


# ── machine-independent ────────────────────────────────────────────────────
def test_call_site_comment_names_the_locked_sysinfo_source_and_the_tool():
    src = SYSMON.read_text()
    assert "sys.used_memory()" in src, "the call the comment describes is gone"
    version = _locked_version()
    cite = f"sysinfo-{version}/src/unix/apple/system.rs"
    assert cite in src, (
        f"Cargo.lock pins sysinfo {version} but sysmon.rs does not cite {cite}: "
        "re-run tools/mem_gauge_compare.py on a Mac, then update the comment"
    )
    assert FORMULA in src, "the comment no longer quotes the formula it depends on"
    assert "tools/mem_gauge_compare.py" in src
    assert TOOL.is_file()


def test_lockfile_parser_refuses_ambiguity():
    one = '[[package]]\nname = "sysinfo"\nversion = "1.2.3"\n'
    assert gauge.locked_sysinfo_version(one) == "1.2.3"
    with pytest.raises(ValueError):
        gauge.locked_sysinfo_version(one + one.replace("1.2.3", "0.30.13"))
    with pytest.raises(ValueError):
        gauge.locked_sysinfo_version("")


def test_am_definition_arithmetic():
    c = {"internal_page_count": 10, "purgeable_count": 3, "wire_count": 4,
         "compressor_page_count": 5}
    am = gauge.am_definition(c, 16384)
    assert am == {"app": 7 * 16384, "wired": 4 * 16384, "compressed": 5 * 16384,
                  "used": 16 * 16384}
    # Purgeable can exceed internal for an instant; App Memory floors at zero.
    assert gauge.am_definition({**c, "purgeable_count": 99}, 1)["app"] == 0


def test_verdict_tolerance_is_inclusive_and_bites():
    assert gauge.TOLERANCE_PP == 1.0
    assert gauge.verdict(1.0) and gauge.verdict(-1.0)
    assert not gauge.verdict(1.01) and not gauge.verdict(-4.24)


def test_non_macos_reports_skipped_not_agreement(monkeypatch, capsys):
    monkeypatch.setattr(gauge.sys, "platform", "linux")
    assert gauge.main(["--json"]) == gauge.EXIT_SKIPPED
    assert "skipped" in json.loads(capsys.readouterr().out)


# ── the real measurement ───────────────────────────────────────────────────
@pytest.mark.skipif(sys.platform != "darwin",
                    reason="Activity Monitor's memory definition only exists on macOS")
@pytest.mark.skipif(shutil.which("cargo") is None,
                    reason="cargo is needed to compile the locked sysinfo")
def test_used_memory_matches_activity_monitor_definition():
    r = subprocess.run([sys.executable, str(TOOL), "--json"],
                       capture_output=True, text=True, timeout=900)
    assert r.returncode in (0, 1), f"harness could not measure:\n{r.stderr}{r.stdout}"
    m = json.loads(r.stdout)
    assert m["sysinfo_version"] == _locked_version()
    assert m["sysinfo_total"] == m["os_total"], "total_memory() is not hw.memsize"
    assert min(m["am"]["app"], m["am"]["wired"], m["am"]["compressed"]) >= 0
    assert m["am"]["used"] > 0
    assert abs(m["delta_pp"]) <= m["tolerance_pp"], (
        f"sysinfo {m['sysinfo_version']} used_memory() is {m['delta_pp']:+.3f} pp off "
        f"Activity Monitor's App+Wired+Compressed (tolerance {m['tolerance_pp']} pp)"
    )
    assert m["agree"] is True
    assert r.returncode == 0
