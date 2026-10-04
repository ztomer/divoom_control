#!/usr/bin/env python3
"""Fail when a declared cargo feature blocks a dependency from moving forward.

THE CLASS THIS EXISTS TO KILL
-----------------------------
Cargo features are the only part of a dependency's interface that can be
DELETED with no error anywhere. When reqwest 0.13.2 dropped its optional
`webpki-roots` dependency, the implicit feature of that name vanished with it.
Nothing warned. `cargo update` simply could not move reqwest past 0.13.1 and
reported it only in a parenthetical --

    Unchanged reqwest v0.13.1 (available: v0.13.5)

-- then exited 0. Not one gate in this repo printed that line. The repo sat on
0.13.1 for months with comments implying currency; the only reason it was
found was a human reading `cargo update --dry-run --verbose` closely. The fix
was two strings. The months were the defect.

THE SUBTLETY THAT MAKES A NAIVE VERSION OF THIS GATE USELESS
------------------------------------------------------------
The obvious implementation checks the declared feature against the LOCKED
version. That reports the bug as healthy, because the locked version is
precisely the one that still has the feature. Measured on this repo:

    reqwest 0.13.1  in_features_map=False  in_deps=True    <- feature exists
    reqwest 0.13.2  in_features_map=False  in_deps=False   <- feature GONE
    ... 0.13.5      in_features_map=False  in_deps=False

The condition is not "the current version lacks the feature". It is "the
declared requirement is UNSATISFIABLE at the newest version it permits", so
`cargo update` cannot make progress. The newest version is where the answer
lives, so that is what this gate checks.

WHY NOT THE crates.io API, AND WHY NOT THE UNPACKED SOURCE
-----------------------------------------------------------
An implicit feature -- one that exists only because an OPTIONAL DEPENDENCY
shares its name -- is absent from the published `features` map. Above,
`in_features_map=False` even for 0.13.1, which genuinely has it. A gate built
on that map alone reports a false positive here and teaches everyone to ignore
it.

So the feature set is derived the way cargo derives it: explicit `[features]`
keys, PLUS every optional dependency that is not reachable only as `dep:foo`,
which cargo also exposes as a feature of that name. The discriminator between
a present and a deleted implicit feature is the optional dependency, so the
dependency list is the thing that must be read -- not the feature map alone.

Data comes from the local index cache under
`~/.cargo/registry/index/*/.cache/`, which cargo refreshes for every crate it
resolves. That makes the gate offline and deterministic.

EXIT CODES
----------
    0  every declared feature exists at the newest version the manifest allows
    1  a declared feature blocks an upgrade, or is missing outright
    2  the gate could not run (no index cache, unparseable requirement,
       crate absent from the cache). Deliberately NOT 0: a gate that cannot
       check must not report success, or it is the same silent pin in a
       different hat.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_CACHE = Path.home() / ".cargo/registry/index"

DEP_TABLES = ("dependencies", "dev-dependencies", "build-dependencies")


# ── version + requirement handling ────────────────────────────────────────────
# Implemented rather than pulled from a library because the index cache is
# already the data source and these two functions are the only semantics
# needed. Anything unrecognised raises, so an unknown requirement FAILS the
# gate instead of silently widening it.


def vparse(v: str) -> tuple:
    """(major, minor, patch, pre) — pre is a tuple so 1.0.0-alpha < 1.0.0."""
    core, _, pre = v.partition("+")[0].partition("-")
    parts = (core.split(".") + ["0", "0"])[:3]
    nums = tuple(int(p) if p.isdigit() else 0 for p in parts)
    if not pre:
        return nums + ((),)
    # 1.0.0-alpha < 1.0.0-beta < 1.0.0
    return nums + ((0, pre),)


def vkey(v: str) -> tuple:
    nums, pre = vparse(v)[0:3], vparse(v)[3]
    # no prerelease sorts above any prerelease; a plain release outranks one.
    return (nums, 1 if not pre else 0, pre)


def satisfies_one(ver: str, req: str) -> bool:
    """Cargo caret semantics for one comparator."""
    req = req.strip()
    if not req or req == "*":
        return True

    for op in (">=", "<=", ">", "<", "="):
        if req.startswith(op):
            bound = req[len(op) :].strip()
            if not re.fullmatch(r"\d+(\.\d+){0,2}(-[0-9A-Za-z.\-]+)?", bound):
                raise ValueError(f"unparseable version bound: {req!r}")
            vb, bb = vparse(ver), vparse(bound)
            if op == ">=":
                return vkey(ver) >= vkey(bound)
            if op == "<=":
                return vkey(ver) <= vkey(bound)
            if op == ">":
                return vkey(ver) > vkey(bound)
            if op == "<":
                return vkey(ver) < vkey(bound)
            return vb[0:3] == bb[0:3] and (ver.partition("-")[2] == bound.partition("-")[2])
        if op == "^":
            break

    if req.startswith("^"):
        req = req[1:].strip()
    if req.startswith("~"):
        # ~1.2.3 := >=1.2.3, <1.3.0 ; ~1.2 := >=1.2, <1.3.0 ; ~1 := >=1, <2
        req = req[1:].strip()
        lo = vparse(req)
        upper = (lo[0], lo[1] + 1, 0) if req.count(".") >= 1 else (lo[0] + 1, 0, 0)
        return vkey(ver) >= vkey(req) and vparse(ver)[0:3] < upper

    if not re.fullmatch(r"\d+(\.\d+){0,2}(-[0-9A-Za-z.\-]+)?", req):
        raise ValueError(f"unparseable version requirement: {req!r}")

    # Bare or `=` requirement == caret, which is cargo's default.
    lo = vparse(req)
    given = req.count(".") + 1 if "-" not in req else req.split("-")[0].count(".") + 1
    if given >= 3:
        upper = (lo[0] + 1, 0, 0)
    elif given == 2:
        upper = (lo[0], lo[1] + 1, 0)
    else:
        upper = (lo[0] + 1, 0, 0)
    return vkey(ver) >= vkey(req) and vparse(ver)[0:3] < upper


def satisfies(ver: str, req: str) -> bool:
    return all(satisfies_one(ver, part) for part in (req.split(",") if "," in req else [req]))


# ── index access ─────────────────────────────────────────────────────────────


@lru_cache(maxsize=None)
def index_entries(crate: str) -> tuple[dict, ...]:
    """Every published version of `crate`, newest-relevant fields kept.

    The on-disk cache is a NUL-separated stream of index lines; the version
    strings are not sorted, so sorting happens here.
    """
    if not INDEX_CACHE.is_dir():
        raise FileNotFoundError(f"no index cache at {INDEX_CACHE}")

    rel = crate.lower()
    if len(rel) == 1:
        p = rel
    elif len(rel) == 2:
        p = f"2/{rel}"
    elif len(rel) == 3:
        p = f"3/{rel[0]}/{rel}"
    else:
        p = f"{rel[:2]}/{rel[2:4]}/{rel}"

    hits = list(INDEX_CACHE.glob(f"*/.cache/{p}"))
    if not hits:
        raise FileNotFoundError(f"{crate} is not in the local index cache — run `cargo fetch`")

    out: list[dict] = []
    for chunk in hits[0].read_bytes().split(b"\x00"):
        chunk = chunk.strip()
        if not chunk.startswith(b"{"):
            continue
        try:
            d = json.loads(chunk)
        except ValueError:
            continue
        if d.get("name") == crate:
            out.append(d)
    if not out:
        raise FileNotFoundError(f"no usable index entries for {crate}")
    return tuple(out)


def feature_set(crate: str, version: str) -> set[str]:
    """Features `crate@version` exposes, implicit ones included.

    The index splits the feature map in two: `features` and `features2`. That
    split is not cosmetic -- on reqwest 0.13.5 it is 6 entries against 24, and
    `json`, `charset`, `blocking` and `query` are ALL in `features2`. Reading
    only `features` produced seven confident false positives on first run,
    including "reqwest has no feature json". Both halves are merged here.
    """
    for d in index_entries(crate):
        if d["vers"] != version:
            continue
        declared = dict(d.get("features") or {})
        declared.update(d.get("features2") or {})
        feats = set(declared)

        optionals = set()
        for dep in d.get("deps") or []:
            if not dep.get("optional"):
                continue
            real = dep.get("package") or dep.get("name")
            if real:
                optionals.add(real)

        # Cargo only creates the implicit feature when the optional dependency
        # is NOT reachable only through an explicit `dep:foo` reference.
        dep_only = set()
        for members in declared.values():
            for m in members if isinstance(members, list) else []:
                if isinstance(m, str) and m.startswith("dep:"):
                    dep_only.add(m[4:])
        return feats | (optionals - dep_only)

    raise FileNotFoundError(f"{crate} has no index entry for {version}")


def newest_allowed(crate: str, req: str) -> str | None:
    """The version `cargo update` would choose: newest non-yanked match."""
    best: str | None = None
    for d in index_entries(crate):
        if d.get("yanked"):
            continue
        v = d["vers"]
        if "-" in v:  # prereleases are never selected by a bare requirement
            continue
        if not satisfies(v, req):
            continue
        if best is None or vkey(v) > vkey(best):
            best = v
    return best


# ── manifest walking ─────────────────────────────────────────────────────────


def manifests() -> list[Path]:
    root = tomllib.loads((ROOT / "Cargo.toml").read_text())
    out = [ROOT / "Cargo.toml"]
    for m in root.get("workspace", {}).get("members", []):
        p = (ROOT / m / "Cargo.toml").resolve()
        if p.exists():
            out.append(p)
    return [p for p in out if "references" not in p.parts]


def declared() -> dict[tuple[str, str, str], list[str]]:
    """(dep, requirement, feature) -> declaring manifests."""
    out: dict[tuple[str, str, str], list[str]] = {}

    def collect(table: dict, origin: str) -> None:
        for dep_name, spec in table.items():
            if isinstance(spec, str):
                spec = {"version": spec}
            if not isinstance(spec, dict):
                continue
            real = spec.get("package", dep_name)
            for f in spec.get("features") or []:
                key = (real, str(spec.get("version", "*")), f)
                out.setdefault(key, []).append(origin)

    for m in manifests():
        origin = str(m.relative_to(ROOT))
        data = tomllib.loads(m.read_text())
        for t in DEP_TABLES:
            collect(data.get(t, {}), origin)
        for target, tdata in data.get("target", {}).items():
            if isinstance(tdata, dict):
                for t in DEP_TABLES:
                    collect(tdata.get(t, {}), f"{origin} [{target}]")
    return out


def main() -> int:
    if not INDEX_CACHE.is_dir():
        print(f"✗ no cargo index cache at {INDEX_CACHE} — cannot verify features", file=sys.stderr)
        return 2

    findings: list[tuple[str, str, str, str, bool]] = []
    problems: list[str] = []
    checked = 0

    for (dep, req, feat), origins in sorted(declared().items()):
        origin = sorted(set(origins))[0]
        try:
            target = newest_allowed(dep, req)
        except ValueError as e:
            problems.append(f"{origin}: {dep} {req!r}: {e}")
            continue
        except FileNotFoundError as e:
            problems.append(f"{origin}: {dep}: {e}")
            continue

        if target is None:
            problems.append(f"{origin}: {dep} {req!r} matches no published version")
            continue

        try:
            feats = feature_set(dep, target)
        except (FileNotFoundError, ValueError) as e:
            problems.append(f"{origin}: {dep}@{target}: {e}")
            continue

        checked += 1
        if feat not in feats:
            # blocking=True means the feature exists in the LOCKED version, so
            # this is a silent pin rather than an ordinary typo.
            findings.append((dep, target, feat, origin, True))

    for p in problems:
        print(f"⚠ {p}")

    if findings:
        print()
        print(f"✗ {len(findings)} declared cargo feature(s) block an upgrade")
        print()
        for dep, target, feat, origin, _ in findings:
            print(f"  {dep} {target} has no feature {feat!r}")
            print(f"    declared in: {origin}")
        print()
        print(
            "  The locked version still has the feature, so cargo reports nothing\n"
            "  wrong: it just cannot move the dependency, and says so only in a\n"
            "  parenthetical while exiting 0. That is how reqwest sat at 0.13.1\n"
            "  for months after 0.13.2 deleted the optional `webpki-roots` dep.\n"
            "\n"
            "  A deleted feature is not a rename you can guess. Read the target\n"
            "  version's changelog and decide what it wants instead."
        )
        return 1

    if problems:
        print()
        print("✗ could not verify every declared feature (see the warnings above)")
        print("  A gate that cannot check must not report success.")
        return 2

    if checked == 0:
        # A vacuous pass. This gate exists to check DECLARED FEATURES; finding
        # none means it inspected nothing, and reporting "✓ 0 ... exist" is a
        # claim of compliance with no work behind it. A renamed directory, a
        # workspace restructure that moves every dependency behind
        # `[workspace.dependencies]`, or being invoked where the member
        # manifests are absent would all land here and retire the gate in
        # silence.
        #
        # Found by the house `check_empty_scope.py`, which runs every gate over
        # a skeleton repo holding the directory shape and the SHAPE_FILES but no
        # content. The root Cargo.toml came along, so this tool parsed it, found
        # no `[dependencies]` table (the root only carries `[workspace]` and
        # `[workspace.lints]`), and cheerfully printed a pass. Exit 2, because
        # "nothing to check" is not a finding -- it is an absence of evidence.
        print()
        print("✗ found no declared cargo features to check")
        print("  This gate verified nothing, so it will not report success.")
        print("  Expected: the workspace manifests declare dependencies with")
        print("  `features = [...]`. If that has genuinely become empty, delete")
        print("  this gate and the GOH_CI_STEPS entry rather than leave it inert.")
        return 2

    print(f"✓ {checked} declared cargo feature(s) exist at the newest version each manifest allows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
