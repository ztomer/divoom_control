# Session Handoff — read this first

**Consolidated roadmap**: `docs/ROADMAP.md` — shipped rounds, open workstreams.
This file tracks the per-round current state and open threads.

This is the **cross-agent session state**. opencode and Claude Code keep their
own conversation stores. THIS FILE + git history + CHANGELOG + ROADMAP are the
shared memory. Read this on entry and **update it at the end of every round**
(see the core rule in `AGENTS.md`).

## How to resume

- **opencode**: `opencode -s ses_f6a64811fffeYyM9ixX43QtgDz` (or `opencode export <id>`).
- **Claude Code**: reads `CLAUDE.md` → `AGENTS.md` → this file, plus `git log`.
- Both: `git log --oneline`, `CHANGELOG.md`, `docs/ROADMAP.md`.
- This file is the CURRENT state, not an archive. Once a round ships and its
  CHANGELOG stanza is written, its entry here is pruned to git history (house
  rule: one forward-looking doc). To recover older context:
  `git log -p -- docs/SESSION_HANDOFF.md` for past entries,
  `git log --diff-filter=D -- 'docs/**/PLANNING_*'` for round plans.

## Current state — _update this section each round_

- **2026-09-25 — L5 unit 1 DONE (uncommitted): the native MCP reaches a remote
  daemon, so the Python shell's last unique capability is closed.** Measured
  first: the native catalog is a strict superset of the Python one (14 vs 13 =
  the same 13 plus `list_screens`), so transport was the only thing keeping
  ~860 lines of second implementation alive. `divoomd/src/daemon_target.rs` now
  selects the daemon exactly as `divoom_client/daemon_protocol.py` does
  (`DIVOOM_DAEMON_HOST`/`_PORT`/`_TOKEN` over `DIVOOM_SOCKET`), and the token
  rides in the request BYTES — proven by a test that binds a real
  `TcpListener` in-process and reads the request back off the wire.
  `mcp_tools.rs` hit the 500-line cap doing it, so it split into `mcp_tools.rs`
  (the MCP surface) + `mcp_daemon.rs` (the request/reply plumbing). `libloading`
  left `divoomd/Cargo.toml` — `cargo machete` in gate step 15 flagged it as unused
  the moment the FFI wrapper went, and it was removed rather than exempted.
  `gen_commands.py` now runs `cargo fmt` on its own output, because regenerating
  used to leave the tree failing the workspace fmt gate.
  **Next for L5, in order:** (1) make `divoom-control mcp-server` delegate to
  `divoomd mcp` so the entry point and its `--host/--port/--token` flags keep
  working, then delete `divoom_lib/mcp_server.py` + `mcp_tools.py` — the test
  surgery is the real work: 30 tests in `test_mcp_server.py`, 32 in
  `test_mcp_tools.py`, plus `test_mcp_server_cli_stdio.py` and
  `test_mcp_server_handle_edges.py`, all of which test the Python implementation
  rather than the contract; the native side has only 4 tests, so the
  consolidation should add native coverage rather than just delete Python tests.
  (2) clap verbs for `cli_commands.py` (444 lines). Guard against the obvious
  mistake: the delegation must be proven by an e2e that runs the real
  `divoom-control mcp-server`, sends `tools/list`, and gets the 14 tools — not
  by asserting the module was deleted.

- **2026-09-25 — L4 COMPLETE (uncommitted): the C encoder chain is deleted, the
  daemon encodes in Rust.** `divoomd::image_encode` (0x49 frame, 0x44 static,
  32x32) and `divoomd::framing` (0x49/basic) replaced the library; the port is
  byte-exact against 192 + 550 vectors captured FROM the C, and every unit was
  red-once proven. `native_encode.rs`, `Daemon::encoder()`, the dylib, the six C
  sources, `native_lib.py`, `build_libdivoom.sh`, the `DIVOOMD_ENCODER_LIB`
  hand-off, the wheel's native globs, the Makefile `native` target, the release
  script's step 1 and py_ci's dylib step are ALL gone.
  Three things the next session should know rather than re-derive:
  (1) `test_build_platform_gate.py` was deleted WITH its subject — it drove the C
  script's arch gate. The policy now lives in `scripts/release.sh` (`arch:
  :arm64` on the cask) and `scripts/check_linux_build.sh` (Linux triple); a NEW
  native build script needs that gate back, and ARCHITECTURE.md says so.
  (2) `multi_device_routing.rs` used to wrap its real assertion in
  `if d.encoder().is_some()` and so asserted NOTHING on any machine without the
  C built. It is unconditional now. Worth remembering as a class: a guard added
  for a missing dependency silently removes the test that depended on it.
  (3) The Python-side image encoders in `examples/divoom_legacy` are still
  there and are now the ONLY Python implementation of the encoders. They are not
  shipped (pyproject excludes `examples*`) and nothing in the product calls them;
  they survive as the cross-check the image-vector generator compares the C
  against. When the C is gone that cross-check has nothing to compare, so the
  generator will fail loudly rather than silently — expected, and the file's
  docstring says why.
  Verified: 331 Rust tests, 25 menubar, clippy 0, 1548 Python tests (1
  pre-existing camoufox browser drift). L1–L4 of the rustification roadmap are
  now done in this repo; what remains for it is L5 (thin CLI/MCP over the daemon
  socket) and the repo's own K-style JNI work in `koffee_big`.

- **2026-09-25 — L4 step 2 DONE (uncommitted): the Python framing half is gone;
  the C stays, and the gate now says which is which.** `divoom_lib/framing.py` is
  parse-only (its two encoders and the ctypes loader deleted);
  `tests/test_framing_both_impls.py` deleted, its round-trip coverage moved to
  `divoomd/tests/framing_round_trip.rs`; test fixtures that need device bytes get
  them from `tests/support/framing_fixtures.py`, which reads the C's own
  550-vector record and REFUSES an unrecorded payload rather than inventing
  bytes (three hand-typed literals in the first draft were wrong — a length
  field, a checksum, an end byte).
  **The mistake, since the next session will hit the same edge:** this round
  deleted `libdivoom_compact.dylib`, `divoom_lib/native_src/*.c` and
  `scripts/build_libdivoom.sh` because the framing cutover had removed the last
  live caller — true of the framing functions, false of the library.
  `divoomd/src/native_encode.rs` loads the SAME dylib for the image encoders and
  there is no fallback: without it `wall.rs` returns false and `display.rs`
  answers "encoder not available", so image display breaks. All of it is
  RESTORED (the build script was re-verified by rebuilding; the committed binary
  is unchanged, so the diff carries no artifact churn).
  `tests/test_no_native_encoder_chain.py` encodes the true state and would have
  caught it: no Python framing encoder shipped, the vector record present and
  dense, the C's consumers still naming it, AND the dylib plus sources actually
  present. The first version of that gate PASSED with the dylib removed from the
  index — it asserted what depends on the library without asserting the library
  was there, which is the hole the mistake fell through. Red-once proven both
  ways since.
  **What L4 still needs, in order:** port the 16x16 palette encoder, the 32x32
  encoder, the 0x8B chunker and LANCZOS3 downsampling to Rust; prove them
  against `divoomd/tests/image_vectors.json` and
  `divoomd/tests/native_encode_parity.rs`; make `display.rs` stop refusing when
  no encoder is present; THEN delete the C, the sources and the build script,
  and delete `test_the_c_library_the_image_path_needs_is_actually_present` and
  `test_the_image_half_is_still_c_on_purpose` with them. The gate names that
  order in its failure message so the next session does not have to remember it.
  Verified: 323 Rust tests, clippy 0, 1559 Python tests (1 pre-existing
  environmental failure: camoufox drifted to beta.30 against a beta.29 pin).

- **2026-09-25 — L4 cutover step 1 DONE (uncommitted): the daemon frames, the
  bridge writes bytes.** `divoomd/src/spp_bridge_protocol.rs` (new) owns the
  co-process message contract; `spp.rs::send_command` now calls
  `write_command_line`, which frames with `crate::framing` and hex-encodes;
  `divoom_client/spp_bridge.py` reads `{"command":"write","frame":"<hex>"}` and
  calls the new `BTSppTransport.send_frame(bytes)`. The old
  `payload`+`framing`+`packet_number` form is refused by name in the bridge
  (a bridge old enough to get it is a mismatched install; ignoring it would
  write nothing and report success). DELETED as unable to exist without a
  Python encoder: `BTSppTransport.send_command`/`send_payload`/
  `send_command_and_wait_for_response` (no in-tree caller outside tests) and
  their `DeviceTransport` declarations; the tests that covered only them went
  with them, and the `wait_for_response` tests were kept. The `send_payload`
  retry loop also went: the live SPP path never had one, so no regression, but
  a retry now belongs on `send_frame` or the daemon if anyone wants one —
  recorded rather than smuggled in. Proof: every frame asserted against the 550
  committed C-derived vectors through the new path, both framings of the same
  command asserted identical, all 256 byte values through the hex, 317 Rust
  tests, 101 SPP Python tests, 1606 Python tests overall (3 pre-existing
  failures: camoufox browser drifted to beta.30 against a beta.29 pin, and two
  that were MINE and are now fixed — see below). 7 red-once perturbations along
  the way, including three of my own new test expectations that were wrong.
  **Fixture-format defect found and fixed:** the 550-vector JSON was written
  with `indent=2`, i.e. 23,895 lines, past the repo's own 15,000-line
  corruption ceiling (`test_no_runaway_file_growth.py` — a real gate catching a
  real shape). One line per case now: 560 lines, and a diff a human can read.
  Next: step 2 — the content gate (no `.dylib`/`.so`/`.c` tracked for this
  chain), then delete `divoom_lib/native_src/`, the committed dylib,
  `scripts/build_libdivoom.sh`, the ctypes block and the two encoders in
  `divoom_lib/framing.py` (the PARSE side stays — the bridge reads
  notifications), and the `pyproject.toml` package-data entry. Note for that
  step: `nowplaying/native/libnp_helper.dylib` is ALSO tracked, so a
  tree-wide "no .dylib" gate is red for a different crate's reason — scope the
  gate to this chain and say so, or fold nowplaying in deliberately.
  Also: the kill criterion is ANSWERED, not assumed — the live framing
  functions are scalar C with no SIMD; the only NEON is a 48-byte row copy in
  `compact_tiles` (NEON vs `memcpy`, byte-identical by construction) which has
  no live caller at all.

- **2026-09-25 — L2 commands as a type DONE (uncommitted).**
  Three generated files: `commands.rs` (the name→id table callers use today,
  plus the counts), `command_model.rs` (a `Command` enum — 105 variants, one per
  protocol ID, covering 109 names — with `ALL`, `TryFrom<u8>`, `TryFrom<&str>`),
  and `command_names.rs` (`CANONICAL_NAMES`, `COMMAND_NAMES`, `command()`,
  `command_id()`). Split at the repo's 500-line cap, which the pre-commit
  structural gate enforces: one file was 761 lines and the gate refused the
  commit. `commands::command_id` is RE-EXPORTED from the new module rather than
  moved — an integration test imports that path, and a public spelling that
  silently disappears is its own outage. ID-FIRST is forced by the protocol: 109 names map to
  105 ids and four ids are spelled two ways, so a variant per NAME would have
  left four pairs with equal discriminants and a `TryFrom<u8>` that could not be
  total. The second spelling rides as `#[doc(alias)]`. Both artefacts are
  emitted by `scripts/codegen/gen_commands.py`, so Python is still the only
  writer. `tests/test_command_model_parity.py` (9 tests) checks both
  directions, the two counts, and the absence of `as u16` casts in the daemon;
  red-once proven twice (delete a variant → 3 red; delete one `COMMAND_NAMES`
  entry → only the currency test red, because the variant survives — the exact
  hole a table-only lookup ships). Model tests are in
  `divoomd/src/commands_tests.rs`, NOT in the generated file: a test module in
  a generated file is erased by the next run without ever failing. Two
  generated 105-arm matches were replaced with table lookups after clippy
  flagged them (a function that grows with the protocol is what that file
  exists to prevent), and the regen-comparison test ignores rustfmt's
  whitespace and trailing commas so it is order-independent — proven from both
  the formatted and the raw generated state. Verified: `cargo test -p divoomd
  --no-default-features` 310 passed, `divoom-menubar` 25 passed + builds,
  clippy `-p divoomd` clean (0 warnings, was 107), `cargo fmt` clean, pytest
  `-k "command or framing or bridge"` 212 passed / 4 skipped.
  Not done: no call site cut over to the enum (the table's `command_id()` is
  unchanged and nothing in the daemon used it anyway — L4 is where the string
  keying goes), and `docs/ROADMAP.md` carries no new stanza for L2 yet.
  Next: L4 (`native_encode.rs` replacing `compact_tiles`/Lanczos/`encode_*`,
  byte-parity vectors + a no-`.dylib`-in-tree gate), which is the first phase
  that DELETES code; L2's remaining value is the type, not the cutover.

- **2026-09-25 — G0 bridge-IDL freeze + L1 protocol lock DONE (committed as
  `1ad0110` and `ac05135`; the entries below still say "uncommitted", which is
  now stale).**
- **2026-09-25 — G0 bridge-IDL freeze DONE (uncommitted).** First autonomous
  rustification step: `divoom_gui/bridge_idl.json` v1 pins the JS↔Python seam
  (113 bridge methods incl. 65 JS-called, 5-method window denylist, 7 push
  events + 2 lifecycle edges) and `tests/test_bridge_idl.py` (6 tests) fails
  on any unlisted method/event. Proven red once (dropped one IDL entry →
  1 failed; restored → 6 passed) and green beside the suite
  (`test_control_server` + auth + event-forwarder: 39 passed). Next: L1
  framing parity vectors (`framing.rs` vs Python), then §2 kernels.
- **2026-09-25 — L1 protocol lock DONE (uncommitted).** Python now consumes the
  shared `divoomd/tests/framing_vectors.json` via `tests/test_framing_vectors.py`
  (5 tests: encode_basic/ios_le + parse both reproduce committed vectors, plus
  a resync-vector-presence pin for the MAX_BASIC_FRAME stall guard). Proven red
  once (flipped one vector byte → 1 failed; restored → 5 passed). Both suites
  agree: Python 5 passed, Rust `framing_parity` 4 passed; BLE-free build
  redone after the test run. Next: §2 kernels (colour first).

- **2026-09-21 — release train BLOCKED at push (v0.39.0 ready, 6 commits, NOT pushed).** Train complete up to push: (a) MCP negotiation `eb12b95` [fmt fix squashed in], (b) Python floor `8c478ad`, (c) tray-icon trim `2426bfb` (intermediate reconstructed: tao kept, 400-crate lock, gtk under tao only — builds, 25 tests), (d) tao→winit `d44f689` (main.rs reconstructed from the recorded diff after an overwrite destroyed the working file; proven by build + 25 tests + clippy `-D warnings` + fmt + machete + `--version`/8s-live-run smoke; 381-crate lock, audit green empty), (e) workflow comment + round docs `64da745`, plus bump `4ad81b4` (0.39.0: pyproject + both product crates + lock via cargo + CHANGELOG rename + `docs/release_notes_v0.39.0.md`). Docs: CHANGELOG covers all five changes; stale refs fixed (README 3.10+→3.14, ARCHITECTURE/README-tree/parity-docstring tao→winit; 2024-11-05 only as supported-echo; no `needs GTK` left); no scratch files; dylib rebuilds restored via checkout (ci_local rebuilds it every run). Verification: cargo audit green empty; divoomd builds; MCP e2e 23 passed (was 22+1 skip — Rust negotiation proven on the wire); ci_local 23/24 with documented `DIVOOMD_ENCODER_LIB` workaround; camoufox browser re-pinned beta.29 (this machine had drifted to beta.30). BLOCKER (not this train's content): `check_no_allow.py` policy changed 2026-09-20 to fail on `#[expect]` too — tree has 136, all pre-dating the train (proven: identical 136 on a v0.38.0 worktree; newest blame 2026-09-07), so the pre-push hook refuses the push AND GitHub CI (same script, no excludes) would go red. Fixing 136 expects is its own round (house-gate migration without a ratchet — owner call, not a smuggled 136-site edit). Also environmental: fleet_routing 2 fail without the encoder env var (shared target dir; green with it — same before the train). Did NOT push (--no-verify refused as gate bypass), did NOT run release.sh (red CI; --skip-ci-check is billing-only), did NOT install (no dist bundle; follows release). NEXT: owner decides — (i) authorize the expect-removal round, or (ii) house-level ratchet in gates_of_heck — then push, CI-green watch, release.sh, install_local.sh + daemon proof.

- **2026-09-21 — tao → winit: last gtk edge GONE, audit ignores deleted — UNCOMMITTED, owner review pending.** Owner-authorized rewrite of the menubar main loop. `tao 0.37.0` (latest) depended on `gtk ^0.18` non-optionally on Linux targets; replaced with `winit 0.30.13` (latest stable; 0.31 is beta, house rule says stable), `default-features = false`. Result: `cargo tree --target all -i gtk/-glib/-proc-macro-error` all print "did not match any packages"; lock 405→381 crates; `cargo audit` green with `ignore = []`, so all 11 stale entries DELETED from `.cargo/audit.toml` (each verified no longer firing). Winit defaults would have added a 12th (`ttf-parser` RUSTSEC-2026-0192 via sctk-adwaita); no-defaults keeps x11rb/Wayland/adwaita out of the lock. macOS AppKit backend is not feature-gated, so the compiled code here is identical. Port shape (mechanical + one structural): winit 0.30's `run()` closure still exists but is `#[deprecated]` (= hard error under `-D warnings`, and `#[allow]` is house-forbidden), so the closure became `ApplicationHandler<UserEvent>` (`tray`/`quitting` as struct fields; `Init`/`ResumeTimeReached` in `new_events`, menu/daemon in `user_event`, `Exit` → `exit()`). ActivationPolicy moved builder-time (`with_activation_policy`, tao set it post-build) — same net effect. Verified: `cargo build -p divoom-menubar --locked`, 25/25 menubar tests, `clippy -p divoom-menubar --all-targets --locked -D warnings` clean, `cargo machete` clean, menubar fmt-clean, divoomd BLE-free still builds, binary smoke-proven (`--version` + 8s live run, exit 124 = alive). Known benign: lock now holds objc2 0.2.x (winit's pin) beside 0.3.x (tray-icon/muda/ours) — upstream-imposed, no type crosses the boundary. Files changed, all uncommitted: `divoom-menubar/Cargo.toml`, `divoom-menubar/src/main.rs`, `Cargo.lock`, `.cargo/audit.toml`. NOTE for next round: `.github/workflows/tests.yml` rust-core comment (lines ~213-218) still says menubar's "tao/tray-icon deps need GTK/glib" — stale as of this change, left untouched per scope; behavior (scoped `-p divoomd`) is still correct.

- **2026-09-21 — GTK edge trim (partial; full elimination BLOCKED on tao) — UNCOMMITTED, owner review pending.** Owner directive was to eliminate gtk/glib/proc-macro-error from Cargo.lock by removing the edge, not another ignore. Ground truth: (a) NEITHER dep is unused — divoom-menubar uses both load-bearingly (tao: main.rs event loop + ActivationPolicy; tray-icon: tray.rs/tile menu + icons); divoomd + nowplaying use neither. So "drop unused deps" was impossible. (b) `tray-icon = { version = "0.24", default-features = false }` in divoom-menubar/Cargo.toml drops upstream defaults ("gtk"→muda/gtk+libappindicator, "libxdo"→muda/libxdo), which forward only to Linux-target-gated deps (verified: zero `feature="gtk"` cfgs in tray-icon 0.24.2 src; muda's gtk use is under Linux-gated platform_impl/gtk) — macOS compiles to identical objc2/AppKit code. Lock result: libappindicator, libappindicator-sys, libxdo, libxdo-sys, and the DUPLICATE libloading 0.7.4 removed (405→400 crates); `cargo tree --target all -i gtk` now shows ONE parent (tao→divoom-menubar) instead of three. BLOCKER for the rest: tao 0.37.0 (latest release) depends on gtk ^0.18 NON-optional on Linux targets (manifest line 275-276, no feature gates it), so gtk/glib/proc-macro-error stay in the lock and ALL 11 audit ignores still fire (each crate verified still in Cargo.lock) — .cargo/audit.toml untouched per scope. Removing the last edge means dropping tao = rewriting the menubar main loop on raw objc2/CFRunLoop; stopped there per instruction, did not force. CORRECTION to the brief's premise: NO Linux CI job builds this graph — tests.yml scopes every Ubuntu job `-p divoomd` (rust-core clippy is `-p divoomd` with a comment saying why menubar is excluded; workspace-wide clippy runs on macOS rust-ble); the audit.toml comment was right. Verified: `cargo build -p divoom-menubar --locked` + 25 menubar tests pass, `cargo clippy -p divoom-menubar --all-targets --locked -D warnings` clean, `cargo machete` clean, `cargo build -p divoomd --no-default-features --locked` green (no rebuild — divoomd graph byte-identical), divoomd no-default suite green EXCEPT 2 fleet_routing tests that fail ONLY because this shell builds into the machine-shared target dir so encoder discovery (upward search for divoom_lib/) misses — proven environmental: green with `DIVOOMD_ENCODER_LIB=.../libdivoom_compact.dylib`; rebuilt dylib then restored via git checkout so the round touches only Cargo.toml+Cargo.lock. Unverifiable on this Mac: Linux compile of menubar was and remains nonexistent (no job builds it); Linux CI impact is nil by scoping, not by testing. MCP files untouched. CHANGELOG/ROADMAP not extended per instruction (handoff only, no commit).

- **2026-09-20 — stale-dependency sweep (Rust tray chain + Python floor) — UNCOMMITTED, owner review pending.** (a) Rust: NO bump. `cargo audit` is green (exit 0, 405 crates, 11 ignores all still firing-legit). Investigated dropping `glib 0.18.5` / `proc-macro-error 1.0.4` via the tray chain and it is not achievable from our side: `tao 0.37.0` is already the latest release and depends on `gtk ^0.18` non-optional on Linux targets (`cargo tree --target all -i gtk` shows three parents: libappindicator and muda via tray-icon 0.24.2, plus tao directly), so glib stays in Cargo.lock regardless of a tray-icon 0.24→0.25 bump (0.25.1 still defaults to muda-gtk3; muda 0.20 keeps gtk3). Churning the lock would remove zero advisories, so Cargo.toml/Cargo.lock are untouched. Only fix: corrected the stale "tray-icon 0.24.2 IS the latest release" premise in `.cargo/audit.toml` (comment-only; gate behavior unchanged). Verified `cargo build -p divoomd --no-default-features --locked` (BLE-free, terminal-safe) + `cargo audit` both green. The block deletes itself when the tao/tray-icon stack moves to GTK4. (b) Python: floor raised `requires-python >=3.10` → `>=3.14`, Pillow floored `pillow>=12`, dead `tomli; python_version < '3.11'` marker removed from both `pyproject.toml` and `requirements.txt` (nothing imports tomli; `tests/` already imports stdlib `tomllib`, so 3.10 was already broken for the suite), classifiers pruned to 3.14. Evidence for 3.14: CI `setup-python` is 3.14 in both jobs, local is 3.14.7, `.buildvenv` is 3.14, README/RELEASING say the shipped app builds on 3.14, no 3.10–3.13 interpreter exists on this machine, and no code needs <3.12 (no `except*`, no `type` statements). Pillow rationale: latest 12.3.0 vs local venv 10.4.0 (the float skew the getdata bridge commit worked around); `get_flattened_data()` exists only on 12+, `getdata` removed in 14. Files changed, all uncommitted per instruction: `pyproject.toml`, `requirements.txt`, `.cargo/audit.toml`. Tests: `test_mcp_server` + `test_pyproject` 49 passed. NOT done per the repo rule, left for the owner: no commit (instructed); CHANGELOG/ROADMAP untouched (CHANGELOG carries the MCP round's uncommitted stanza); `README.md:74` still says "**Python 3.10+**" -- one-line follow-up now that the floor is 3.14.

- **2026-09-20 — MCP protocol to SEP-2575 (`2026-07-28`) — UNCOMMITTED, owner review pending.** Both MCP servers negotiate now instead of pinning `2024-11-05`: requested version echoed when in (`2024-11-05`, `2025-03-26`, `2025-06-18`, `2025-11-25`, `2026-07-28`), else latest `2026-07-28`; `_meta` tolerated. Fleet reference zinc `engine_client.PROTOCOL_VERSION`. Live-vs-retired finding: BOTH implementations are live, neither retired — `divoomd/src/mcp.rs` (native; GUI spawns `divoomd mcp`) and `divoom_lib/mcp_server.py` (CLI `divoom-control mcp-server` via `cmd_mcp_server`; `mcp_tools` imports `Tool` from it); `examples/divoom_legacy/` holds no MCP copy. Also removed the `MCPServer(protocol_version=...)` ctor override (no in-repo callers). Files changed, all uncommitted per instruction (no commit this time): `divoomd/src/mcp.rs` (+negotiate fn + `#[cfg(test)]` unit test), `divoom_lib/mcp_server.py` (`SUPPORTED_PROTOCOL_VERSIONS`/`LATEST_PROTOCOL_VERSION` + `negotiate_protocol_version()`), `tests/test_mcp_server.py` (pin → `2026-07-28` + negotiation/`_meta` tests), `docs/MCP_SERVER.md` (version refs), `CHANGELOG.md` (Unreleased stanza). Tests: `test_mcp_server` + `handle_edges` + `cli_stdio` + `mcp_tools` 88 passed; `test_mcp_control` 22 passed + 1 skipped (e2e needs a built version-matching divoomd; none built). `tests/test_mcp_control.py` never pinned a version (asserts presence only) — only `test_mcp_server.py` did. ROADMAP untouched (no open MCP workstream; shipped history immutable). Before commit: `cargo build -p divoomd` + re-run `test_mcp_control.py` e2e so the Rust negotiation is proven on the wire, not just in `#[cfg(test)]`.

- **2026-09-14 — legacy-facade retirement DONE (v0.38.0).** The 77 modules
  the production import closure never reached (measured by AST over
  `divoom_gui`, `divoom_client`, `nowplaying`, the CLI/MCP modules; 27 of 104
  reached) now live in `examples/divoom_legacy/` as a standalone package:
  same subpackage layout, every import made absolute (`divoom_legacy.*` for
  itself, `divoom_lib.*` for the retained core it depends on), plus
  `DeviceSlot` (only `wall.py` used it). 114 test files that exercised them
  moved to `examples/tests/` with their support modules and the BLE mock
  (`examples/tests/support/mock_device.py`); `examples/tests/conftest.py`
  re-exports the main conftest. Both suites green: `tests/` 1597, and
  `examples/tests/` 1413 (`scripts/py_ci.sh` runs both; the coverage floor
  stays over `divoom_gui` + `divoom_client`). Gates re-targeted, not
  dropped: `check_positional_args` and `test_device_call_parity` read the
  legacy signatures at their new path; `check_examples` pins the scripts to
  `divoom_legacy.divoom`; `capability_census` treats both prefixes as "the
  library"; `check_gui_is_a_client` forbids `divoom_legacy` by prefix;
  `test_no_direct_facade_in_production` became "production never imports
  the retired package" over all four production trees. Decided and done:
  `pyproject` keeps `divoom_lib` (the core) and excludes `examples/`; the
  font blobs stay in `divoom_lib/fonts/` because `divoomd` embeds them.
  Also gone: the vendored house checks (`tools/check_no_allow.py`,
  `tools/check_file_size.py`, `scripts/house_emoji_gate.sh`) — the CI list
  and GitHub CI run `structural.sh --full` and `rust_gate.sh` from
  gates_of_heck by name.
  Open: the Python legacy suite is the only executable spec for the
  daemon's device_call arms; if `examples/` is ever deleted, port
  `test_device_call_parity` and the positional gate to read a recorded
  signature table first.

- **2026-09-13 — v0.37.0 RELEASED & INSTALLED LOCALLY** (tag v0.37.0 at
  cd553cd, GitHub release with the DMG, cask bumped; daemon inode
  546319145 running from /Applications/Divoom.app, signed by the local
  identity). Detail: the v0.37.0 CHANGELOG stanza; the ROADMAP "Shipped"
  entry. Verified on the installed build after install: daemon and
  menubar report 0.37.0; the active panel, `owned_devices` command,
  store faces (19) and their picture decode, Keychain-backed credentials
  (no password line in config.ini), and the CLI `select` all answer.
  Local gate 27/28 with one socket-test flake (5/5 green alone, ledger in
  ROADMAP); GitHub CI 5/5 green at the tagged commit.
- **2026-09-12 — v0.36.0 RELEASED & INSTALLED LOCALLY: one struct per panel, the
  six user-reported defects, prompt-free rebuilds.** Detail: the v0.36.0
  CHANGELOG stanza; design rule: ROADMAP "per-device aggregate". Signing:
  "Divoom Local Signing" (self-signed) signs every bundle via
  `scripts/codesign_identity.sh`; rebuild + `scripts/install_local.sh`
  prompt-free on this machine.

## Open threads / next up

1. **Browser suites run in CI** (own step, `--run-browser`): 3 runs green,
   1 with a single timeout in the gallery-overflow test that did not
   recur; that test now reports its layout on timeout. Watch for a repeat.
2. **`examples/` decision CLOSED 2026-09-15** — keep as the retired-library
   archive with daemon-client counterparts alongside: `examples/README.md`
   already states the retired status + the `divoom-control` CLI as the
   scriptable daemon-client path; production-import ban green
   (`test_no_direct_facade_in_production` 5 passed) and capability census
   0 DIRECT / 0 WRAPPED. No further retire — deleting it would orphan the
   only executable spec for the daemon's device_call arms.
3. **Menubar tile visual check**: the rows and the switch were read through
   System Events (NotchNook covers that part of the menu bar for a click
   tool); the tile ICON itself is proven up to the `Icon` handed to
   `NSMenu`, not by eye.
4. **Release hygiene**: a new machine needs `scripts/make_signing_identity.sh`
   once (one keychain prompt, user present) or every install prompts.

**Environment notes that recur** (not repo defects):

* **`sccache` can wedge a build**: 51 minutes at 0:00 CPU, `sccache
  --show-stats` showing accepted requests and nothing executed. Same build in
  4s with `RUSTC_WRAPPER=""`. Check CPU time before assuming a build is slow.
* **The shared `CARGO_TARGET_DIR` sits at the disk gate's ceiling** (~45-50GB
  of 50GB). Disk hygiene then aborts `structural.sh` before layer 3 with a
  message about the gate. `debug/incremental` and `llvm-cov-target` are the
  safe things to clear.
* **Bluetooth-grant terminal calibrator**: `cargo test` under the Claude
  desktop app's Bash has no Bluetooth grant, so any test that reaches a real
  CoreBluetooth central dies with SIGABRT and no message. That is a finding
  about the code (rule 10), not the terminal — fix the eager radio use.

## Hardware packet

    python3 scripts/hw_verify.py --self-test        # calibrate FIRST
    python3 scripts/hw_verify.py --out report.json

Start the GUI first: it owns the Bluetooth grant, and the packet refuses to
spawn its own daemon. `--self-test` exits **3 = PARTIAL** until a device is
connected. `tools/check_hw_verify_methods.py` gates the packet's method names
against the daemon's match arms. Play something before `album_art`.
`search_weather_city` is a canary (expected to fail on the real account).

## Earlier history

`CHANGELOG.md` is the durable record of what shipped, and `docs/ROADMAP.md` of
what is open. Round-by-round handoff prose is recoverable from
`git log -p -- docs/SESSION_HANDOFF.md` and, for R3–R64, from the archive file
deleted on 2026-08-30: `git log --diff-filter=D -- 'docs/archive/*'`.
`docs/CAPABILITY_MAP.md` holds the census verdicts from R70-R72.

## Hardware note

macOS Bluetooth TCC is granted per RESPONSIBLE PROCESS and keyed on the code's
designated requirement. A daemon started from a shell has no grant, so the
first BLE scan kills it with **SIGABRT and an empty stderr**. Users are
unaffected (the GUI launches the daemon and owns the grant); it bites terminal
work and tests.

**To drive a locally built daemon on hardware:** build and install the bundle
and let the app be the responsible process — `scripts/build_release.sh` then
`scripts/install_local.sh` (quits the app, installs, `open`s, proves the
running daemon's inode is the installed one). With the local signing identity
present (`scripts/make_signing_identity.sh`, once) there is no Bluetooth
prompt. For a traced daemon: `scripts/make_dev_daemon_app.sh` (BLE debug on,
log at `/tmp/divoom_dev_daemon.log`, lines tagged `[ble <id>]`); quit the GUI
first or it respawns its own daemon over the socket.

Then drive `/tmp/divoom.sock`. `connect {mac}` works directly; `scan` often
reports "already in progress" while the GUI scans. A device does not always come
back on its own after a daemon restart: `scan` times out while `connect` with
the saved identifier succeeds.

**Reading a trace:** a device ECHOES `basic frame cmd=0xNN` for opcodes its
firmware implements. A silence proves nothing on its own — send a known-good
command (0x45) first in the SAME window and compare.

Watch out: `cargo test` rebuilds `target/debug/divoomd` WITH default features,
so a BLE-free build does not stay BLE-free across a test run.
