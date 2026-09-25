# v0.40.0 — the device stack is Rust

If you only drive panels through the CLI or the GUI, **nothing here changes how
you drive them.** The verbs, the wire format, and the GUI are the same. This
release removes the machinery underneath.

**One daemon, one MCP server, no C.** The Python MCP server and the C encoder
chain (`libdivoom_compact.dylib`, its three sources, and the Python FFI wrapper
that loaded them) are deleted. The app now decodes, resizes, encodes, and
streams entirely in Rust. `divoom-control mcp-server` still works and is still
the entry point an MCP client config names — it hands off to `divoomd mcp` with
`execv`, so the pipe goes straight to the Rust server.

**The C's exact behaviour is preserved as test data.** 550 framing vectors and
192 image vectors, captured from the C itself, are committed and asserted byte
for byte, so this is a like-for-like substitution rather than a rewrite. Image
resizing on the device path uses nearest-neighbour, which is the behaviour the
app has had since LANCZOS-on-device was fixed.

## Breaking: removed from the installed `divoom_lib` package

v0.39.0 shipped these; v0.40.0 does not. If you imported them directly rather
than going through the CLI, GUI, or `divoom_client`, you must change:

- `divoom_lib.framing.encode_ios_le_payload` — use the daemon (or
  `divoom_client`), which frames in `divoomd::framing`
- `divoom_lib.framing.encode_basic_payload` — same
- `divoom_lib.framing.escape_payload`, `.get_checksum`, `.int2hexlittle` — pure
  wire helpers with no remaining caller; the daemon does this framing
- `divoom_lib.native_lib` (module) and `divoom_lib/native_src/` (C sources)
- `divoom_lib.mcp_server`, `divoom_lib.mcp_tools` — the Rust catalog is a strict
  superset (14 tools vs the Python 13, adding `list_screens`)

`divoom_lib.framing` still exports the two read-side functions,
`parse_ios_le_notification` and `parse_basic_protocol_frames`, and the
`divoom-control` console script keeps every subcommand it had.

Full detail: CHANGELOG.md.
