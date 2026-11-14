#!/usr/bin/env bash
#
# ship_release.sh VERSION -- `goh ship`'s release kit for divoom-control (.gatesrc GOH_SHIP_RELEASE,
# GOH_SHIP_RELEASE_PUSHES=1; DV.SHIPKIT). goh runs it as `goh ship --bump patch`'s release step with
# the next version; scripts/release.sh (CI check, DMG, tag, GitHub release, cask) stays the one place
# a release is cut and still runs by hand. What release.sh cannot do for itself is the part before it:
#
#   1. bump       the version in every place it lives (scripts/bump_version.py), then CHANGELOG.md's
#                 Unreleased cut into `## vX.Y.Z -- <summary>` (goh's changelog_cut.py, title from
#                 GOH_SHIP_SUMMARY), committed as `chore(release): version X.Y.Z - <summary>`.
#                 When HEAD's pyproject already declares VERSION (a resumed ship, or a bump followed
#                 by fix commits) the bump is skipped, and any entries Unreleased gained since are cut
#                 into VERSION's stanza and committed (DV.SHIPCUT), so the check below never meets
#                 a release whose Unreleased still holds lines.
#   2. push       HEAD to origin/main through the pre-push gate. release.sh refuses a tag whose commit
#                 is not on origin/main (D.RELTAG), so the release commit must be there first; this is
#                 why the kit pushes and goh's own push step is skipped (GOH_SHIP_RELEASE_PUSHES=1).
#   3. CI         not here: hosted CI is advisory (owner 2026-11-11; EST.CIWAIT, as goh GOH.CIWAIT).
#                 release.sh reads it ONCE through loopctl's door; nothing in either script waits.
#   4. release    exec scripts/release.sh, which reads CI once (red refuses; pending is advisory over the push gate), builds the DMG, tags,
#                 pushes the tag, creates the release and bumps the cask.
#
#   scripts/ship_release.sh 0.45.2
#
# Seams (the tests): the release step is scripts/release.sh beside this file. Nothing is asked of GitHub except through those.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
GOH="${GOH_DIR:-$HOME/Projects/gates_of_heck}"
# shellcheck source=/dev/null # goh's tui/lib.sh: outside this repo; gates_of_heck lints it
. "$GOH/tui/lib.sh"

[ $# -eq 1 ] || die "usage: scripts/ship_release.sh X.Y.Z"
V="${1#v}"
[[ "$V" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "version must be MAJOR.MINOR.PATCH, got '$1'"
SUMMARY="${GOH_SHIP_SUMMARY:-}"

[ "$(git rev-parse --abbrev-ref HEAD)" = "main" ] \
  || die "release refused: HEAD is not the branch main -- a release is cut from main; nothing changed"
[ -z "$(git status --porcelain --untracked-files=no)" ] \
  || die "release refused: uncommitted tracked changes -- the release commit would carry them; nothing changed"

# Whether any `## Unreleased` section of CHANGELOG.md holds a non-blank line.
unreleased_holds() {
  awk '/^## /{u = ($0 ~ /^## \[?[Uu]nreleased\]?([[:space:]]|$)/); next} u && NF {f = 1} END {exit !f}' CHANGELOG.md
}
commit() { # Through the pre-commit hook, never around it. The trailer is the caller's, if it has one.
  if [ -n "${DIVOOM_RELEASE_TRAILER:-}" ]; then
    git commit -q -m "$1" -m "$DIVOOM_RELEASE_TRAILER"
  else
    git commit -q -m "$1"
  fi
  ok "committed $(git rev-parse --short HEAD)"
}

DECLARED="$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")"
if [ "$DECLARED" = "$V" ]; then
  info "pyproject.toml already declares ${V} -- not bumping again"
  # DV.SHIPCUT: entries added under Unreleased after the bump (fix commits, as agents are told to
  # write them) ship with this tag, so they move into its stanza here, not by hand.
  if unreleased_holds; then
    info "Unreleased holds entries landed after the bump -- moving them into the v${V} stanza"
    python3 "$GOH/tools/release-kit/changelog_cut.py" cut --version "$V" --file CHANGELOG.md \
      || die "CHANGELOG cut refused (above) -- nothing committed"
    git add CHANGELOG.md
    commit "chore(release): v${V} takes the entries Unreleased gained after its bump"
  fi
else
  info "bumping ${DECLARED} → ${V}"
  python3 scripts/bump_version.py "$V" || die "version bump refused (above)"
  cut=(python3 "$GOH/tools/release-kit/changelog_cut.py" cut --version "$V" --file CHANGELOG.md)
  [ -z "$SUMMARY" ] || cut+=(--title "$SUMMARY")
  "${cut[@]}" || die "CHANGELOG cut refused (above) -- version files changed, nothing committed"
  git add pyproject.toml divoomd/Cargo.toml divoom-menubar/Cargo.toml Cargo.lock CHANGELOG.md
  msg="chore(release): version ${V}"
  [ -z "$SUMMARY" ] || msg="${msg} - ${SUMMARY}"
  commit "$msg"
fi
python3 "$GOH/tools/release-kit/changelog_cut.py" check --version "$V" --file CHANGELOG.md \
  || die "CHANGELOG has no clean stanza for ${V} (above) -- nothing pushed"

info "pushing $(git rev-parse --short HEAD) to origin/main"
git push origin HEAD:refs/heads/main || die "push refused (above) -- nothing tagged"

exec bash scripts/release.sh
