#!/usr/bin/env bash
# release_branch_gate.sh -- the ONE place that decides whether HEAD may be tagged
# as a release. Sourced, not run, by scripts/release.sh:
#
#   . "$ROOT/scripts/lib/release_branch_gate.sh"
#   divoom_release_branch_gate
#
# The rule (D.RELTAG): a release tag names a commit that is on origin's main. release.sh
# used to WARN when HEAD was not `main` and tag HEAD regardless, so a tag could name a
# side-branch commit or a commit that exists only on this machine. Now, fail closed:
#
#   * HEAD is the branch `main` (not a side branch, not detached);
#   * origin is fetched (a fetch that fails refuses: an unverifiable claim is no pass);
#   * HEAD is an ancestor of, or equal to, origin/main -- a local-only commit is refused.
#
# Needs tui/lib.sh (die, ok) already sourced. Tests: tests/test_release_branch_gate.py.

divoom_release_branch_gate() {
  local branch="main" current
  current="$(git rev-parse --abbrev-ref HEAD)"
  if [ "$current" != "$branch" ]; then
    die "release refused: HEAD is '${current}', not ${branch} -- a release tag must name a commit on origin/${branch}; check out ${branch} (merged and pushed) and release again"
  fi
  git fetch --quiet origin "$branch" \
    || die "release refused: could not fetch origin/${branch}, so HEAD cannot be shown to be on it -- nothing tagged"
  if ! git merge-base --is-ancestor HEAD "origin/${branch}"; then
    die "release refused: HEAD $(git rev-parse --short HEAD) is not on origin/${branch} (a local-only commit) -- push it through the gate first, wait for CI, then release; nothing tagged"
  fi
  ok "HEAD $(git rev-parse --short HEAD) is on origin/${branch}"
}
