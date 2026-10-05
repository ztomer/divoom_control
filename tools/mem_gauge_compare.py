#!/usr/bin/env python3
"""Does the sysmon `mem` gauge still mean what Activity Monitor means?

WHY THIS EXISTS
---------------
The widget's memory percentage is `sysinfo::System::used_memory()` over
`total_memory()` (divoomd/src/live_jobs/sysmon.rs). Which quantity "used" names
is sysinfo's choice, and sysinfo has changed it without changing the signature
or the units: 0.30 summed `active + wire + compressor + speculative` pages,
0.39 sums `internal - purgeable + wire + compressor`. Nothing in the type system,
the tests or the build can see that. The only thing that ever noticed was a
human holding the widget up against Activity Monitor -- and that comparison,
done by hand from two byte snapshots, drew the wrong conclusion both ways
(see the comment at the call site for what was verified instead).

So the comparison is a command. One run answers ONE question: does the
`used_memory()` of the sysinfo version pinned in Cargo.lock equal Activity
Monitor's `App Memory + Wired Memory + Compressed` on this machine, now?

INDEPENDENCE
------------
The two sides must not share code, or the harness reads one number twice.

* sysinfo's side is the real crate: a throwaway probe is compiled against the
  exact version Cargo.lock pins (read at run time, never hardcoded), with the
  repo's lockfile copied in so its dependencies resolve the same way, and run.
* Activity Monitor's side is rebuilt here from the raw kernel counters,
  `host_statistics64(HOST_VM_INFO64)` via ctypes, page size from
  `host_page_size`, total from `sysctl hw.memsize`. App Memory is
  `(internal_page_count - purgeable_count) * page_size`; that identity is an
  EMPIRICAL calibration, not an Apple document -- it matched Activity Monitor's
  footer to 0.003 GiB mean over 9 paired samples on a 64 GiB, 16 KiB-page
  machine (macOS 27.0.1). If Activity Monitor redefines App Memory, this side
  is what goes stale, and a hand comparison against its footer is how to tell.

Activity Monitor's HEADER "Memory Used" is deliberately not the reference: it
ran a stable ~1.2 GiB above the sum of its own three footer fields, which no
`vm_statistics64` counter explains. That is Activity Monitor disagreeing with
itself, and no harness can match both of its numbers.

TOLERANCE
---------
The two sides read the counters at different instants (a process spawn
apart) and memory moves between reads, so equality is never exact. Each round
brackets the probe with a counter read before and after; the verdict is the
median delta over the rounds. Measured on the machine above, sysinfo 0.39 vs
this reconstruction: mean -0.13 pp, sd 0.29 pp. 1.0 pp is ~3.4 sd -- wide
enough not to flake on a busy machine, and still a quarter of the -4.24 pp mean
gap the 0.30 formula showed, so a formula change of that kind cannot hide in it.

Usage:
    python3 tools/mem_gauge_compare.py [--json] [--rounds N]
    python3 tools/mem_gauge_compare.py --sysinfo-version 0.30.13   # a candidate
Exit: 0 agree, 1 disagree, 2 harness could not measure, 3 not macOS (skipped).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tui import err, info, ok, warn  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TOLERANCE_PP = 1.0  # justified in the module docstring; do not tune to pass
EXIT_AGREE, EXIT_DISAGREE, EXIT_ERROR, EXIT_SKIPPED = 0, 1, 2, 3

# A stable directory, not a fresh tempdir per run: cargo keys its build-dir on
# the workspace path, so a new path every run would rebuild from scratch and
# leave a dead multi-hundred-MB build tree behind each time.
PROBE_DIR = Path(tempfile.gettempdir()) / "divoom-mem-gauge-probe"
PROBE_MAIN = """use sysinfo::System;

fn main() {
    let mut sys = System::new();
    sys.refresh_memory();
    println!("MEMPROBE {} {}", sys.total_memory(), sys.used_memory());
}
"""


def locked_sysinfo_version(lock_text: str) -> str:
    """The one sysinfo version Cargo.lock resolves. Two is an error, not a pick."""
    found = re.findall(r'\[\[package\]\]\nname = "sysinfo"\nversion = "([^"]+)"', lock_text)
    if len(found) != 1:
        raise ValueError(f"expected exactly one sysinfo in Cargo.lock, found {found}")
    return found[0]


def am_definition(c: dict[str, int], page: int) -> dict[str, int]:
    """Activity Monitor's App + Wired + Compressed, in bytes, from raw counters."""
    app = max(0, c["internal_page_count"] - c["purgeable_count"]) * page
    wired = c["wire_count"] * page
    compressed = c["compressor_page_count"] * page
    return {"app": app, "wired": wired, "compressed": compressed,
            "used": app + wired + compressed}


def verdict(delta_pp: float, tolerance_pp: float = TOLERANCE_PP) -> bool:
    return abs(delta_pp) <= tolerance_pp


# ── the OS side: raw Mach counters via ctypes ──────────────────────────────
class _Mach:
    """`host_statistics64` / `host_page_size` / `sysctlbyname`, nothing else."""

    def __init__(self) -> None:
        import ctypes

        c_nat, c_u64 = ctypes.c_uint32, ctypes.c_uint64
        # vm_statistics64 from <mach/vm_statistics.h>, through the last field
        # sysinfo (or Activity Monitor's components) needs. The kernel fills
        # `count` integer_t's and reports how many it wrote.
        fields = [(n, c_nat)
                  for n in ("free_count", "active_count", "inactive_count", "wire_count")]
        fields += [(n, c_u64) for n in ("zero_fill_count", "reactivations", "pageins", "pageouts",
                                        "faults", "cow_faults", "lookups", "hits", "purges")]
        fields += [("purgeable_count", c_nat), ("speculative_count", c_nat)]
        fields += [(n, c_u64) for n in ("decompressions", "compressions", "swapins", "swapouts")]
        fields += [(n, c_nat) for n in ("compressor_page_count", "throttled_count",
                                        "external_page_count", "internal_page_count")]
        fields += [("total_uncompressed_pages_in_compressor", c_u64)]
        self._Stats = type("vm_statistics64", (ctypes.Structure,), {"_fields_": fields})
        self.names = [n for n, _ in fields]
        self._ct = ctypes
        self._lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        self._lib.mach_host_self.restype = ctypes.c_uint32
        self._host = self._lib.mach_host_self()

    def page_size(self) -> int:
        size = self._ct.c_size_t(0)
        if self._lib.host_page_size(self._host, self._ct.byref(size)) != 0:
            raise OSError("host_page_size failed")
        return size.value

    def memsize(self) -> int:
        val, ln = self._ct.c_uint64(0), self._ct.c_size_t(8)
        if self._lib.sysctlbyname(b"hw.memsize", self._ct.byref(val), self._ct.byref(ln), None, 0):
            raise OSError("sysctlbyname(hw.memsize) failed")
        return val.value

    def counters(self) -> dict[str, int]:
        st = self._Stats()
        want = self._ct.sizeof(st) // 4
        count = self._ct.c_uint32(want)
        host_vm_info64 = 4
        rc = self._lib.host_statistics64(self._host, host_vm_info64,
                                         self._ct.byref(st), self._ct.byref(count))
        if rc != 0 or count.value < want:
            raise OSError(f"host_statistics64 rc={rc}, filled {count.value}/{want} words")
        return {n: int(getattr(st, n)) for n in self.names}


# ── the sysinfo side: the real crate, compiled ─────────────────────────────
def build_probe(version: str) -> Path:
    """Compile the probe against `version`; return the executable's path."""
    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    (PROBE_DIR / "src").mkdir(exist_ok=True)
    (PROBE_DIR / "src" / "main.rs").write_text(PROBE_MAIN)
    (PROBE_DIR / "Cargo.toml").write_text(
        '[package]\nname = "mem_gauge_probe"\nversion = "0.0.0"\nedition = "2024"\n\n'
        f'[dependencies]\nsysinfo = "={version}"\n'
    )
    # Same dependency resolution as the product: cargo keeps the entries it
    # can use and prunes the rest. Rewritten each run so a bump is picked up.
    shutil.copyfile(ROOT / "Cargo.lock", PROBE_DIR / "Cargo.lock")
    r = subprocess.run(
        ["cargo", "build", "--release", "--quiet", "--message-format=json"],
        capture_output=True, text=True, cwd=PROBE_DIR, timeout=900,
    )
    if r.returncode != 0:
        raise RuntimeError("the sysinfo probe did not build:\n" + r.stderr[-2000:])
    # Resolve the binary from cargo's own report: the house build-dir layout
    # means "<dir>/target/release/..." is not a path to hardcode.
    for line in r.stdout.splitlines():
        msg = json.loads(line) if line.startswith("{") else {}
        if msg.get("reason") == "compiler-artifact" and msg.get("executable"):
            return Path(msg["executable"])
    raise RuntimeError("cargo built the probe but reported no executable")


def run_probe(exe: Path) -> tuple[int, int]:
    out = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30, check=True).stdout
    line = next((s for s in out.splitlines() if s.startswith("MEMPROBE ")), None)
    if line is None:
        raise RuntimeError(f"probe printed no MEMPROBE line: {out!r}")
    total, used = (int(x) for x in line.split()[1:3])
    return total, used


def measure(version: str, rounds: int, source: str = "Cargo.lock") -> dict:
    mach = _Mach()
    page, memsize = mach.page_size(), mach.memsize()
    exe = build_probe(version)
    samples = []
    for _ in range(rounds):
        before = am_definition(mach.counters(), page)
        si_total, si_used = run_probe(exe)
        after = am_definition(mach.counters(), page)
        am = {k: (before[k] + after[k]) // 2 for k in before}
        samples.append({
            "sysinfo_total": si_total, "sysinfo_used": si_used, "am": am,
            "bracket_bytes": abs(after["used"] - before["used"]),
            "delta_bytes": si_used - am["used"],
            "delta_pp": 100.0 * (si_used - am["used"]) / si_total,
        })
    mid = sorted(samples, key=lambda s: s["delta_pp"])[len(samples) // 2]
    return {
        "platform": "darwin", "sysinfo_version": version, "version_source": source,
        "page_size": page, "os_total": memsize, "sysinfo_total": mid["sysinfo_total"],
        "sysinfo_used": mid["sysinfo_used"], "am": mid["am"],
        "delta_bytes": mid["delta_bytes"], "delta_pp": mid["delta_pp"],
        "delta_pp_sd": statistics.pstdev(s["delta_pp"] for s in samples),
        "tolerance_pp": TOLERANCE_PP, "rounds": samples,
        "agree": verdict(mid["delta_pp"]) and mid["sysinfo_total"] == memsize,
    }


def _gib(b: int) -> str:
    return f"{b / 2**30:8.3f} GiB"


def report(m: dict) -> None:
    tot = m["sysinfo_total"]
    pct = lambda b: f"{100.0 * b / tot:6.2f}%"  # noqa: E731
    am = m["am"]
    info(f"sysinfo {m['sysinfo_version']} ({m['version_source']})  ↔  Activity Monitor definition "
         f"from host_statistics64, page {m['page_size']} B, median of {len(m['rounds'])} rounds")
    info(f"total            {_gib(tot)}   (hw.memsize {_gib(m['os_total'])})")
    info(f"sysinfo used     {_gib(m['sysinfo_used'])}  {pct(m['sysinfo_used'])}")
    info(f"AM App+Wir+Comp  {_gib(am['used'])}  {pct(am['used'])}   "
         f"= {am['app'] / 2**30:.3f} + {am['wired'] / 2**30:.3f} + {am['compressed'] / 2**30:.3f}")
    info(f"delta            {m['delta_bytes']:+,} B   {m['delta_pp']:+.3f} pp   "
         f"(round sd {m['delta_pp_sd']:.3f} pp, tolerance ±{m['tolerance_pp']} pp)")
    if m["sysinfo_total"] != m["os_total"]:
        err("sysinfo's total_memory() is not hw.memsize -- the denominator moved too")
    if m["agree"]:
        ok("used_memory() is Activity Monitor's App + Wired + Compressed")
    else:
        err("used_memory() no longer matches Activity Monitor's App + Wired + Compressed "
            "-- sysinfo changed what it measures; re-derive the sysmon.rs comment")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="print the measurement as JSON")
    ap.add_argument("--rounds", type=int, default=7, help="bracketed samples (median wins)")
    ap.add_argument("--sysinfo-version", help="measure this version instead of Cargo.lock's")
    a = ap.parse_args(argv)

    if sys.platform != "darwin":
        why = f"Activity Monitor's definition only exists on macOS (this is {sys.platform})"
        print(json.dumps({"skipped": why})) if a.json else warn(f"SKIPPED: {why}")
        return EXIT_SKIPPED
    try:
        version = a.sysinfo_version or locked_sysinfo_version((ROOT / "Cargo.lock").read_text())
        source = "--sysinfo-version" if a.sysinfo_version else "Cargo.lock"
        m = measure(version, max(1, a.rounds), source)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as e:
        err(f"could not measure: {e}")
        return EXIT_ERROR
    print(json.dumps(m, indent=2)) if a.json else report(m)
    return EXIT_AGREE if m["agree"] else EXIT_DISAGREE


if __name__ == "__main__":
    sys.exit(main())
