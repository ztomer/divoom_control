# v0.38.0 — the direct-to-device library retired to examples/

No change on the daemon path. If you never imported `divoom_lib` yourself,
nothing here affects you.

**What moved.** 77 of `divoom_lib`'s 104 modules — the `Divoom` facade and
everything only it reached (BLE/LAN/SPP transports, the display / system /
tools / scheduling / media command groups, `cloud`, the Python encoders,
`wall`, `monthly_best_daemon`) — are now `examples/divoom_legacy/`, a
standalone package with its own 1413-test suite and the example scripts
beside it. The `divoomd` daemon owns every one of those capabilities; the
production import closure never reached the Python. `from divoom_lib import
Divoom` no longer works; use `divoom_client.DaemonDeviceProxy`, or put
`examples/` on your path and import `divoom_legacy`.

**What stays in `divoom_lib`.** Framing, models, the transport interface,
cloud auth, the native-library loader, the CLI and the MCP server (both
daemon clients), and the font blobs the daemon embeds.

**What keeps it that way.** A production-scope gate fails on any
`divoom_legacy` import; the retired code remains the executable spec the
daemon's `device_call` arms are gated against.

Full detail: CHANGELOG.md.
