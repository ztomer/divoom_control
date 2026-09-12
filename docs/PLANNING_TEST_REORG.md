# Plan — test rearrangement + obsolete Python retirement

Filed 2026-09-12 from the roadmap item "OPEN — code rearrangement".
Census first, moves second, deletions last. Per house rule this file is
pruned to git history once the work ships; the roadmap item stays.

## Census (measured 2026-09-12, v0.35.4 tree)

### Python: 3 stray test files, 7 suite squatters

`pytest.ini` already sets `testpaths = tests`. Tracked files outside it:

| File | What it is | Disposition |
|---|---|---|
| `divoomd/test_show_image.py` | Manual socket smoke test, live hardware, MAC on argv | Move to `tests/`, hardware-gated + skip-by-default. (The `test_show_image*` hits in `tests/test_display_channels.py`, `test_e2e_mock_device.py`, `test_mcp_tools.py` are test *function* names, not references to this file — verified 2026-09-12. Only CHANGELOG mentions it.) |
| `scripts/test_watchface_roundtrip.py` | Watchface driver on the **old direct-device path** (`Divoom()` + `dev.connect()` + `dev.display.show_clock`, `scripts/test_watchface_roundtrip.py:108-129`) — TCC-unsafe from a shell and bypasses daemon single-ownership | **Move + hardware-gate, no socket port** (revised 2026-09-12 during implementation: the "lean port" was wrong). `hw_verify.py` has NO watchface check, so this is the only roundtrip coverage — and `tests/test_e2e_mock_device.py:242` pins the facade seam (`monkeypatched Divoom.__init__` + `MockBleakClient`). A socket port would force a rewrite of that passing mock test for zero new coverage, and direct-BLE-under-`--run-hardware` is an accepted repo pattern (`conftest.py HARDWARE_TEST_MODULES`). Moved to `tests/test_watchface_roundtrip.py`, gated, importer updated. The daemon-socket port belongs to Phase 3 old-path-scripts work. |
| `scripts/hw_test_modes.py` | Deterministic hardware walker over the daemon socket | Not a pytest test — rename off the `test_` prefix. Only CHANGELOG mentions it. |

Correctly placed, do not touch: `scripts/hw_verify.py`,
`scripts/verify_gallery_render.py` (daemon-backed verifiers, already
gated by `tools/check_scripts.py`). `tests/e2e_gui_bridge.py` is NOT a
squatter either — it is the live subprocess bridge driven by
`tests/test_e2e_gui_daemon_connect_disconnect.py:61` and referenced by
`tests/support/gui_daemon_stack.py`; it stays.

Inside `tests/` (275 files), the uncollected files break down as follows
(all verified by reference-grep 2026-09-12; none match `test_*.py` collection):

- **Dead manual-runner trio — delete:** `test_runner.py` (collects 0 tests
  under pytest — no `test_` functions, only a `__main__` block — and its
  script list names `examples/discover_devices.py`, which does not exist),
  `api_test.py`, `minimal_api.py` (old direct-device path; referenced only
  by `test_runner.py` itself). Confirm no other references at deletion time.
  — DONE 2026-09-12. Reference re-grep showed the trio is self-referential
  only (the one outside hit was `run_integration_tests.py`'s own logger
  name, not an import). Note: `api_test.py` DOES match the placement
  gate (`*_test.py` suffix) — gate count went 254 → 252 with `test_runner`.
- **Ad-hoc benchmarks — move to `scripts/`:** `perf_downsample.py`,
  `perf_image_encode.py`. Both self-describe as "intended for ad-hoc runs,
  not the regular CI suite". No references anywhere. — DONE 2026-09-12
  with one correction to the census: both files DO define `test_perf_*`
  functions (11 total), but they are never collected in suite runs
  (filenames match neither `test_*.py` nor `*_test.py`; verified 0 hits
  in full-suite collection). Moving preserves exact behavior: explicit
  `pytest scripts/perf_*.py` still collects and all 11 pass from the new
  location, `__main__` ad-hoc use unchanged. Open question recorded, not
  decided: whether CI should run perf regressions at all (timing-flaky
  by nature) — belongs to Phase 3 or a later round, not this move.
- **Superseded runners — delete:** `run_integration_tests.py` (old
  `Divoom()` + `discovery` path, own `test_case` registry predating
  pytest), `automated_visual_tester.py` (PyWebView screenshot runner
  superseded by `scripts/gui_pov.py`). No references to either.
  — DONE 2026-09-12.
- **Keep:** `tests/support/`, `tests/fixtures/`, and
  `tests/e2e_gui_bridge.py` (live helper, see above).

Phase 2 verification (2026-09-12): `pytest --collect-only` 3182 before
and after (deletion delta exactly 0, as predicted); full suite 2946
passed / 236 skipped, identical to Phase 1; `check_test_placement`
(252 files), `check_scripts` (37 scripts), `check_file_size` green.
Procedural note: a `git stash` + `pop` around staged renames came back
with the index split (renames as A+D, deletions unstaged) — repaired
with `git add -A` and re-verified. Avoid stashing mid-round with staged
moves; if you must, check `git status` shape after the pop.

### Python: "obsolete" is usage-patterns, not modules

Every `divoom_lib` module has ≥1 importer and `capability_census.py`
reports 0 DIRECT / 0 WRAPPED. Python is canonical for wire formats
(R67 proved the Rust port against it). Wholesale deletion would destroy
the reference the parity gates check against. The real obsolete surface:

- `examples/` — 7 files, all on the pre-daemon direct-device path
  (`Divoom()` + `utils.discovery`). Presumed broken; verify each.
- Old-path scripts: `validate_devices.py`, `diagnose_ble.py`
  (+ `test_watchface_roundtrip.py` above).
- `divoom_lib/cli.py` subcommands (`scan`, `push-image`, `daemon`,
  …) — per-subcommand keep/kill, not a blanket delete.
- `scratch/` — untracked clutter (`test_overlay*.py`, `benchmark.py`,
  dozens of PNG/GIF artifacts). Cleanup is `rm`, not a commit.

### Rust: 1 defect class + naming debt

Four shapes, three of them fine:

- **A. Inline `#[cfg(test)] mod tests` in ~28 subject files** —
  idiomatic, keep.
- **B. `#[path]`-wired siblings** (`socket_bind_tests`,
  `subscriptions_tests`, `art_hot_tests`, `wire_tests`) — gated via the
  parent's `#[cfg(test)]`, split out for the 500-line cap. Keep.
- **C. `divoomd/tests/` integration suite** (12 files,
  `*_behavior.rs` + parity + `multi_device_routing.rs`) — idiomatic
  location, keep.
- **D. Menubar + nowplaying** (`daemon/tests.rs` under
  `#[cfg(all(test, unix))]`, `media_remote_tests.rs` under
  `#[cfg(test)]`) — correctly gated, keep.

**Defect — 4 ungated `pub mod` test files** (`divoomd/src/lib.rs:50-53`):

```rust
pub mod mock_device_tests;   // no #[cfg(test)] — every sibling has one
pub mod mock_device_tests2;
pub mod mock_scroll_tests;
pub mod mock_scrolling_text_tests;
```

Each file's only content is a `#[cfg(test)]` module, so release builds
carry four empty public modules, and `pub` advertises an API
(`divoomd::mock_device_tests::tests::…`) that exists under
`cargo test` and vanishes in release — an integration-test author
reaching for `setup_mock_daemon` gets a confusing resolution error.
`divoomd/tests/*.rs` reference none of them, so the `pub` is not
load-bearing. (`mock_transport` is different: `connect {"mock": true}`
uses it on the runtime path — it stays `pub`. Verified in
`daemon_connect.rs` + `transport.rs`.)

**Naming debt** — `mock_device_tests` vs `mock_device_tests2` is a
numbered split (reason documented in-file: 500-line cap). Acceptable,
but topical names (`…_channels`, `…_display`) would survive the next
split. Optional; do it while touching the files anyway.

## Phases

### Phase 0 — Decision record (no moves)

Write the classification so later phases aren't judgment calls: pytest
test (auto-collectable, daemon-or-mock, hardware-gated via
`conftest.py`) vs hardware driver script vs verifier script. Kill
criterion per class. Output: this file (done) + the gate in Phase 1.

### Phase 1 — Stray files + the Rust gating fix (mechanical, one commit)

Status 2026-09-12: SHIPPED. Items 1–4 implemented, gate (item 5) written,
calibrated both directions, wired into `.gatesrc` + CI, full verification
green (pytest 2946 passed / 236 skipped, cargo both matrices, clippy both
cfgs, fmt, ci_local 26/26).
Bonus find during implementation: `divoomd/smoke_display_aliases.py` —
same class as `test_show_image.py` (manual HW smoke over the daemon
socket, zero references, usage string even names a stale
`test_display_aliases.py`) — moved with it as
`tests/test_smoke_display_aliases_hw.py` (module-level flow refactored
into `run_smoke()` so collection is side-effect free).

1. `divoomd/test_show_image.py` → `tests/test_show_image_hw.py` — DONE.
   Flow wrapped in `test_show_image_quadrants()` (asserts daemon
   `success`), `main(mac=…)` kept for manual CLI use, MAC via
   `DIVOOM_TEST_MAC` under pytest. Collects 1 test, skips by default.
2. `scripts/test_watchface_roundtrip.py` → `tests/test_watchface_roundtrip.py`
   — DONE (move + gate, no port — see revised disposition above).
   Collects 0 tests (driver module); the facade seam proven by
   `test_e2e_mock_device.py` (15/15 pass with the updated import).
3. `scripts/hw_test_modes.py` → `scripts/hw_walk_modes.py` — DONE
   (docstring usage lines updated; only CHANGELOG prose mentions the old
   name and prose history is not rewritten).
4. `divoomd/src/lib.rs:50-53` → gate each declaration with `#[cfg(test)]`
   (copy the `#[cfg(test)] mod c7_positional_tests;` pattern from line
   18-19 — gate the *declaration*, not just `pub`→`mod`, so release
   builds see nothing and there is no `dead_code` trip under
   `-D warnings`). `mock_device_tests2`'s
   `super::super::mock_device_tests::tests::setup_mock_daemon` path stays
   valid: both sides are `cfg(test)`.
5. New gate in the style of `check_scripts.py`: fail on any
   `test_*.py` outside `tests/` and any ungated `*_tests` module in
   `divoomd/src`. Wire it into `.gatesrc` `GOH_CI_STEPS` (which is what
   `ci_local.sh` and CI consume) and mirror in
   `.github/workflows/tests.yml` per the repo's mirror rule.
   Calibrate both directions (restore one stray, remove one `cfg`, watch
   both go red). — DONE as `tools/check_test_placement.py` (step 5/26 in
   local CI, mirrored in `tests.yml` after `check_scripts.py`). Both
   directions proven red with zero tree residue; green on the shipped
   tree (254 test files, 114 .rs files). Floor: `scope_is_empty` +
   `MIN_RS_FILES = 50` against the extractor going blind.

Verify: full pytest suite, `cargo test` both feature matrices
(default + `--no-default-features`, the no-BLE lint step from
`.gatesrc`), `cargo clippy --all-targets` on both cfgs (the gating
change must not introduce `dead_code` under `-D warnings`),
`ci_local.sh --fast`.

### Phase 2 — `tests/` squatters (one commit)

Status 2026-09-12: SHIPPED. Trio + 2 superseded runners deleted,
`perf_*` moved to `scripts/` (11/11 pass explicitly from the new
location). Suite collection 3182 before and after; full suite 2946
passed / 236 skipped, identical to Phase 1.

Per the census above: delete the trio (`test_runner.py`, `api_test.py`,
`minimal_api.py`) and the two superseded runners
(`run_integration_tests.py`, `automated_visual_tester.py`); move
`perf_*` to `scripts/` (covered there by `check_scripts.py`'s
parse/lint scope). Re-grep references at deletion time — the census is
2026-09-12 and the tree moves.
Verify: `pytest --collect-only` count unchanged (`test_runner.py`
collected 0 tests, so the deletion delta must be exactly 0).

### Phase 3 — Obsolete-Python retirement (per-item, slow)

Arbiters stay green throughout: `capability_census.py`,
`check_gui_is_a_client.py`, both parity gates. They define what
"obsolete" may not touch.

1. `examples/` × 7 — run each against the daemon model; port to
   daemon-socket examples or delete with a changelog note.
2. Old-path scripts — port to daemon client or retire.
3. `divoom_lib/cli.py` subcommand audit — keep / kill / mark
   reference-only per subcommand.
4. `scratch/` — confirm unreferenced, `rm` (untracked, no commit).
5. Optional: topical rename of the `mock_device_tests*` split.

Rule: additive-before-subtractive — the replacement is proven working
before the old file goes.

### Phase 4 — Ship

Full `pytest`, `ci_local.sh`, house gates. Handoff + changelog +
roadmap updates; prune this file to git history.

## Explicit non-goals

- No `divoom_lib` module deletion beyond Phase 3's per-item findings —
  the census and parity gates own that definition.
- No Rust test relocation — `tests/` + inline + `#[path]` siblings are
  all idiomatic; the fix is 4 gate attributes, not a move.
- No `mock_transport` visibility change — runtime code, not test code.
