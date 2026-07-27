# docs/ index

## Current / canonical (read these)
- **[../README.md](../README.md)** — project overview, install, run.
- **[../ARCHITECTURE.md](../ARCHITECTURE.md)** — system map (3 packages + daemon +
  protocols + transports + platform support).
- **[SESSION_HANDOFF.md](SESSION_HANDOFF.md)** — live cross-session state + open
  threads. Update every round.
- **[ROADMAP.md](ROADMAP.md)** — shipped rounds, open workstreams.
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
- **[NOTIFICATIONS_SETUP.md](NOTIFICATIONS_SETUP.md)** — macOS notification setup.
- **Device bitmap font** — `divoom_lib/fonts/` + `scripts/extract_apk_font.py`.
- **[divoom_docs/](divoom_docs/)** — captured upstream/device docs.
- **[cloud_api/](cloud_api/)** — cloud HTTP API catalog (533/533 endpoints).

## Operations
- **[RELEASING.md](RELEASING.md)** — release process (.dmg, Homebrew cask).

## Historical (planning rounds)
Archived under `docs/archive/rounds/`. Each is a point-in-time record; for
current state read SESSION_HANDOFF + ROADMAP + the canonical docs above.
