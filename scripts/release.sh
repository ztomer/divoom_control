#!/usr/bin/env bash
#
# release.sh — one-shot release for divoom-control. In order:
#   0. check GitHub CI is green for the commit being tagged [skippable]
#   1. build the DMG (scripts/build_release.sh)  [skippable]
#   2. git tag vX.Y.Z (annotated, notes from CHANGELOG) + push to origin
#   3. GitHub release on the code repo with the DMG attached
#   4. bump the Homebrew cask (version + sha256) in the tap repo
#
# The version is read from pyproject.toml — bump it there first. Idempotent:
# re-running clobbers the DMG asset and re-PUTs the cask, so a partial run is
# safe to resume.
#
# RELEASE RULE: a release is only cut when GitHub CI is green for the commit
# being tagged. The only exception is credit depletion (GitHub Actions billing
# exhaustion) — that is a money wall, not a code signal, so it does not block.
# release.sh auto-detects that failure and proceeds; use --skip-ci-check if
# detection ever misses.
#
#   scripts/release.sh                # full run
#   scripts/release.sh --skip-build   # reuse an existing dist/ DMG (faster)
#   scripts/release.sh --skip-ci-check  # skip the CI gate (only for credit depletion)
#
# Requires: gh (authenticated: `gh auth login`), the macOS build toolchain that
# scripts/build_release.sh needs, and push access to both repos below.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

REPO="ztomer/divoom_control"      # code repo — hosts the tag + release + DMG asset
                                  # (renamed from divoom_lib; the old name only redirects)
TAP="ztomer/homebrew-tap"         # cask repo
CASK_PATH="Casks/divoom-control.rb"

SKIP_BUILD=0
CHECK_CI=1
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --skip-build) SKIP_BUILD=1 ;;
    --skip-ci-check) CHECK_CI=0 ;;
    --dry-run) DRY_RUN=1 ;;
    *) echo "ERROR: unknown option: $arg" >&2; exit 1 ;;
  esac
done

# ci_gate — refuse to cut a release while GitHub CI is not green for the commit being
# tagged. One read through loopctl's door (DV.CIDOOR), which judges job by job with .gatesrc's
# LOOP_CI_ADVISORY: a duplicate-of-local job is reported, never blocking; a job local cannot
# reproduce blocks. A billing/credit-depleted CI is no verdict, so it is red here too; the
# loud way past a CI that cannot run is --skip-ci-check.
ci_gate() {
  local sha="$1" verdict rc=0
  echo "→ checking GitHub CI status for ${sha}"
  verdict="$(python3 "${DIVOOM_LOOPCTL:-$HOME/Projects/.loop/tools/loopctl.py}" ci "$sha" --repo divoom-control 2>&1)" || rc=$?
  case "$rc" in
    0) echo "  ✓ ${verdict}" ;;
    3) echo "  ERROR: ${verdict}. CI is still pending; wait for it to finish." >&2; exit 1 ;;
    4) echo "  ERROR: ${verdict}. No CI found for this commit." >&2; exit 1 ;;
    75) echo "  ERROR: ${verdict} -- not a failure, not a green; retry when it lifts." >&2; exit 75 ;;
    *) echo "  ERROR: ${verdict}. Refusing to cut a release on a CI that is not green." >&2
       echo "  (If CI cannot run at all, e.g. credit depletion, re-run with --skip-ci-check.)" >&2; exit 1 ;;
  esac
}

VERSION="$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")"
TAG="v${VERSION}"
DMG="dist/Divoom-${TAG}.dmg"      # name MUST match the cask url (Divoom-v#{version}.dmg)

echo "→ release ${TAG}  (repo ${REPO}, tap ${TAP})"

# ── preflight ───────────────────────────────────────────────────────────────
command -v gh >/dev/null || { echo "ERROR: gh CLI required (brew install gh)" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "ERROR: gh not authenticated — run: gh auth login" >&2; exit 1; }
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "⚠ working tree has uncommitted TRACKED changes — the tag will point at HEAD," >&2
  echo "  which does not include them. Commit or stash first, or press Ctrl-C." >&2
  sleep 3
fi
# The tagged commit must be HEAD of local main AND on origin/main (D.RELTAG): a hard
# refusal, never a warning. DIVOOM_RELEASE_GATE_ONLY stops here, for the tests.
# shellcheck source=/dev/null # goh's tui/lib.sh: outside this repo; gates_of_heck lints it
. "${GOH_DIR:-$HOME/Projects/gates_of_heck}/tui/lib.sh"
# shellcheck source=scripts/lib/release_branch_gate.sh
. "$ROOT/scripts/lib/release_branch_gate.sh"
divoom_release_branch_gate
[ -z "${DIVOOM_RELEASE_GATE_ONLY:-}" ] || exit 0

# Dry-run the push gate's tag check NOW, before the CI wait and the build. The
# pre-push hook refuses a tag whose commit declares no matching version, and it
# only finds out at `git push origin <tag>` -- step 3, after everything slow.
# v0.41.1 hit exactly that: the root Cargo.toml is a workspace with no version,
# and .gatesrc did not say where the version lives. Same check, same .gatesrc,
# read in a child shell so its keys do not leak into this one.
GOH="${GOH_DIR:-$HOME/Projects/gates_of_heck}"
NULL_SHA=0000000000000000000000000000000000000000
printf 'refs/tags/%s %s refs/tags/%s %s\n' "$TAG" "$(git rev-parse HEAD)" "$TAG" "$NULL_SHA" \
  | (set -a; [ ! -f .gatesrc ] || . ./.gatesrc; set +a
     bash "$GOH/gates/goh.sh" tag-version --root . --refs-file -) \
  || { echo "ERROR: the pre-push tag check would refuse ${TAG}; declare the version" >&2
       echo "  sources in .gatesrc (GOH_TAG_VERSION_SOURCES) -- nothing built or tagged." >&2; exit 1; }

# Release rule: only cut when GitHub CI is green for the commit being tagged
# (a billing-depleted CI is not green either; --skip-ci-check is the loud way past). See ci_gate above.
if [ "$CHECK_CI" -eq 1 ]; then
  ci_gate "$(git rev-parse HEAD)"
else
  echo "→ skipping CI check (--skip-ci-check)"
fi
# DIVOOM_RELEASE_CI_ONLY stops here, for the tests of ci_gate (nothing is built or tagged).
[ -z "${DIVOOM_RELEASE_CI_ONLY:-}" ] || exit 0

# ── 1. build DMG ────────────────────────────────────────────────────────────
if [ "$SKIP_BUILD" -eq 1 ] && [ -f "$DMG" ]; then
  echo "→ reusing existing ${DMG}"
else
  echo "→ building ${DMG}"
  bash scripts/build_release.sh
fi
[ -f "$DMG" ] || { echo "ERROR: ${DMG} not found after build" >&2; exit 1; }
SHA="$(shasum -a 256 "$DMG" | awk '{print $1}')"
echo "  sha256 ${SHA}"

# ── 2. release notes: every CHANGELOG section newer than the last published
#      release (so a catch-up release covers all of it; a normal release is just
#      the one new section). ──────────────────────────────────────────────────
LAST="$(gh release list --repo "$REPO" -L 1 --json tagName --jq '.[0].tagName' 2>/dev/null || true)"
NOTES="$(mktemp)"
trap 'rm -f "$NOTES"' EXIT
VER="$VERSION" LAST="${LAST#v}" python3 - > "$NOTES" <<'PY'
import os, re
ver = os.environ["VER"]; last = os.environ.get("LAST", "")
text = open("CHANGELOG.md").read()
start = re.search(r'^## v%s\b' % re.escape(ver), text, re.M)
if not start:
    print(f"Release {ver}"); raise SystemExit
end = None
if last:
    e = re.search(r'^## v%s\b' % re.escape(last), text, re.M)
    if e:
        end = e.start()
if end is None:  # no known prior release → just this one section
    nxt = re.search(r'(?m)^## v', text[start.end():])
    end = start.end() + nxt.start() if nxt else len(text)
print(text[start.start():end].strip())
PY

# ── 3. git tag + push ───────────────────────────────────────────────────────
if git rev-parse "$TAG" >/dev/null 2>&1; then
  echo "→ tag ${TAG} already exists (leaving it)"
else
  echo "→ tagging ${TAG} at $(git rev-parse --short HEAD)"
  git tag -a "$TAG" -F "$NOTES"
fi
echo "→ pushing tag to origin"
git push origin "$TAG"

# ── 4. GitHub release (+ DMG asset) ─────────────────────────────────────────
if gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then
  echo "→ release ${TAG} exists — clobbering the DMG asset"
  gh release upload "$TAG" "$DMG" --repo "$REPO" --clobber
else
  echo "→ creating GitHub release ${TAG}"
  gh release create "$TAG" "$DMG" --repo "$REPO" --title "$TAG" --notes-file "$NOTES"
fi

# ── 5. bump the Homebrew cask (version + sha256) ────────────────────────────
# Goes through the tap's OWN gate: tap_bump.sh clones the tap, moves the version,
# every url and every sha256, commits, runs the tap's tools/gate.sh --full, and
# pushes the commit pinned. A red gate pushes nothing. --dry-run shows the gate
# step without pushing.
echo "→ bumping cask ${TAP}/${CASK_PATH} → ${VERSION}"
TAP_BUMP_ARGS=(--tap "${TAP}" --cask divoom-control --tag "${TAG}" --artifact "${DMG}")
if [ "${DRY_RUN}" = "1" ]; then
  TAP_BUMP_ARGS+=(--dry-run)
fi
"${GOH_DIR:-$HOME/Projects/gates_of_heck}/tools/release-kit/tap_bump.sh" "${TAP_BUMP_ARGS[@]}"

echo ""
echo "✓ released ${TAG}"
echo "  release: https://github.com/${REPO}/releases/tag/${TAG}"
echo "  install: brew install --cask ztomer/tap/divoom-control"
