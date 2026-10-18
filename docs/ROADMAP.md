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
Twelve items have landed since (P1.1 `15ff359` on 2026-10-15; P1.6, the
build/install platform gate, and P1.7, the RX frame parser's one-byte resync, on
2026-10-16; P1.12, the framing-vector generator, P1.5, the two-suite
collection fix, P1.2, the PyInstaller pin from a committed file, P1.4, the
coverage floor ratcheted to the measurement, P1.3, the stale `tao` comments
in CI, P1.8, the 52 hand-rolled status markers, P1.11, the short-frame panic
fixed on both sides, P1.10, CI reading Python from `.python-version`, and
P1.9, the release bumping the cask through the tap's gate, also on
2026-10-17), so the items below have
NOT been re-derived against a later HEAD -- check an item against the code before
working it. Phase 0 is new (goh 0.27.0's fallout,
measured); the old Phase 0 became Phase 1 and every later phase moved up by one
(P9 unchanged), and the old P0.8 (camoufox) is now P0.2. Each phase states its
goal, exit criterion and rough size in sessions (S = under one, M = one or two,
L = three or more).
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

### Phase 1 — correctness defects and drift (small, independent)

**Goal:** no known defect or gate hole stays open while feature work starts.
**Exit:** every P1 item's *Done when* is a test or gate that was watched red
first. **Size:** M (all items landed). Depends on Phase 0
(nothing pushes until it lands).

**Phase 1 complete** (2026-10-17): all eleven P1 items landed (P1.1, P1.2, P1.3,
P1.4, P1.5, P1.6, P1.7, P1.8, P1.9, P1.10, P1.11).
### Phase 2 — daemon liveness and safety

**Goal:** the daemon can say who holds it, never hangs on one peer, and
notices its own wedge. **Exit:** P2.1-P2.6 each pinned by a test that stalls,
floods or wedges the real socket server; P2.7 has a trace or is gone.
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

#### P2.7 — The panel does not always come back after a daemon restart
**Status:** OPEN
**Why:** seen repeatedly on 2026-09-07: `scan` times out while `connect` with
the saved identifier succeeds at once. Unexplained; it costs every hardware
round time, and nobody knows whether normal use (no restarts) is affected.
**Done when:** a BLE trace (`DIVOOMD_BLE_DEBUG`) of one failing restart is
captured and the cause named, or the reconnect path uses the saved identifier
first and the symptom is gone.

### Phase 3 — the daemon knows what each panel is

**Goal:** one owner (the daemon) for each panel's model, size and failure
codes. **Exit:** `device_status` carries model/size and errors carry codes,
with tests per model class. **Size:** M. **Release check (needs a panel):**
P3.3 changed what the weather widget looks like on every panel; it needs the
R12-style visual pass on hardware before release.

Landed (2026-10-17): P3.1, `device_status` carrying each panel's model and resolution from the APK's own tables (`divoomd/src/panel_model.rs`);
P3.2, a stable `code` on every device failure, branched on by the Settings card (`divoomd/src/error_code.rs`);
P3.3, weather drawn by us as a `render_widget` frame and pushed like every other widget, the firmware's clock face no longer selected (`divoomd/src/live_jobs/weather_frame.rs`).

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

Landed (2026-10-18): P5.8, a live job or activity record naming a panel no link ever made a fleet entry refused with `unknown_device` naming the mac, the fleet's only constructor private behind `Fleet::adopt` and the client path a `Fleet::known` lookup, a linked-then-dropped panel keeping a new job waiting, `MatrixWall` refused as the wall surface rather than a panel, and MCP/CLI tool errors carrying the daemon's `code` (`0f73dda`; `divoomd/src/device/fleet.rs`, `divoomd/src/error_code.rs`, `divoomd/tests/unknown_panel.rs`);
P5.7, every other bridge call that acts on a panel -- the Tools tab, the alarms editor, the live widgets, the stock tile, the gallery, hot-channel and custom-art pushes, `device_call` -- naming it first through `ApiBase._display(mac)` (the wall refused for one-panel actions and named, never defaulted, for the rest), `current_divoom` deleted, and one test enumerating every public bridge method so a new one without a mac fails (`691e0b5`; `tests/test_device_actions_name_their_panel.py`, `tests/test_e2e_device_action_reaches_its_panel.py`, `divoomd/src/mock_tools_tests.rs`);
P5.6, every channel bridge call naming the panel its click resolved, through one `ApiBase._display(mac)` to the daemon, a call naming no panel refused, `_target()` and `current_target_mode` deleted, and `_LanView` forwarding the daemon's `lan.*` calls so albums, playlists and the overlay work through the real proxy (`0a8aa81`; `divoom_gui/api/__init__.py`, `tests/test_e2e_channel_write_reaches_its_panel.py`, `tests/test_channel_writes_name_their_panel.py`, `divoomd/src/mock_channel_tests.rs`);
P5.5, with no panel known the bench showing an empty state that says how to add one and the deck "No panel selected" with no levels, the active-panel lookup answering null instead of an invented mac (`f56b550`; `window.isKnownTarget` in `divoom_gui/web_ui/app_globals.js`, `tests/test_e2e_no_invented_fleet.py`);
P5.2, every channel control writing the selected display's own per-channel settings through one funnel that resolves the display at the gesture via `DisplayPreviewRegistry.getActive()`, the app-wide channel globals deleted (`78608ea`; `divoom_gui/web_ui/channel_settings.js`, `tests/test_e2e_channel_settings_per_panel.py`);
P5.4, the weather card showing the PNG of `render_widget {kind: "weather"}` with the reading beside it, the SVG renderer and `get_weather` deleted, loading and failure as distinct placeholders that say why (`4ac2bcf`; `divoom_gui/web_ui/widgets_weather.js`, the converse call-site check in `tests/test_widget_drift.py`);
P5.3, the menubar updating labels, the "Active panel" check and the notification items in place, rebuilding only when the set of rows changes, decided by diffing one `MenuModel` signature (`28f54cd`; `divoom-menubar/src/menu_model.rs`). That meets the exit's menubar half in code; holding the menu open through a fleet change on screen is not yet checked (2026-10-18: the console was locked, so no NSMenu could be held open or captured; a two-mock-panel smoke -- selection A, B, A and a row rename over the socket -- left the menubar running);
P5.1, brightness, volume and panel size read and written per mac through the daemon, both name-based size guessers deleted, switching panels shows that panel's values (`f1f7b3b`; `divoom_gui/panels.py`, `divoom_gui/web_ui/panel_facts.js`, `tests/test_e2e_panel_levels_per_panel.py`, `divoomd/src/mock_levels_tests.rs`).

#### P5.9 — P5.8's three leftovers: a job on a removed panel, wasted activity calls, uncoded missing-argument replies
**Status:** OPEN
**Why:** P5.8 (`0f73dda`) left three defects. (1) `LiveJobCoordinator::start`
(`divoomd/src/live_jobs/coordinator.rs`) looks the panel up with
`Fleet::known` and installs the job later, outside any lock: a `disconnect`
that removes the panel in between leaves a running job on a panel no longer
in the fleet, and the reply says success. (2) The web UI
(`divoom_gui/web_ui/app_globals.js`, `window.setDeviceActivity`) still sends
`set_device_activity` for `MatrixWall` and for panels the daemon never
reported; the daemon refuses every one, so each call is wasted. (3) A missing
required argument is answered with prose and no `code` (`live_job_start
requires 'mac'`, 27 sites across the handlers), so a program cannot tell a
malformed request from any other failure.
**Done when:** lookup-and-install cannot interleave with removal, pinned by a
deterministic interleaving test (a hook between lookup and install, not a
sleep) watched red on `0f73dda`; a browser test sees no `set_device_activity`
naming `MatrixWall` or an unreported mac, watched red; and one test walks the
daemon's command table and asserts a missing required argument yields a
`bad_request` reply for every command, watched red.

### Phase 6 — the multi-panel wall

**Goal:** a wall is placed by snapping, and LAN panels can join it.
**Exit:** P6.1's *Done when*. **Size:** M. Needs two panels for the final
check.

Landed (2026-10-18): P6.1's code, dragged panels snapping flush and lined up
through one pure function, the saved position the snapped one, and a LAN panel
refused as a wall slot with its reason by the daemon (`wall_configure`'s
`refused`, `device_status`'s `wall_refusal`) and in the deck and the wall push
(`eaf199b`; `divoom_gui/web_ui/spatial_snap.js`, `tests/test_spatial_snap.py`,
`tests/test_e2e_bench_snap.py`, `divoomd/src/wall_lan_tests.rs`).

#### P6.1 — Snap adjacent panels into one surface: the hardware check
**Status:** BLOCKED (on two real panels at the bench)
**Why:** the snapping and the refusal are tested in the browser and the daemon,
but nothing has shown one image across two real panels placed by snapping:
the slots are the bench's chassis drawings, so a bezel or a size the drawing
gets wrong would show as a gap or a step at the seam that no test can see.
**Done when:** two real panels dragged edge to edge on the bench show one
image across the seam with no gap, overlap or step (photographed), or the
error is measured and the slot geometry corrected.

#### P6.2 — A panel on Wi-Fi as a wall slot
**Status:** BLOCKED (on a source for the Wi-Fi image upload and a LAN panel)
**Why:** P6.1 found the limit is not the wall: the daemon cannot draw an image
on a LAN panel at all (a LAN transport has no `send_command` or
`stream_animation_8b`; `divoomd/src/device_call/lan.rs` has no image command),
and the vendor app's Wi-Fi upload (`DesignSendModel.sendByLocalHttp`) did not
decompile. The refusal is stated (`divoomd/src/wall/refusal.rs`).
**Done when:** a Wi-Fi image command is taken from a source (a decompile of
`sendByLocalHttp`, or the public HTTP API's `Draw/SendHttpGif` checked on a
real LAN panel), the daemon draws a slot over it, and the refusal is deleted.

### Phase 7 — decisions for the owner

**Goal:** the owner's calls, each with the evidence needed to make it.
**Exit:** a recorded ruling per item. **Size:** S once decided.

#### P7.1 — The tray glyph tells states apart by colour alone
**Status:** DECISION (owner)
**Why:** Offline / Online / Error differ only in fill (grey / green / red); green
vs red is the pair about 1 in 12 men cannot separate (house rule: colour
reinforces, shape carries). Also, the `#F5F5F5` border is invisible on a light
menu bar at every size, so there the glyph is only its fill.
**Done when:** the owner picks a design (e.g. hollow Offline, barred Error) and
the states differ in greyscale on `tools/render_tray_icon.py` sheets.

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
**Status:** BLOCKED (on a hardware session with a camera)
**Why:** the R12 visual pass verified the widgets on the panel but never judged
them against a light AND a dark surrounding. It is a photograph, not code.
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
**Status:** BLOCKED (on a panel: what 0x46 reports after a pushed image is unmeasured)
**Why:** a screen lease (`divoomd/src/lease.rs`) hands a panel back to its
live widget by repainting the widget's newest frame. A panel with no widget
is left showing the holder's last frame, and `lease_release` says so
(`restored: "none"`). Reading the channel with 0x46 at acquire and selecting
it again at the end is the obvious fix, but nobody has watched what 0x46
reports after a pushed image, or whether re-selecting that channel shows the
image again or the channel's own gallery. Restoring a guess would put up a
screen the user never chose.
**Done when:** a `DIVOOMD_BLE_DEBUG` trace on a panel shows what 0x46 reads
after a clock, a channel and a pushed image, and the lease restores each case
it can restore faithfully, saying `restored: "channel"`, with the rest left
as `"none"` by measurement rather than assumption.

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
  candidate (`tools/camoufox_installed.py`, `tests/support/browser.py`).
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

Start the GUI first: it owns the Bluetooth grant, and the packet refuses to
spawn its own daemon. `--self-test` exits **3 = PARTIAL** until a device is
connected. `tools/check_hw_verify_methods.py` gates the packet's method names
against the daemon's match arms. `album_art` needs something PLAYING — with no
track the music job has nothing to push, and a dark panel then means "nothing
playing", not "broken". `search_weather_city` is the XFAIL canary (see above).

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
| Local gate | 24 `GOH_CI_STEPS` + `scripts/py_ci.sh` = 25 steps, run by `pre-push` on the pushed commit in a clean worktree | `.gatesrc`, `tools/gate.sh`, `scripts/ci_local.sh` |
| Python tests (default) | 1640, 129 skipped | `pytest.ini` (`testpaths = tests`) |
| `examples/tests` | 1095 (2026-10-04) | `scripts/py_ci.sh` |
| Browser subset | 177, all passing (opt-in `--run-browser`, own CI step) | `.github/workflows/tests.yml` |
| Rust tests | 486 (2026-10-04) | `cargo test --locked` |
| Python coverage floor | 88.5 (see P1.4) | `scripts/py_ci.sh` |
| Rust coverage floor | 42 | `scripts/rust_coverage.sh` |
| File length | 500 lines, allowlist empty | gates_of_heck structural layer |
| Daemon/client duplication | 0 DIRECT, 0 WRAPPED | `tools/capability_census.py` |

**Flake ledger** (one line each; a repeat earns an investigation):
- 2026-09-13, full gate at load ~20: `socket_bind::tests::clears_a_stale_socket`
  saw `UnresponsiveListener` (a connect to a dropped listener's file succeeded,
  then silence). 5/5 green alone.
- 2026-10-14, full gate at load ~140, under `cargo llvm-cov` only:
  `a_subscriber_that_stops_reading_is_dropped_and_frees_its_slot` parsed two
  NDJSON lines as one (P0.4). 3/3 green alone.

---

## Owned elsewhere — estate-wide items this repo depends on

Tracked here only because this repo shares its gate layer with routines, ztools,
monitor and app_updates; each belongs to the repo named.

- **Restriction lints** (`unwrap_used`, `expect_used`, `panic`) are adopted
  nowhere. A correctness campaign with its own review, not a switch to flip.
- **PATH decides which build of a tool runs, and installers do not check.**
  `app_updates` shows the fix: after copying, ask the binary its identity and
  confirm `command -v` resolves to the copy just written. The user's `.zshrc`
  PATH entry for routines is theirs to change, not this repo's.
- **`routines` needs an in-process self-watchdog** for the same reason as P2.6.
- **antiknob** shares the tray-icon question (fixed the same way, 2026-10-05) and
  keeps its own plan in its `PLAN.md`.

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

**Shipped, by release:** `CHANGELOG.md`; the release table this file carried
until 2026-10-14 is `git show a8a848d:docs/ROADMAP.md`.

---

## Sources consolidated (2026-10-12)

Every agent session that ever worked on this repo was read and given a
disposition on 2026-10-12, then removed; nothing in them is open beyond the
items above. The table (opencode loop, Antigravity, Gemini CLI, Claude
desktop and memory, the landed worktree, the cross-project plans) is
`git show a8a848d:docs/ROADMAP.md`.
