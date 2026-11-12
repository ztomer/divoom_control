"""The workflow's repo checkout fetches the whole history and its tags, and goh is a NAMED release.

DV.FETCHDEPTH (2026-11-11). `goh changelog-tags` judges CHANGELOG.md against the repository's `v*`
tags. `actions/checkout` at its default depth is shallow and carries only the tags its fetch named,
so since goh 33b1b13 (GOH.TAGLESSCI) the runner printed `NOT JUDGED` and never judged; before that it
read the partial set as a clean changelog. Every checkout of THIS repository therefore sets
`fetch-depth: 0` and `fetch-tags: true`. The goh checkouts ride a released tag, never a moving ref,
and every job rides the same one.
"""

from __future__ import annotations

import pathlib
import re

import yaml

WORKFLOW = pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows" / "tests.yml"
# The oldest goh whose changelog-tags says NOT JUDGED on a shallow clone (GOH.TAGLESSCI landed
# after v0.100.0 and is released in v0.101.x); raise this with the workflow, never lower it.
GOH_FLOOR = (0, 101, 1)


def _checkouts() -> list[tuple[str, dict]]:
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    return [
        (name, step.get("with") or {})
        for name, job in jobs.items()
        for step in job.get("steps", [])
        if str(step.get("uses", "")).startswith("actions/checkout")
    ]


def test_every_checkout_of_this_repo_fetches_history_and_tags():
    own = [(j, w) for j, w in _checkouts() if "repository" not in w]
    assert own, "no checkout of this repository: the scan is looking at the wrong file"
    bad = [j for j, w in own if str(w.get("fetch-depth")) != "0" or str(w.get("fetch-tags")).lower() != "true"]
    assert not bad, f"jobs whose own checkout is shallow or tagless: {bad}"


def test_goh_is_a_named_release_at_or_above_the_floor_in_every_job():
    refs = {
        (j, str(w["ref"]).split("#")[0].strip())
        for j, w in _checkouts()
        if str(w.get("repository", "")).endswith("/gates_of_heck")
    }
    assert refs, "no goh checkout found"
    for job, ref in refs:
        m = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", ref)
        assert m, f"{job}: goh ref {ref!r} is not a vX.Y.Z release tag"
        assert tuple(map(int, m.groups())) >= GOH_FLOOR, f"{job}: goh {ref} is older than the floor"
    assert len({ref for _, ref in refs}) == 1, f"jobs ride different goh releases: {sorted(refs)}"
