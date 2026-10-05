# docs/ index

## Current / canonical (read these)
- **[../README.md](../README.md)** — project overview, install, run.
- **[../ARCHITECTURE.md](../ARCHITECTURE.md)** — system map (3 packages + daemon +
  protocols + transports + platform support).
- **[ROADMAP.md](ROADMAP.md)** — the one forward-looking doc: open work, current
  debt, hardware reference. Update every round.
- **[../CHANGELOG.md](../CHANGELOG.md)** — shipped milestones.
- **[../AGENTS.md](../AGENTS.md)** — conventions for agents.

## Protocol reference
- **[CHANNEL_ARCHITECTURE.md](CHANNEL_ARCHITECTURE.md)** — channel modes, light
  toggles, wire formats, APK divergences. The primary protocol doc.
- **[APK_COMPARISON.md](APK_COMPARISON.md)** — byte-level frame encoding, BLE
  framing, animation streaming — verified against decompiled APK.
- **[CUSTOM_CHANNEL_VS_APK.md](CUSTOM_CHANNEL_VS_APK.md)** — custom art push,
  hot channel, 0xBD/0xB1/0x8C wire formats.
- **[MCP_SERVER.md](MCP_SERVER.md)** — the MCP server (daemon-routed, R28).
- **[CAPABILITY_MAP.md](CAPABILITY_MAP.md)** — who owns what; the census verdicts
  from R70-R72.
- **[NOTIFICATIONS_SETUP.md](NOTIFICATIONS_SETUP.md)** — macOS notification setup.
- **Device bitmap font** — `divoom_lib/fonts/` + `scripts/extract_apk_font.py`.
- **[divoom_docs/](divoom_docs/)** — captured upstream/device docs.
- **[cloud_api/](cloud_api/)** — cloud HTTP API catalog (533/533 endpoints).

## Operations
- **[RELEASING.md](RELEASING.md)** — release process (.dmg, Homebrew cask).
- **`scripts/ci_local.sh`** — the full CI-equivalent gate; run before pushing.
- **`scripts/gui_pov.py`** — drive the real GUI against a real daemon and report
  what a user would see. Use before calling anything user-facing "done".

## Historical
`docs/archive/` is gone entirely (2026-08-30) — round plans, superseded
workstream plans and the R3–R64 handoff archive were all point-in-time records,
and keeping them alongside the live docs is how a graveyard misleads the next
session into reading a stale plan as current.

For current state read ROADMAP + the canonical docs above.
`docs/SESSION_HANDOFF.md` was folded into ROADMAP (open work) and CHANGELOG
(per-round narrative) on 2026-10-05 and deleted.
For what shipped, read CHANGELOG. To recover a pruned file:

```
git log --diff-filter=D -- 'docs/**/PLANNING_*'      # round plans
git log --diff-filter=D -- 'docs/archive/*'          # handoff + superseded
git log -p -- docs/SESSION_HANDOFF.md                # the retired handoff file
```
