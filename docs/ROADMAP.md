# Roadmap — divoom-control

The ONE forward-looking document (`AGENTS.md`). It holds what is not done yet,
in the order it should be done, and the standing rules new work must respect.
What shipped is in `CHANGELOG.md`; round plans and pruned sections are in git
history (`git log -p -- docs/ROADMAP.md`).

**How to read the Plan.** Phases run in order; an item may depend only on items
in its own or an earlier phase. Each item says why it matters, what "done"
means in terms someone can check, and where the evidence is. Statuses:

| Status | Meaning |
|---|---|
| `OPEN` | Ready to work. |
| `BLOCKED (on X)` | Cannot move until X changes; X is named. |
| `DECISION (owner)` | Needs the owner's call before any code. |
| `WATCH` | Nothing to do until an outside event; the trigger is named. |

`tests/test_roadmap_shape.py` enforces that shape: every item has a status and a
**Done when**, no dependency points at a later phase, and every repo path cited
anywhere in this file exists. Shipped items are deleted from the Plan, not
marked SHIPPED -- that marker is refused.

Premises were last checked against the code on **2026-10-14** (HEAD `a38e2df`,
the goh 0.27.0 hook reinstall on top of the 2026-10-12 plan commit `a8a848d`).
Fourteen items have landed since (P1.1 `15ff359` on 2026-10-15; P1.6, the
build/install platform gate, and P1.7, the RX frame parser's one-byte resync, on
2026-10-16; P1.12, the framing-vector generator, P1.5, the two-suite
collection fix, P1.2, the PyInstaller pin from a committed file, P1.4, the
coverage floor ratcheted to the measurement, P1.3, the stale `tao` comments
in CI, P1.8, the 52 hand-rolled status markers, P1.11, the short-frame panic
fixed on both sides, P1.10, CI reading Python from `.python-version`, and
P1.9, the release bumping the cask through the tap's gate, also on
2026-10-17; P7.1, the tray glyph's shapes, on 2026-10-18; P1.13, the browser
suites run in the local gate, on 2026-10-19, in `1760a79`, `7080f72`, `414ab5e`
and `0627eb5`; P7.2, the connection dot's shape-and-fill vocabulary, on
2026-10-20, ruled by the owner and landed), so the items below have
NOT been re-derived against a later HEAD -- check an item against the code before
working it. Phase 0 is new (goh 0.27.0's fallout,
measured); the old Phase 0 became Phase 1 and every later phase moved up by one
(P9 unchanged), and the old P0.8 (camoufox) is now P0.2. Each phase states its
goal, exit criterion and rough size in sessions (S = under one, M = one or two,
L = three or more).

**One exception to "not re-derived": the 2026-10-20 hardware round.** P2.7,
P5.3, P6.1, P6.2, P9.3 and P9.7 were re-derived against the installed v0.41.3
bundle and the code at `0d4fb76`, with four panels on the bench; each entry
below carries its verdict and what is left. P2.7 landed and is deleted from
the Plan.
---

## Plan

### Phase 0 — wire in goh 0.27.0

**Goal:** `tools/gate.sh --full` green at HEAD and pushed (`a8a848d` and the
hook reinstall `a38e2df` are waiting on it). **Exit:** the pre-push gate
accepts `git push`; each item's named step is green and was seen red.
**Size:** M (one session; P0.1 is the bulk). Measured 2026-10-14 on
`a38e2df`: structural stops at its first red (stdin), so the rest was read
with `GOH_SUBPROCESS_STDIN=off` written into a scratch `.gatesrc` (not
committed): 22 of 25 steps green in 7 min 59 s at load ~140, three red.

#### Phase 0 ships in `a8a848d..229c96d`; what is left

All six items landed and the full gate is green. They are deleted rather than
annotated, per this file's header:

- **P0.1** — `56a6a2b` — every call names its stdin, declared not seeded
- **P0.2** — `439fdcd` — the check names the shared cache as the cause and the tests fake the active build
- **P0.3** — `c0bce0a` + `4c4828e` — the gate judges its own tree, and the accept test drives a fixture
- **P0.4** — `20b3df2` + `6aa6f5c` — the reader frames by line; a two-events-in-one-chunk case is watched red
- **P0.5** — `229c96d` — all floors set, the `[subject]` line is gone
- **P0.6** — `f70919b` — rustls 0.23.46, no ignore entry

Two things the phase found that are NOT its items, tracked where they belong:

- `tests/test_empty_scope_guard.py`'s ratchet asserted `legitimate` must be
  empty, which is not what that section means (see the entry's own header);
  rewritten, with both directions proven red.
- The py_ci coverage floor now binds on every run (`23b512f`) — it was
  reporting "NOT enforced" because the two camoufox probes disagreed.

Landed after (2026-10-21): the stdin sweep's row for this repo was closed on
2026-10-14 (`56a6a2b`, P0.1), and the tree has moved since, so the floor was
re-measured with the house's own tool and set WITH the tree: 73 process calls
across 53 files, every one of them declaring its stdin, and no allowlist file
at all — nothing is seeded, so there is no 'unreviewed' debt to work off. The
step is NAMED in `.gatesrc` now (`GOH_SUBPROCESS_STDIN=on`): it has run by
default since goh 0.27.0, and a gate a repo inherits from a default is a gate
nobody turned on. Both directions were watched red first — with every
declaration stripped the check names all 73 calls, and with the floor raised
above what the scan reads it names the floor key.

### Phase 1 — correctness defects and drift (small, independent)

**Goal:** no known defect or gate hole stays open while feature work starts.
**Exit:** every P1 item's *Done when* is a test or gate that was watched red
first. **Size:** M (all items landed). Depends on Phase 0
(nothing pushes until it lands).

**Phase 1 complete** (2026-10-17): all eleven P1 items landed (P1.1, P1.2, P1.3,
P1.4, P1.5, P1.6, P1.7, P1.8, P1.9, P1.10, P1.11).

Landed after (2026-10-18): a probe crate's cargo build removed with its temp
dir -- the tray-icon verifier left a build under `~/.cargo/build` per run
because the house `build-dir` hashes a fresh path every time; every Python
cargo build spawn in `tools/` and `scripts/` now takes its environment from
`probe_env`, and a class check fails any that does not (`45cc5e5`;
`tools/_cargo_env.py`, `tests/test_cargo_probe_env.py`).
Landed after (2026-10-18): main CI's browser step, red on run 39171574815 on two
different tests, was one app defect -- a Spatial Bench re-render (every scan
result, activity event and owned-device broadcast, including the startup scan a
second after load) re-applied selection side effects: it moved the channel tab
the user had opened, rebuilt the node under an open drag, and repainted a level
slider under the pointer. A refresh now syncs only on a change of panel, never
moves a tab the user opened, waits for a drop, and leaves a held slider alone
(`divoom_gui/web_ui/spatial_stage.js`, `divoom_gui/web_ui/spatial_drag.js`,
`divoom_gui/web_ui/panel_facts.js`; `tests/test_e2e_rerender_keeps_user_state.py`,
which fires the refresh inside each gesture, 4 red before). Running the suites
eight-wide to reproduce CI's contention found two test-side instances of the
same "the page moved on while the test looked" shape, both fixed: a gallery
fixture tile the app drops as broken (180 ms fade) and three backend mocks
that released on a 120-3000 ms timer instead of when the test said so, and
a GIF-frame probe that read a 400 ms loop through a real 260 ms timer (now a
pinned clock, `tests/test_preview_gif_animation.py`).
Landed after (2026-10-19): P1.13, the browser suites run in the local gate.
The camoufox build is declared once, in `.camoufox-build`
(`official/prerelease/156.0.1-beta.39`, the newest release and the dev
machine's build; owner ruling: CI uses the local machine's version). CI fetches
that spec, and CI and `GOH_CI_STEPS` both run `scripts/browser_e2e.sh`, which
refuses any other active build with the install command; the parity exemption
is gone (`tests/test_camoufox_install_check.py` fails a build literal outside
the pin). The suites are hermetic too: the test browser's
off-machine traffic goes to a closed port, because waiting on Google Fonts made
`Page.goto` time out under load (`tests/support/browser_options.py`, `414ab5e`).
Landed after (2026-10-19): the browser suites running eight-wide in the local
gate found two app defects, both the same class -- the app's own startup
overwrote state it already had. `setConnectionState` wrote two views of one
fact (the panel's own link flags and the app-wide `appConnected`) and
disagreed on what a PENDING connect means: the banner keeps the last known
device until the connect resolves, the link flag did not, and for the Virtual
Wall -- which has no `discoveredDevices` record of its own -- that flag is what
`requireDevice()` gates every wall write on, so those writes were refused with
"Connect a device first" and dropped. Separately, the app's startup restore
installed the PERSISTED snapshot over the live state (an empty snapshot
erasing it too, since `{}` is truthy in JavaScript): the wall stopped being a
known target and writes aimed at it went to a single panel instead, and the
daemon's own live devices were dropped from `discoveredDevices`, so
`panelIsLinked` said "not linked" for a panel that was linked
(`divoom_gui/web_ui/connection_events.js`, `divoom_gui/web_ui/app_init.js`;
`tests/test_e2e_write_during_pending_connect.py`,
`tests/test_e2e_startup_restore_keeps_live_state.py`, both red before;
`0627eb5`).

Landed after (2026-10-21): P1.14, the web UI's JavaScript has a syntax gate.
The rule is the browser's: one classic script per file, parsed independently
(the browser makes one Script Record per `<script src>`), and the payload of a
template literal is NOT code -- the browser parses only the `${...}` holes.
The node reader uses `vm.Script`, which IS the Script goal a `<script src>`
uses; `node --check` runs too, but its goal flips to CommonJS (or, on node
22+, to module), so it ACCEPTS a file the browser refuses (a top-level
`return`, an `import`, a top-level `await`) -- a difference that is not
academic, because such a file never loads and the app loses a whole tab
without a word. The pure-Python reader (`tools/_js_lex.py`) is the fallback
where node is absent, it runs on EVERY run so it is never dormant, and its
scope is stated: it is a LEXER (unterminated literals, unbalanced brackets,
unclosed `${}` holes) and it cannot see `const x = ;`. The gate is
`tools/check_js_syntax.py`, named in `.gatesrc` and in CI's checks job; it
covers every `.js` file under `divoom_gui/web_ui/`, not only the ones
`index.html` names (two of them are loaded by the test suite instead). Both
directions watched RED first, on a copy of the real tree with the historical
defect planted: a stray backtick inside a template literal in
`templates_settings.js` (`tests/test_js_syntax_gate.py`).
Landed after (2026-10-21): P1.16, the gallery's internal-scroll test stopped
racing the gallery's own render. The app schedules its gallery load 50ms
after the Gallery sub-tab is clicked (`settings_features.js`), and that load
replaces the container's contents wholesale; the test injected its tiles
straight after the click, so it measured a container the app was about to
empty, and CI run 39542787961 read "gallery never overflowed: scrollHeight
316, clientHeight 316" -- an EMPTY container's numbers, which name the symptom
and not the cause. Reproduced here on the CI runner's own viewport (the
container is 316px tall in both) by loading the machine: the app's write has
to land between the injection and the first poll, and that window is one
browser round trip. The test now watches the container with a
MutationObserver and waits for TWO things: the app's OWN write (the one
that says "this container is mine now") and then stillness. Stillness alone is
not enough, and the first CI run of that fix proved it -- the gallery's load
is scheduled with `setTimeout(window.loadGallery, 50)`, and a timer fires
when the MAIN THREAD is free, which on a loaded runner was 450ms later: the
container had never been written, it read as quiet, the test injected, and
the app's load landed 20ms later and emptied the container underneath it. The
test also asserts that the tiles SURVIVED the measurement, that the grid
overflows, and that neither the card nor the page scrolls (the two halves of
what the test's name claims, and the second of which it had never checked).

Landed after (2026-10-21): P1.15, the daemon's startup lock is released
EXPLICITLY, and the reason it outlived the process is named. A `flock` belongs
to the OPEN FILE DESCRIPTION, not to the descriptor: a descriptor is one
reference to a description, and the lock lives until the LAST reference goes
away. A child process that inherits the descriptor holds another reference to
the SAME description, so the parent's `close()` does not release the lock --
the lock outlives the process that took it, and the next daemon is told
"another divoomd is starting up" by a daemon that is not running. The daemon
starts children (`spp.rs` starts a Python helper), the window is the
fork-to-exec gap -- short, not zero, and longer on a loaded machine -- and
that is CI run 39523759110. Reproduced 4 times in 320 runs of the 435-test
lib binary (twice as `StartupInProgress` on the lock, twice as
`UnresponsiveListener` on the socket), and then DETERMINISTICALLY:
`a_released_lock_is_released_even_when_a_child_inherited_the_descriptor` gives
a child a copy of the lock's descriptor and watches the second `acquire` fail
with CI's own message. `StartupLock` now unlocks (`flock(LOCK_UN)`) when it is
dropped, so the release means "I am giving the lock up" and not "the last
descriptor is gone"; the same test is that fix's green. The same window seen
through the SOCKET rather than the lock is the `clears_a_stale_socket` variant
(`UnresponsiveListener`: a child that inherited the listener's descriptor keeps
the socket listening, and the probe finds a listener that never answers). Its
production exposure is bounded -- the daemon unlinks the socket path before it
exits, so the path is gone -- and it is left as a named variant, not as a fix.

### Phase 2 — daemon liveness and safety

**Goal:** the daemon can say who holds it, never hangs on one peer, and
notices its own wedge. **Exit:** P2.1-P2.6 each pinned by a test that stalls,
floods or wedges the real socket server; P2.7 has a trace or is gone (the
trace was taken 2026-10-18; P2.7 and P2.8 are now fixes with named causes).
**Size:** L (P2.5 and P2.6 are each M). **Risk:** P2.3's deadlines must not
cut a legitimately slow `sync_artwork`; per-command budgets, not one global.
P2.7 needs a panel and the GUI's Bluetooth grant (Hardware reference below).

Landed (2026-10-17): P2.1, the socket made owner-only by the daemon rather
than the umask;
P2.2, `get_status` reporting every connection by kind with ages, peer pid and in-flight command;
P2.3, every command under a per-command deadline (`divoomd/src/deadlines.rs`);
P2.4, a named subscriber (`client_id`) replacing its own slot before staleness eviction;
P2.5, a lagging subscriber caught up to the latest value per key (`divoomd/src/events.rs`);
P2.6, an in-process watchdog that exits a wedged daemon within 30 s (`divoomd/src/watchdog.rs`).

Landed (2026-10-19): P2.8, a lost link retires itself and is reported (event +
`device_status`), and every read that gets no answer fails with a code instead
of `success: true, result: null` -- the class, not the one read the report
named: 28 reads across the daemon's `device_call` layer, the MCP read tool,
and the live widget's push (`divoomd/src/device_call/read.rs`,
`divoomd/src/daemon/link.rs`, `divoomd/src/transport.rs`).

Landed (2026-10-20): P2.7, the panel relinking after a daemon restart is
CONFIRMED on hardware (the GUI respawns the daemon and the panel re-links with
no click; two SIGTERMs, `==== daemon spawn from pid 35435 ====` then
`[ble][connect]` and `device_status` showing the panel linked).

Landed (2026-10-20): P2.7's REMAINDER — the panels a CLI or an MCP client
linked, and the wall's slots, which the GUI's relink never covered. The
daemon now writes down what it holds (`~/.config/divoom-control/links.json`:
the id and the connect request that made each link, and the wall's slots) and
replays it on startup, one panel at a time. The GUI's own relink stays — it
is the client's path, and the two agree because the daemon skips a panel it
already holds. The restore reaches for the radio, so it is the spawn that
carries the Bluetooth grant (the app's client) that asks for it
(`divoomd/src/links.rs`, `divoomd/tests/link_restore.rs`,
`tests/test_daemon_link_restore_e2e.py`).

### Phase 3 — the daemon knows what each panel is

**Goal:** one owner (the daemon) for each panel's model, size and failure
codes. **Exit:** `device_status` carries model/size and errors carry codes,
with tests per model class. **Size:** M. **Release check (needs a panel):**
P3.3 changed what the weather widget looks like on every panel; it needs the
R12-style visual pass on hardware before release.

Landed (2026-10-17): P3.1, `device_status` carrying each panel's model and resolution from the APK's own tables (`divoomd/src/panel_model.rs`);
P3.2, a stable `code` on every device failure, branched on by the Settings card (`divoomd/src/error_code.rs`);
P3.3, weather drawn by us as a `render_widget` frame and pushed like every other widget, the firmware's clock face no longer selected (`divoomd/src/live_jobs/weather_frame.rs`).

#### P3.4 — the panel's description is the daemon's, and the clients read it
**Status:** OPEN
**Why:** the daemon knew each panel's model and size, and three clients kept
their OWN answers to "what kind of panel is this": the web UI decided the
chassis family from the model with its own regexes and a table of its own, the
web UI decided the FM-radio and VJ abilities from the DEVICE NAME, and the CLI
kept a per-model capability table whose FM rows were wrong for fifteen models.
The name-based one reached the screen: the FM card was offered to every panel
whose name contained "tivoo" or "ditoo", and the vendor app offers the radio to
the Timebox and the Tiivoo 2 and to no other panel -- the opposite.
**Done when:** the daemon's `device_status` carries the chassis, the app's
per-model switches (including the radio and the microphone) and the app's home
list for the model; the web UI carries no per-model derivation of its own; the
CLI has no capability table, and the daemon refuses to tune a panel it knows
has no radio.

#### P3.5 — the MCP says what the daemon says
**Status:** OPEN
**Why:** `get_capabilities` returned the daemon's description, but its own
description of the description was wrong ("There is no FM-radio flag: the
vendor app does not decide FM per model"), and it did not carry the chassis
or the screens.
**Done when:** the tool's text matches the daemon's table, and the whole
description is what it returns.

### Phase 4 — MCP as a display surface

**Goal:** an external agent can discover each panel, draw on it at its real
resolution, and share it with background jobs without collisions. The
catalog had 14 tools when this phase opened; it has 25.
**Exit:** an MCP client draws a full-resolution multi-frame image on a 64x64
panel while a live job runs, and the panel returns to the job when the lease
expires (e2e over the real `divoomd mcp` entry point). **Size:** L.

Landed (2026-10-17): P4.1, `get_capabilities` describing the named panel with model, size and the vendor app's per-model features (`divoomd/src/panel_features.rs`, derived by `tools/derive_panel_features.py`);
P4.2, `list_screens` listing every known or placed screen with its size, live link and place (`screens` in `get_topology`);
P4.3, `show_image` drawing at the panel's size under a `resize` policy, every decoded frame held to the 256-colour palette (`divoomd/src/image_fit.rs`);
P4.4, `push_animation` playing every frame with its own duration through one multi-frame `show_image` call;
P4.5, text, live jobs, scoreboard, timer and countdown as MCP tools in the one catalog, every integer range stated once (`divoomd/src/arg_bounds.rs`);
P4.6, screen leases: `lease_acquire`/`lease_renew`/`lease_release` with a mandatory bounded TTL, the live widget paused under a lease and repainted from its newest frame when the lease ends or lapses, `show_image` pushes conflated latest-wins (`divoomd/src/lease.rs`; the Phase 4 exit is `divoomd/tests/mcp_lease_e2e.rs`);
P4.7, `notify`: text shown under a screen lease whose TTL is the notification's bounded duration (`arg_bounds::NOTIFY_DURATION_MS`), so the panel comes back when the lease lapses with nothing waiting (`divoomd/tests/notify_tool.rs`).

### Phase 5 — the GUI models each panel, not "the" panel

**Goal:** every per-panel fact the GUI shows is read from and written to the
daemon by mac. **Exit:** browser tests across two panels for P5.1/P5.2; the
menubar no longer closes on a status change. **Size:** M.

Landed (2026-10-18): P5.10, every failure reply carrying an `ErrorCode` -- the code-less `err_reply` deleted, `error_code.rs` the only place a reply's `success` is written, the wire checking every reply, five codes added (`device_failed`, `busy`, `unauthorized`, `upstream_failed`, `internal`) and the code table in `docs/MCP_SERVER.md` held to the enum (`3459280`; `divoomd/src/reply_code_sweep_tests.rs`, `divoomd/src/reply_shape_scan_tests.rs`, `divoomd/src/ancs.rs`);
P5.9, a job, activity record or screen lease refused on a panel a racing `disconnect` forgot (its slots closed for whoever still holds it, pinned by a forced interleaving) and `Fleet::adopt` attaching under one lock hold, the web UI sending `set_device_activity` only for a panel the daemon reported, and every missing required argument refused `bad_request` from one command table the dispatcher checks first (`58898ed`; `divoomd/src/device/slot.rs`, `divoomd/src/command_args.rs`, `tests/test_e2e_activity_only_for_reported_panels.py`);
P5.8, a live job or activity record naming a panel no link ever made a fleet entry refused with `unknown_device` naming the mac, the fleet's only constructor private behind `Fleet::adopt` and the client path a `Fleet::known` lookup, a linked-then-dropped panel keeping a new job waiting, `MatrixWall` refused as the wall surface rather than a panel, and MCP/CLI tool errors carrying the daemon's `code` (`0f73dda`; `divoomd/src/device/fleet.rs`, `divoomd/src/error_code.rs`, `divoomd/tests/unknown_panel.rs`);
P5.7, every other bridge call that acts on a panel -- the Tools tab, the alarms editor, the live widgets, the stock tile, the gallery, hot-channel and custom-art pushes, `device_call` -- naming it first through `ApiBase._display(mac)` (the wall refused for one-panel actions and named, never defaulted, for the rest), `current_divoom` deleted, and one test enumerating every public bridge method so a new one without a mac fails (`691e0b5`; `tests/test_device_actions_name_their_panel.py`, `tests/test_e2e_device_action_reaches_its_panel.py`, `divoomd/src/mock_tools_tests.rs`);
P5.6, every channel bridge call naming the panel its click resolved, through one `ApiBase._display(mac)` to the daemon, a call naming no panel refused, `_target()` and `current_target_mode` deleted, and `_LanView` forwarding the daemon's `lan.*` calls so albums, playlists and the overlay work through the real proxy (`0a8aa81`; `divoom_gui/api/__init__.py`, `tests/test_e2e_channel_write_reaches_its_panel.py`, `tests/test_channel_writes_name_their_panel.py`, `divoomd/src/mock_channel_tests.rs`);
P5.5, with no panel known the bench showing an empty state that says how to add one and the deck "No panel selected" with no levels, the active-panel lookup answering null instead of an invented mac (`f56b550`; `window.isKnownTarget` in `divoom_gui/web_ui/app_globals.js`, `tests/test_e2e_no_invented_fleet.py`);
P5.2, every channel control writing the selected display's own per-channel settings through one funnel that resolves the display at the gesture via `DisplayPreviewRegistry.getActive()`, the app-wide channel globals deleted (`78608ea`; `divoom_gui/web_ui/channel_settings.js`, `tests/test_e2e_channel_settings_per_panel.py`);
P5.4, the weather card showing the PNG of `render_widget {kind: "weather"}` with the reading beside it, the SVG renderer and `get_weather` deleted, loading and failure as distinct placeholders that say why (`4ac2bcf`; `divoom_gui/web_ui/widgets_weather.js`, the converse call-site check in `tests/test_widget_drift.py`);
P5.3, the menubar updating labels, the "Active panel" check and the notification items in place, rebuilding only when the set of rows changes, decided by diffing one `MenuModel` signature (`28f54cd`; `divoom-menubar/src/menu_model.rs`). That meets the exit's menubar half in code; holding the menu open through a fleet change on screen is not yet checked (2026-10-18: the console was locked, so no NSMenu could be held open or captured; 2026-10-18 unlocked, full-screen control for clicking the status item was declined, so it is still unchecked; a two-mock-panel smoke -- selection A, B, A and a row rename over the socket -- left the menubar running). **2026-10-20, the machine half is CONFIRMED and the on-screen half is still the owner's eyes:** the status item's AX "help" text tracks the live fleet model ("4 of 4 panels online — active: Pixoo-1 / Tivoo-Max-light-3 / Timoo-light-4") and changes when `select_device` changes the active panel, so the menubar's model is live; the MENU could not be opened from this session at all (the console is at the login window, and an AXPress on a known-good control — FineTune — opened no window and produced no AXMenu change, so the block is the environment, not divoom-menubar). Holding it open on screen is the last unchecked half;
P5.1, brightness, volume and panel size read and written per mac through the daemon, both name-based size guessers deleted, switching panels shows that panel's values (`f1f7b3b`; `divoom_gui/panels.py`, `divoom_gui/web_ui/panel_facts.js`, `tests/test_e2e_panel_levels_per_panel.py`, `divoomd/src/mock_levels_tests.rs`).

### Phase 6 — the multi-panel wall

**Goal:** a wall is placed by snapping, and LAN panels can join it.
**Exit:** P6.1's *Done when*. **Size:** M. Needs two panels for the final
check.

Landed (2026-10-18): P6.6, with the wall chosen the deck's brightness and
volume are the wall's -- one gesture one wall write that reaches every slot,
the toast naming each slot that did not take it, volume offered only when
every slot's panel has a speaker by the daemon's word, and a mock panel's
wire readable over the socket (`mock_sent`) so the test sees the write
arrive (`039d719`, `092e9b0`; `divoom_gui/web_ui/panel_facts.js`,
`divoom_gui/web_ui/spatial_stage.js`, `tests/test_e2e_wall_levels.py`,
`divoomd/src/daemon_mock.rs`);
P6.4, every GUI display write -- light, clock, channel,
VJ, visualizer, text, scoreboard, brightness, volume, the ticker and the wall
image -- answering one outcome through one funnel that keeps the daemon's
reply, and the page's toast naming each wall panel that did not take it by
its bench name (`402773c`; `divoom_gui/api/__init__.py`,
`divoom_gui/web_ui/display_write.js`, `tests/test_wall_writes_name_the_panel.py`,
`tests/test_e2e_wall_write_names_the_panel.py`);
P6.5, the wall answering `get_last_previews` with each
slot's cut as the slicer produced it (kept only for a slot that took the push),
the wall's methods a declared table held to its arms, and a test holding every
socket command and `device_call` the GUI or a test fake uses to the daemon's
tables -- which also found the wall's rich clock, scoreboard and stock ticker
refused, all three fixed (`3aed256`; `divoomd/src/wall/previews.rs`,
`divoomd/src/wall_preview_tests.rs`, `tests/test_bridge_commands_exist_in_daemon.py`,
`tests/test_e2e_wall_previews.py`);
P6.3, a wall reply naming each linked panel whose write
failed (`failed`, with the reason) apart from each slot with no panel
(`degraded`), every wall command returning one outcome per slot
(`WallOutcome`) instead of one `bool`, the wall switching channels from the
panel's own table, and the wall image push's toast naming the panel by its
bench name (`066c124`; `divoomd/src/wall/outcome.rs`,
`divoomd/src/wall_outcome_tests.rs`, `tests/test_e2e_bench_snap.py`);
P6.1's code, dragged panels snapping flush and lined up
through one pure function, the saved position the snapped one, and a LAN panel
refused as a wall slot with its reason by the daemon (`wall_configure`'s
`refused`, `device_status`'s `wall_refusal`) and in the deck and the wall push
(`eaf199b`; `divoom_gui/web_ui/spatial_snap.js`, `tests/test_spatial_snap.py`,
`tests/test_e2e_bench_snap.py`, `divoomd/src/wall_lan_tests.rs`).

#### P6.1 — Snap adjacent panels into one surface: the hardware check
**Status:** BLOCKED (on a photograph of the two real panels; the machine half is done)
**Why:** the snapping and the refusal are tested in the browser and the daemon,
but nothing has shown one image across two real panels placed by snapping:
the slots are the bench's chassis drawings, so a bezel or a size the drawing
gets wrong would show as a gap or a step at the seam that no test can see.
**Measured 2026-10-20 (Pixoo-1 + Timoo-light-4 as one wall, machine half
CONFIRMED):** `wall_configure` with a grid layout (x=0, x=1) and with a
free-form layout (x=0, x=16) both give EXACT adjacent halves — a blue marker
column lands at source column 15 in slot A and nowhere in slot B, the two cuts
are 16x16 each, 0 of 256 pixels differ from the source halves, and the tile
width is exactly 32 = 16 + 16. The geometry the daemon cuts is right.
**What is left is the glass, not the arithmetic:** the bench geometry is
chassis-based (`getWallSlots` in `divoom_gui/web_ui/spatial_rooms.js` uses
`enc.w_mm * 0.65`), while the visible screen square is inset, so the picture
ON the panels is discontinuous by the bezel width — measured 21 bench px for
Pixoo + Timoo. No camera on this machine sees a panel (it sees a lamp), so
this half needs the owner's photograph.
**Done when:** two real panels dragged edge to edge on the bench show one
image across the seam with no gap, overlap or step (photographed), or the
error is measured and the slot geometry corrected.

#### P6.2 — A panel on Wi-Fi as a wall slot
**Status:** BLOCKED (on a LAN panel bound to the account; the upload path is
KNOWN)
**Why:** P6.1 found the limit is not the wall: the daemon cannot draw an image
on a LAN panel at all (a LAN transport has no `send_command` or
`stream_animation_8b`; `divoomd/src/device_call/lan.rs` has no image command),
and the refusal is stated (`divoomd/src/wall/refusal.rs`).
**Correction (2026-10-20): this item's blocker as written was wrong.** The
roadmap said the vendor app's Wi-Fi upload "did not decompile"; it DID. The
APK smali carries `DesignSendModel.sendByLocalHttp` ->
`HttpCommand.DrawPixelLocalHttp = "Draw/PixelLocalHttp"`, a multipart POST to
`http://<DevicePrivateIP>:9000/upload` (`OkHttpUtils.uploadFileToLocalDevice`),
plus `Draw/EqLocalHttp`, and `DrawPixelLocalHttpRequest` carries fileName,
imageName, flag, authorId, nickName, headFileId, headFileName, lcdIndex and
soundFileName. So the request shape is not the unknown.
**What IS the blocker (measured 2026-10-20):** there is no LAN panel to draw
on. The account is signed in (user_id 401414409; the session token is
redacted here, as everywhere else in this repo) but
`Device/GetListV2` and `Device/GetList` both answer `DeviceList: []`, and
port 9000 is closed on every 192.168.0.1-254 (192.168.0.175 answered once,
then went down). The daemon's LAN transport still has no image command, so
even with a panel the draw is code to write.
**Done when:** a Wi-Fi image command is written against the smali's own
`Draw/PixelLocalHttp` shape (or the public HTTP API's `Draw/SendHttpGif`
checked on a real LAN panel), the daemon draws a slot over it, and the
refusal is deleted — which needs a Wi-Fi panel bound to the account first.

### Phase 9 — parked on something outside this repo

**Goal:** none until the named trigger fires; each item says what unparks it.

#### P9.1 — `search_weather_city` fails server-side
**Status:** BLOCKED (on a capture of the official app's city search)
**Why:** the endpoint returns RC=1 for every keyword on a valid account while
other cloud calls in the same minute succeed. Guessing field names is ruled out.
`scripts/hw_verify.py` carries it as an XFAIL canary that reports XPASS if the
server starts answering.
**Done when:** a capture shows the request the server accepts, or the feature
is removed.

#### P9.2 — Scrolling text has no GUI
**Status:** BLOCKED (on a panel that acks 0x7C)
**Why:** the APK marquee is ported (`divoomd/src/device_call/text.rs`), but the
Tivoo-Max acked nothing for 0x6E/0x7C/0x86 while the bytes were proven correct.
The GUI Text channel pushes a static image and ignores its speed/effect
arguments (`divoom_gui/api/lighting.py`).
**Done when:** a device acks 0x7C in a trace, then a GUI control is wired.

#### P9.3 — Light/dark backdrop check of the four widgets on a real panel
**Status:** BLOCKED (on a photograph against both backdrops; eyes are the blocker)
(2026-10-18: the four bench panels were all in scan range and the packet's
four widget pushes were sent OK by `scripts/hw_verify.py`, each UNKNOWN for
want of anyone looking; panels are not the blocker, eyes are.)
**2026-10-20, the machine half of the four pushes is CONFIRMED** (Pixoo-1,
installed v0.41.3): `sysmon` paints a frame that CHANGES with load (three
distinct pictures, CPU 12 -> 50) and equals `render_widget sysmon`; `weather`
paints a frame byte-identical to `render_widget weather` (0 of 256 pixels
differ) and it is ONE combined icon + temperature frame — the firmware's
cycling face is gone (P3.3); `custom_art` paints the source image downscaled
NEAREST (18 of 256 pixels differ by 1-2, palette quantisation) rather than the
216 that a BILINEAR smear would give, so it is neither a smear nor a crop;
`album_art` pushes nothing because nothing is playing (`now_playing` answers
"Kaset (not playing)") — the documented precondition, not a failure.
**Why:** the R12 visual pass verified the widgets on the panel but never judged
them against a light AND a dark surrounding. It is a photograph, not code.
**Still open:** a camera on this machine cannot see a panel (after a blue push
it counted 0 blue-dominant pixels — it sees a lamp, not the panels), so the
backdrop judgement is the owner's photograph.
**Done when:** photos against both backdrops are judged and filed with the
round's notes.

#### P9.4 — Two `objc2` majors in the lock
**Status:** WATCH
**Why:** winit 0.30 pins `objc2` 0.5 (0.5.3 in the lock on 2026-10-12);
everything else is on 0.6 (0.6.5). No type crosses between them, so it costs
build time only.
**Done when:** a stable winit on `objc2` 0.6 is taken and the lock holds one
(`cargo tree -i objc2` prints one version).

#### P9.6 — The June 2026 hardware deferrals, re-checked on the Rust daemon
**Status:** BLOCKED (on a hardware session with an SPP panel and the 4-panel rig)
**Why:** the June 2026 adversarial review loop (Python era) closed with five
items it could not settle without hardware. One is gone (the C static encoder
was deleted in v0.40.0) and one was P1.7, landed 2026-10-16. The other three
were never re-checked
after the port: (a) SPP framing vs BLE (escaping, packet number, write pacing,
response-timeout clearing) now that `divoom_client/spp_bridge.py` carries bytes
the daemon frames; (b) a 0x8B retransmit request arriving in the re-arm window
of the animation stream (`divoomd/src/ble.rs` phase 3); (c) a custom-art ACK
treated as success while the 0x8E read-back is unreliable
(`divoomd/src/device_call/animation.rs`).
**Done when:** each of (a)-(c) has a `DIVOOMD_BLE_DEBUG` trace read with the
A/B rule (Hardware reference below) and is either closed with the trace cited
or becomes its own OPEN item with a reproduction.

#### P9.5 — Python majors that cannot be taken yet
**Status:** WATCH
**Why:** `multidict` 7 (aiohttp caps <7), `pyee` 14 (playwright caps <14) and
`playwright` 1.63 (camoufox 0.5.5 caps <1.61) are unreachable, not declined.
**Done when:** each parent widens its cap and the major moves in its own commit.

#### P9.7 — A lease on a panel with no live widget gives back the firmware channel
**Status:** BLOCKED (on eyes on the panel: does re-selecting channel 5 show the
pushed image again, or the custom gallery?)
**Measured 2026-10-18** (Pixoo-1, `DIVOOMD_BLE_DEBUG` trace, 0x46 byte 0 =
`current_light_effect_mode`): after `show_clock` 0; after `set_channel 1`
(light) 1, with brightness and on/off reading 0; after a pushed image
(`display.show_image`, `0x45 05..` then 0x8B) 5; `set_channel 3` (VJ, a
one-byte `0x45 03`) drew no echo while `0x45 01` echoed in the same window,
and 0x46 stayed 0 -- this panel does not take that form.
**Measured again 2026-10-20, and the channel half is now settled:** 0x46 byte 0
reads the channel back in every case (clock -> 0, `set_channel 1` -> 1, a
pushed image -> 5), the device ECHOES 0x45 for every channel except 3 (VJ),
which draws no echo in either the one-byte or the 10-byte form — the
panel-specific gap this item already recorded — while the control `0x45 01`
echoed in the SAME window, so the silence is the panel and not the trace. A
re-selected channel 5 is ACCEPTED: 0x46 reads 5 back after it.
**What is left is a pixel question, and it is the whole item:** whether
`0x45 05` puts the pushed image back up or the channel's own custom gallery.
Both are plausible; only eyes can tell, and the lease must not restore a
screen the user never chose.
**Why:** a screen lease (`divoomd/src/lease.rs`) hands a panel back to its
live widget by repainting the widget's newest frame. A panel with no widget
is left showing the holder's last frame, and `lease_release` says so
(`restored: "none"`). Reading the channel with 0x46 at acquire and selecting
it again at the end is the obvious fix, but nobody has watched what 0x46
reports after a pushed image, or whether re-selecting that channel shows the
image again or the channel's own gallery. Restoring a guess would put up a
screen the user never chose.
**Done when:** a `DIVOOMD_BLE_DEBUG` trace on a panel shows what 0x46 reads
after a clock, a channel and a pushed image (done, 2026-10-20), AND a
photograph says what re-selecting channel 5 shows, and the lease then
restores each case it can restore faithfully, saying `restored: "channel"`,
with the rest left as `"none"` by measurement rather than assumption.

#### P9.8 — Is the "monthly best" category a sliding window?
**Status:** WATCH
**Why:** the owner asked on 2026-10-21 whether the category slides and said
they were not sure. The name says "monthly", the content is refreshed almost
daily, and the files it returns carry dates from 2020 to 2026 — so neither the
name nor a single snapshot can answer it. It is a MEASUREMENT, and the
measurement is now being taken: every scheduled push writes down what the
category returned — the file names, the dates they carry and their ids — into
the daemon's log and into
`~/.config/divoom-control/hotchannel_fetches.json` (the last 14 runs).
**What is left:** two dated snapshots a day apart, and the diff between them.
**Done when:** two runs' snapshots exist on different days, and the diff says
which files came and which went — then the answer (window or not, and of what
width) is written down in `CHANGELOG.md` and this item is deleted.

#### P9.9 — The magic-26 family's other frame flags are not read
**Status:** WATCH
**Why:** the gallery's magic-26 containers are the flag-`0x0C` form (a
palette and LSB-first indices in a 4x4 grid of 16x16 tiles), and
`divoomd/src/art_codec/iframe.rs` reads that, the raw forms (`0x0B`, `0x11`),
the 128x128 palette form (`0x12`) and the quadtree (`0x15`). Two more flags
exist in the app's own dispatcher and are NOT read here: `0x00`, the
standard 7-byte `AA` form the daemon itself encodes (the app picks its size
from the picture, not from the container's grid), and `0x14`, the palette
form in the "net" colour order, which the app converts with
`convert_rgb_local_to_net_128` before it shows it. Both are REFUSED rather
than guessed at, and no gallery file has carried either.
**The trigger is named:** the run now prints the frame flag of every file it
could not show, so the first `0x00` or `0x14` in a gallery run is visible in
the daemon's log. (A magic-26 animation is also decoded to its first 24
frames — the same bound the magic-9 and magic-18 decoders carry — so a long
animation plays as its first 12 seconds.)
**Done when:** a gallery file carries a flag this decoder refuses, and the
refusal is lifted by reading that flag out of the native library the same way
`0x0C` was — or the flags are shown never to appear and this item is deleted.

#### P9.10 — The stored gallery cannot be READ BACK on this hardware
**Status:** WATCH (the trigger is named: a panel that answers `0x8E`)
**Why:** the push now STORES the art in the device's own gallery — the
custom-art page, `divoomd/src/gallery_store.rs`, the only persistent art
store this protocol has for a 16×16 panel — instead of only streaming it
past. The WRITE is the device's own acknowledgement of the save command
(`0xB1`, the app's own page writer), and the panel is then told to PLAY the
stored page (`0xBD [0x17, page]`). What is MISSING is the READ-back: `0x8E`
("App get user define info" — the file ids a page holds) does not answer.
Measured 2026-10-21 on all four of the owner's panels (Pixoo-1,
Ditoo-light-2, Tivoo-Max-light-3, Timoo-light-4): every `0x8E` timed out,
while `0xB6` ("how many user-defined items") answers on three of them and
`0xBD [0x15]` ("get user define time") answers on all four — so the panels
are alive and the store is not the missing thing. The protocol has no screen
readback either, so what is ON the panel cannot be read from this side.
**The trigger is named:** the run asks the device after every store and
prints its answer, so the first `0x8E` that answers is visible in the
daemon's log.
**Done when:** a panel answers `0x8E` with the ids of what the push stored —
then the run can report the store as CONFIRMED instead of "the device
accepted the save" — or the owner says the art is on the panel and this item
is deleted.

---

## Standing rules


### The per-device rule (read before adding any per-panel state)

**All per-device state lives on ONE struct per panel** — `Device` in the
daemon, `DeviceView` in the menubar, `discoveredDevices[mac]` in the GUI —
and each fact has ONE writer. The class this closes: two owners of one
per-panel fact drifting apart. It produced, in one day, a frame that landed
after "stop", a push on the wrong panel, a fleet renamed "Divoom", jewels
that were always green, and previews that stopped following the device.

* Anything that sends to a panel goes through `Device::link()` ->
  `Link::run` / `Link::queue.acquire`. Never hold a transport `Arc` across an
  await without the link's permit. Never key new per-device state by mac
  string — put it on `Device`.
* A queued unit of work holds the `Link` it was queued on and re-checks
  `retired` (and its job's `alive`) at execution time. Abort alone never
  cancels work already handed to the queue worker.
* There is no "current" device. The ACTIVE panel is a user selection the
  daemon owns (`Fleet::selected`); a mac-less request resolves to it while
  it is linked, else to the single linked panel, else is refused. The GUI
  names its panel on every call anyway.
* The selection changes through ONE funnel everywhere: bench click ->
  `select_device`, menubar "Active panel", CLI `select`; the daemon
  broadcasts `selection`/`owned_devices` and every client follows. The
  bench's first-render fallback is provisional (Python proxy only). A
  status event updates the panel it names; the global dot follows the
  active panel; a status naming nobody is fleet-wide.
* The gate is `divoomd/tests/live_jobs_stress.rs`; every new scenario there
  should be shown red first.

Now Playing is read per client since v0.37.0 (the earlier "one session"
residual was a mis-declared call, not a platform limit).

### The ownership rule — what counts as a duplicate

`divoomd` (Rust) is the shipping implementation of every DEVICE, CLOUD and HOST
capability; `divoom_lib` is the protocol ground truth it was ported from and
is still imported at runtime by the client for constants, pure helpers and
client preferences. A `divoom_lib` import is a defect when it performs a job
the daemon owns (device I/O, cloud HTTP, host data, rendering, device-facing
persistence) and fine otherwise; `tools/capability_census.py` enforces exactly
that line and its confident set is zero. Python stays canonical for WIRE
FORMATS: every R67 packet bug was found by diffing the Rust payload against the
Python builder, and Python was right every time, which is why parity gates
(`tools/check_weather_parity.py`, `tools/check_hotchannel_parity.py`) exist.
One exception is structural, not a duplicate: macOS Classic SPP is unreachable
from Rust, so `divoomd/src/spp.rs` spawns `divoom_client/spp_bridge.py` and
still owns the device.

### Rules that came from shipped bugs

- **A re-render is not a selection.** Anything that runs on every status or scan
  event (`SpatialStage.refresh`, `PanelLevels.show`) repaints; it never moves
  the user's tab, rebuilds the node under a drag, or sets a control the pointer
  holds. Selection side effects belong to the gesture that selects
  (`tests/test_e2e_rerender_keeps_user_state.py` fires the refresh mid-gesture).
- **A test owns the in-flight state it asserts on.** A mock that answers on a
  timer makes "during the call" a window a loaded runner overshoots; hold the
  promise and release it from the test (`tests/test_e2e_ux_feedback.py`).

- **A deletion is only as safe as its consumer list**, and the list is never
  the one you remember: v0.40.0 missed the archived `examples/tests/` suite and
  the callers that EXECUTE things (CI workflows, the Linux host, `build.sh`).
  `tools/check_scripts.py` check 4 gates the second class.
- **`examples/` is a spec, not dead weight.** `examples/divoom_legacy/` is the
  only executable oracle for the daemon's `device_call` arms
  (`examples/tests/test_device_call_parity.py`, `tools/check_positional_args.py`).
  Port both to a recorded signature table before `examples/` is ever deleted.
- **Pins move with their channel.** The camoufox pin went stale twice because a
  pin looks like discipline and staleness looks identical. Move it in its own
  commit when the channel moves, after running the browser suites against the
  candidate: edit `.camoufox-build` (the only copy) and run the install command
  `tools/camoufox_installed.py` prints.
- **A dependency bump can change what a number MEANS.** sysinfo 0.30 -> 0.39
  changed `used_memory()`'s formula under the same signature; v0.41.0 then
  misread its own measurement. Re-derive with `tools/mem_gauge_compare.py`
  (gated by `tests/test_mem_gauge_parity.py`), and judge visual bumps on
  `tools/render_tray_icon.py` sheets, not on a full live menu bar.
- **Gated capabilities are decisions, not gaps.** 5-LCD commands wait on a Times
  Gate this project has no reason to own; `Voice/SendText` waits on a real
  render, because a similar command once ACKed cleanly and drew nothing. Danmaku
  is GUI-wired but unconfirmed on a panel, and says so on Bluetooth-only devices.

### Hardware reference — driving a real panel

Durable how-to, not a backlog item. The TCC rule itself is in the Hardware
bullet of `AGENTS.md`: a daemon started from a shell has no Bluetooth grant and
dies on its first BLE scan with SIGABRT and an empty stderr.

**The packet.**

    python3 scripts/hw_verify.py --self-test        # calibrate first
    python3 scripts/hw_verify.py --out report.json

The packet shows you the frame the DAEMON painted and asks you to compare the
panel with it; it carries no description of what the panel should look like
(a description written here goes stale the moment the daemon's renderer
changes, and a stale description grades a working widget FAIL — the `weather`
check said the device "cycles" after P3.3 started drawing one combined frame).
The frames are saved next to the report (`--frames-dir` to choose where), and
a widget that painted NOTHING is a machine FAIL rather than a question for
you; a check whose precondition is unmet (nothing playing) is a SKIP.
`tools/check_hw_verify_methods.py` gates the packet's method names against the
daemon's match arms — and the hand-written-LOOK rule, so the class cannot
come back.

Start the GUI first: it owns the Bluetooth grant, and the packet refuses to
spawn its own daemon. `--self-test` exits **3 = PARTIAL** until a device is
connected. `tools/check_hw_verify_methods.py` gates the packet's method names
against the daemon's match arms. `album_art` needs something PLAYING — with no
track the music job has nothing to push, and a dark panel then means "nothing
playing", not "broken". `search_weather_city` is the XFAIL canary (see above).

**The exit code is the verdict.** `scripts/hw_verify.py` exits 0 when every
check that ran was answered, **1** when a check FAILED — including a branch
that RAISED, which is never a warning — **2** when the daemon is not there or
the arguments are wrong, and **3** when nothing was proven: a verdict was
UNKNOWN or SKIP, or the self-test has one branch proven and one still owed.
`scripts/hw_smoke.py` exits 0 clean, 1 when any branch failed, 2 when the
daemon is not there.

**A script prints through the house PUBLIC helpers** — `info`, `step`, `ok`,
`err`, `warn`, `hr`, `section` from `tui/lib.py` (or `tools/_tui.py`, which
resolves the same helpers in CI). The TUI's colour constants are
module-private (`_C_GRAY`, `_C_RESET`, ...); naming one from a script is a
NameError, and `tools/check_scripts.py` now fails the push for it.

**A locally built daemon on hardware.** Let the app be the responsible process:
`scripts/build_release.sh` then `scripts/install_local.sh`, which quits the app,
refuses to install over a running bundle, `open`s it, and proves the running
daemon's text inode is the file it wrote. With the local signing identity
present (`scripts/make_signing_identity.sh`, once) there is no Bluetooth prompt.
For a traced daemon, `scripts/make_dev_daemon_app.sh` (`DIVOOMD_BLE_DEBUG=1`,
log at `/tmp/divoom_dev_daemon.log`, lines tagged `[ble <id>]`); quit the GUI
first or it respawns its own daemon over the socket. Then drive
`/tmp/divoom.sock`: `connect {mac}` works directly, while `scan` often reports
"already in progress" while the GUI scans (and see the reconnect item above).
`cargo test` rebuilds `target/debug/divoomd` WITH default features, so a
BLE-free build does not stay BLE-free across a test run.

**Reading a trace.** A device ECHOES `basic frame cmd=0xNN` for opcodes its
firmware implements. A silence proves nothing on its own — send a known-good
command (`0x45`) first in the SAME window and compare.

---

## Quality baseline

Measured 2026-10-05 unless dated otherwise. These are the numbers a regression
is judged against; when one moves, change it here in the same commit.

| Measure | Value | Where it is enforced |
|---|---|---|
| Local gate | 30 `GOH_CI_STEPS` (incl. the browser suites and CI's Linux `--all-features` lint, 2026-10-20) + `scripts/py_ci.sh` = 31 steps, run by `pre-push` on the pushed commit in a clean worktree | `.gatesrc`, `tools/gate.sh`, `scripts/ci_local.sh` |
| Python tests (default) | 2095, 176 skipped (2026-10-20) | `pytest.ini` (`testpaths = tests`) |
| `examples/tests` | 1022 passed, 73 skipped (2026-10-19) | `scripts/py_ci.sh` |
| Browser subset | 230 passed (2026-10-19, beta.39, `-n 8`; in the local gate and CI, through `scripts/browser_e2e.sh`) | `scripts/browser_e2e.sh` |
| Rust tests | 659 (2026-10-20) | `cargo test --locked` |
| Python coverage floor | 89.0 (see P1.4) | `scripts/py_ci.sh` |
| Rust coverage floor | 42 | `scripts/rust_coverage.sh` |
| File length | 500 lines, allowlist empty | gates_of_heck structural layer |
| Process calls | 73 in 53 files, every one declaring its stdin (2026-10-21) | gates_of_heck structural layer (`goh subprocess-stdin`) |
| Daemon/client duplication | 0 DIRECT, 0 WRAPPED | `tools/capability_census.py` |

**Flake ledger** (one line each; a repeat earns an investigation):
- 2026-09-13, full gate at load ~20: `socket_bind::tests::clears_a_stale_socket`
  saw `UnresponsiveListener` (a connect to a dropped listener's file succeeded,
  then silence). 5/5 green alone.
- 2026-10-14, full gate at load ~140, under `cargo llvm-cov` only:
  `a_subscriber_that_stops_reading_is_dropped_and_frees_its_slot` parsed two
  NDJSON lines as one (P0.4). 3/3 green alone.
- 2026-10-20, the browser suite inside the pre-push gate at 8 and at 4
  workers: THREE different UI-timing tests failed in three runs — the bench
  drag's `bounding_box()` came back None, the gallery never overflowed inside
  its wait, and the gallery tab was "not stable" for a 2 s click. Each passes
  alone and in a fresh worktree; the suite is pushed SERIALLY, the way CI runs
  it. The class is UI timing under parallel browsers, and it earns an
  investigation of its own before the next 8-wide local run.

---

## Owned elsewhere — estate-wide items this repo depends on

Tracked here only because this repo shares its gate layer with routines, ztools,
monitor and app_updates; each belongs to the repo named.

- **Restriction lints** (`unwrap_used`, `expect_used`, `panic`) are adopted
  nowhere. A correctness campaign with its own review, not a switch to flip.
- **homebrew-tap's T2.3 (the cask's `pkill`) is UNBLOCKED as of 2026-10-20.**
  The tap's cask stopped the app's helpers with a NAME PATTERN, because they
  had no stable identity. They have one now: the app writes an identity file
  per helper it spawns (`~/.config/divoom-control/run/divoomd.pid`,
  `.../divoom-menubar.pid`), naming the process by pid AND by the moment it
  started, so a stale identity from a crashed run names nothing and the
  reader leaves an innocent process alone. The cask's change is the TAP's to
  make; this repo's half (the identity, the quit path that clears it, and the
  `pkill` this repo used for the same job) is done.
- **PATH decides which build of a tool runs, and installers do not check.**
  `app_updates` shows the fix: after copying, ask the binary its identity and
  confirm `command -v` resolves to the copy just written. The user's `.zshrc`
  PATH entry for routines is theirs to change, not this repo's.
- **`routines` needs an in-process self-watchdog** for the same reason as P2.6.
- **antiknob** shares the tray-icon question (fixed the same way, 2026-10-05) and
  keeps its own plan in its `PLAN.md`.
- **gates_of_heck's proven-step cache treats a step's EXIT STATUS as its
  effect, and a build's effect is an ARTIFACT.** The pre-push gate runs in a
  FRESH worktree; the cache (`GOH_PROVEN`, on by default) skips a step whose
  exit status it recorded earlier on the same tree — so a skipped
  `cargo build -p divoomd --locked` leaves NO binary behind, and the later
  `py_ci` step then fails with "divoomd (Rust daemon) binary not found" on
  the daemon-spawn tests (`tests/test_daemon_connect_edge_e2e.py`),
  for a reason that has nothing to do with the tree. Measured 2026-10-20: the
  cache had been filled by an earlier push attempt on the SAME commit, so
  step 27 was skipped as "proven on this tree 8m ago" and step 30 failed.
  The cache must key on what a later step CONSUMES, or the step list must not
  let a skipped step feed a later one. (Not fixed here: gates_of_heck is
  another repository. Reproduce with `GOH_PROVEN=0 git push` — every step
  then runs and the suite is green.)

---

## Reference

**Architecture.** UI: Python pywebview GUI (`divoom_gui/`). Daemon: Rust
`divoomd` (unix-socket NDJSON, sole BLE/LAN/cloud owner). Menubar: Rust
`divoom-menubar` (winit + tray-icon). Encoders: Rust (`divoomd/src/image_encode.rs`,
`divoomd/src/framing.rs`), pinned to 550 framing and 192 image vectors from the
deleted C. Transport: BLE (CoreBluetooth via btleplug), LAN HTTP, Divoom cloud
HTTP, and Classic SPP through the co-process above.

**Protocol coverage.** Cloud HTTP: 533/533 endpoints catalogued in
`docs/cloud_api/` (16 batches). WiFi/LAN: all 45 commands from the APK's
`HttpCommand.java` implemented; the backend-only ones are the gated
capabilities above.

**Shipped, by release:** `CHANGELOG.md` -- the newest stanza is `v0.41.3`
(2026-10-19: the browser e2e suites run in the local gate, and the app's own
startup no longer overwrites live state); the release table this file carried
until 2026-10-14 is `git show a8a848d:docs/ROADMAP.md`.

---

## Sources consolidated (2026-10-12)

Every agent session that ever worked on this repo was read and given a
disposition on 2026-10-12, then removed; nothing in them is open beyond the
items above. The table (opencode loop, Antigravity, Gemini CLI, Claude
desktop and memory, the landed worktree, the cross-project plans) is
`git show a8a848d:docs/ROADMAP.md`.
