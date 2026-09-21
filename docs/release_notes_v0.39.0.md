# v0.39.0 — MCP negotiation, Python 3.14 floor, menubar off tao

No device-protocol change. If you only drive panels, nothing here affects you.

**MCP speaks your version.** Both servers — the native `divoomd mcp` and
`divoom-control mcp-server` — answer `initialize` with the client's
requested protocol version when it is one they support (`2024-11-05`
through `2026-07-28`), else the latest (`2026-07-28`).

**Python 3.14 is now the floor.** The package requires `>=3.14` (what CI,
the dev venv and the shipped app already build on) and `pillow>=12` (whose
`get_flattened_data()` replaces the `getdata()` Pillow 14 removes).

**The menubar no longer pulls GTK anywhere.** The event loop moved from
`tao` (which depended on GTK3 on Linux targets) to `winit 0.30`, and
`tray-icon` dropped its Linux-only defaults. The dependency lock shrank
405→381 crates and the security-audit exemption list is empty.

Full detail: CHANGELOG.md.
