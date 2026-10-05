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

Premises were last checked against the code on **2026-10-05** (commit
`6a0ea79`), item by item, with file:line evidence; the evidence column of each
item is what that audit found.

---

## Plan

### Phase 0 — correctness defects and drift (small, independent)

#### P0.1 — One brightness change sends two `set_brightness` calls
**Status:** OPEN
**Why:** two listeners sit on the same slider: `divoom_gui/web_ui/spatial_stage.js`
sends on every `input` event and `divoom_gui/web_ui/app_init.js` sends again on
`change`. Every drag ends with a duplicate device write, and the two paths
disagree about which panel they mean (neither passes a mac).
**Done when:** one slider gesture produces one device call per value, pinned by
a browser test that counts calls (watched failing on today's code).

#### P0.2 — PyInstaller is unpinned, so a release build takes whatever is newest
**Status:** OPEN
**Why:** `scripts/build_release.sh` runs a bare `pip install pyinstaller`. The
previous roadmap said 6.21.0 -> 6.22.3 was "deliberately not taken"; in fact
nothing holds it, and the next clean build changes the bundle silently.
**Done when:** the build installs a pinned version from a committed file, and
moving it is its own commit carrying a bundle diff (file list + sizes).

#### P0.3 — CI comments still describe the menubar's `tao` era
**Status:** OPEN
**Why:** `.github/workflows/tests.yml` (the `rust-ble` job, about lines 251 and
259) says the menubar needs system packages no Linux runner ships; the lock has
no `tao` since 2026-09-20 and the menubar is on winit plus a target-gated
`ksni`. A wrong comment next to a CI job decides what the next person skips.
**Done when:** the comments name the real dependency, and the system-packages
claim is either proven by a Linux build or deleted.

#### P0.4 — The Python coverage floor dropped and was never ratcheted back
**Status:** OPEN
**Why:** `scripts/py_ci.sh` enforces 88.5 (lowered in v0.35.4 at a measured
88.74). A floor that only moves down stops protecting anything.
**Done when:** the floor equals the current measurement rounded down to 0.1, and
the script says when and at what value it was last measured.

#### P0.5 — `tests/` and `examples/tests/` cannot be collected in one run
**Status:** OPEN
**Why:** `examples/tests/conftest.py` re-exports `tests/conftest.py` with a star
import, so `pytest_addoption` registers `--run-hardware` twice and pytest aborts
before collecting. CI runs the two separately (`scripts/py_ci.sh`), so this
bites only a person running both -- but the error names an option, not the cause.
**Done when:** `python3 -m pytest tests examples/tests --collect-only` succeeds.

### Phase 1 — daemon liveness and safety

#### P1.1 — The socket's access rule comes from the umask, not the code
**Status:** OPEN
**Why:** `divoomd/src/socket_bind.rs` binds `/tmp/divoom.sock` and never sets a
mode; it is owner-only today (`srwxr-xr-x`) only because the umask is 022. A
daemon started under a looser umask would accept any local user, and the unix
socket path has no token check (`require_auth=false` in
`divoomd/src/socket_server.rs`).
**Done when:** the socket is created owner-only explicitly (mode or a 0700
parent directory), and a test binds under umask 000 and asserts the mode.

#### P1.2 — `get_status` cannot say who is connected
**Status:** OPEN
**Why:** the 2026-09-07 wedge (64 subscriptions) is now impossible by
construction, but its CAUSE was never found because killing the daemon
destroyed the evidence. `get_status` (`divoomd/src/daemon/dispatch.rs`) reports
no connection counts; the semaphore and the registry's `len()` are never read.
**Done when:** `get_status` returns connections by kind (request, subscription)
with ages, and a test opens N of each and reads them back.

#### P1.3 — A slow command holds its connection with no deadline
**Status:** OPEN
**Why:** `handler.handle(req).await` in `divoomd/src/socket_server.rs` has no
timeout and does not read the socket while it runs, so a peer that hangs up is
invisible. `device_call` bounds itself; cloud calls, `sync_artwork` and
`render_widget` do not.
**Done when:** every command runs under a deadline (per-command where needed),
and a test with a stalled handler sees the connection released.
**Depends on:** P1.2

#### P1.4 — A reconnecting subscriber cannot replace its own slot
**Status:** OPEN
**Why:** `divoomd/src/subscriptions.rs` keys entries by a counter, not a client
identity, so a client that crashed and reconnected is a stranger: admitted only
if the oldest slot has been quiet for 600 s, otherwise refused. Identity-keyed
takeover should run BEFORE staleness eviction (MQTT 5.0 reason 0x8E).
**Done when:** a subscribe that names an identity replaces that identity's
entry immediately, pinned by a test that fills the registry and reconnects.

#### P1.5 — Status fan-out drops events instead of keeping the latest
**Status:** OPEN
**Why:** subscribers share a `broadcast::channel(32)` (`divoomd/src/daemon.rs`);
a lagging one is told and dropped past 64 lost events
(`divoomd/src/socket_server/pump.rs`). A status subscriber wants the CURRENT
truth, so conflation (latest value per key) is the method of record, not a
lossy ring.
**Done when:** a slow subscriber receives the latest state for every key it
missed rather than a hole or a disconnect, under a test that stalls one reader.

#### P1.6 — Nothing notices the daemon has stopped serving
**Status:** OPEN
**Why:** launchd has no watchdog (verified as an absence), and the protocol has
no heartbeat -- only a client-sent `ping`. A wedge detector on macOS has to live
in-process and be pinged from INSIDE the serving loop; a side-channel check is
exactly the gray-failure blind spot.
**Done when:** a stalled serving loop is detected and reported (log + exit for
relaunch) within a stated bound, proven by a test that wedges the loop.
**Depends on:** P1.2

#### P1.7 — The panel does not always come back after a daemon restart
**Status:** OPEN
**Why:** seen repeatedly on 2026-09-07: `scan` times out while `connect` with
the saved identifier succeeds at once. Unexplained; it costs every hardware
round time, and nobody knows whether normal use (no restarts) is affected.
**Done when:** a BLE trace (`DIVOOMD_BLE_DEBUG`) of one failing restart is
captured and the cause named, or the reconnect path uses the saved identifier
first and the symptom is gone.

### Phase 2 — the daemon knows what each panel is

#### P2.1 — `device_status` carries model and panel resolution
**Status:** OPEN
**Why:** `divoomd/src/daemon_status.rs` reports link state per mac and nothing
about the panel itself, so every client (MCP, GUI, menubar) guesses size. It is
the root of P3.1-P3.3.
**Done when:** each device entry has `model`, `width`, `height` (and battery
where the device reports one), with a test per supported model class.

#### P2.2 — Typed error codes on device failures
**Status:** OPEN
**Why:** a push to an unlinked panel fails at once but as prose
(`device '{id}' not connected`); `err_reply` in `divoomd/src/protocol.rs` carries
only `success` and `error`. Clients cannot branch on prose without making
wording load-bearing -- the class `divoomd/src/ble_fault.rs` was written to end.
**Done when:** errors carry a stable `code` (`DEVICE_DISCONNECTED`, ...) beside
the message, and clients branch on the code.

#### P2.3 — Weather is drawn by the firmware, not by us
**Status:** OPEN
**Why:** `push_weather` (`divoomd/src/live_jobs/mod.rs`) configures the device's
own clock face (0x5F data + a ClockPacket) and inherits its cycling and panel
semantics; that is why weather was the only widget that broke. Every other
widget renders frames (`divoomd/src/render_widget.rs` `KINDS` = sysmon, stocks,
album_art, text). Rendering weather also makes it the first consumer of the
custom-image path Phase 3 exposes.
**Done when:** `weather` is a `render_widget` kind drawn with
`divoomd/src/live_jobs/render.rs` and `divoomd/src/live_jobs/font.rs`, the weather job
pushes frames, and the device's own face is no longer selected.

### Phase 3 — MCP as a display surface

Goal: an external agent can discover each panel, draw on it at its real
resolution, and share it with background jobs without collisions. Today
`divoomd/src/mcp_tools.rs` has 14 tools.

#### P3.1 — `get_capabilities` describes the panel
**Status:** OPEN
**Why:** it forwards `device_status`, so it returns link state only -- no size,
model, battery or feature flags (speaker, radio, clock).
**Done when:** it returns what P2.1 provides plus feature flags from one table.
**Depends on:** P2.1

#### P3.2 — `list_screens` derives resolution and live status
**Status:** OPEN
**Why:** it forwards `get_topology`: stored names and x/y, `current_device`, no
resolution and no per-panel connection state.
**Done when:** each screen entry carries resolution and live link state.
**Depends on:** P2.1

#### P3.3 — `show_image` draws at the panel's size, with a stated policy
**Status:** OPEN
**Why:** `push_image_bytes` always resizes to 16x16 ("Device size is 16 for
now"), so a 64x64 panel gets a quarter of its pixels.
**Done when:** the tool takes a resize policy (`fit`, `fill`, `exact`, `none`),
sizes to the target panel, and `none` with the wrong size is a clear error.
**Depends on:** P2.1

#### P3.4 — `push_animation` streams every frame
**Status:** OPEN
**Why:** it pushes the first frame and says so ("full animation streaming is a
follow-up").
**Done when:** multi-frame animations play on the panel, frame timing honoured.
**Depends on:** P3.3

#### P3.5 — Text, live jobs and the built-in tools over MCP
**Status:** OPEN
**Why:** the daemon already has `render_widget` text, `live_job_start/stop/list`,
and `scoreboard.set_scoreboard` / `timer.set_timer` /
`countdown.set_countdown`; none is an MCP tool, so an agent has to speak the raw
socket for them.
**Done when:** each is an MCP tool generated from the same registry as the
others, with the arguments' bounds shared rather than restated.

#### P3.6 — Screen leases, so agents and background jobs do not collide
**Status:** OPEN
**Why:** the nearest thing is `exclusive_start`/`exclusive_end` on the command
queue. An agent drawing on a panel while sysmon runs gets overwritten, and a
crashed agent leaves a stale frame forever.
**Done when:** a caller acquires a lease with a mandatory TTL and renewal; on
expiry the panel returns to what it showed before; continuous pushes for one
panel are conflated (latest frame wins) on slow links.
**Depends on:** P1.5, P3.3

#### P3.7 — Transient notifications as a tool
**Status:** OPEN
**Why:** no MCP tool shows an alert and then gives the panel back.
**Done when:** a notification tool shows for a bounded time and restores the
previous content, using the lease from P3.6.
**Depends on:** P3.6

### Phase 4 — the GUI models each panel, not "the" panel

#### P4.1 — Connection, brightness and volume are per panel
**Status:** OPEN
**Why:** `window.DivoomState.appConnected` (`divoom_gui/web_ui/app_globals.js`)
is one boolean and still gates brightness and volume; `set_brightness` and
`set_volume` take no mac and are read once at startup; per-panel brightness is
only a memory of what the slider last sent. The per-device rule below says
every per-panel fact has one owner -- the daemon -- and these do not.
**Done when:** the GUI reads and writes these per mac through the daemon, and
switching panels shows that panel's values (browser test across two panels).
**Depends on:** P2.1

#### P4.2 — Channel settings are written per display
**Status:** OPEN
**Why:** `syncChannelControlsToDisplay` (`divoom_gui/web_ui/channel_preview.js`)
fixed the READ side, but the write path still uses globals
(`divoom_gui/web_ui/channels_grids.js`, `divoom_gui/web_ui/channels_core.js`),
`DisplayPreviewRegistry.getActive()` has no callers, and a colour input keeps
the previous display's value when the new one is on another channel.
**Done when:** every channel control writes to the selected display's state,
and changing display A's clock style leaves B's untouched (browser test).

#### P4.3 — The menubar updates rows in place
**Status:** OPEN
**Why:** any change of rows, names, kinds or the active panel rebuilds the root
`Menu` (`divoom-menubar/src/tray.rs`), which dismisses it if it is open; only
row icons update in place.
**Done when:** labels and the "Active panel" check update in place; a rebuild
happens only when the set of rows changes.

### Phase 5 — the multi-panel wall

#### P5.1 — Snap adjacent panels into one surface
**Status:** OPEN
**Why:** slicing an image across a wall already works (`divoomd/src/wall.rs`
cuts per slot by x/y), but placing panels is free-form: dragging only clamps to
the bench, and "Align" lays everything in one row. LAN panels are refused for
wall images.
**Done when:** dragged panels snap edge-to-edge into a contiguous group, and a
LAN panel can be a wall slot (or the refusal is shown in the UI with its reason).

### Phase 6 — decisions for the owner

#### P6.1 — The tray glyph tells states apart by colour alone
**Status:** DECISION (owner)
**Why:** Offline / Online / Error differ only in fill (grey / green / red); green
vs red is the pair about 1 in 12 men cannot separate (house rule: colour
reinforces, shape carries). Also, the `#F5F5F5` border is invisible on a light
menu bar at every size, so there the glyph is only its fill.
**Done when:** the owner picks a design (e.g. hollow Offline, barred Error) and
the states differ in greyscale on `tools/render_tray_icon.py` sheets.

### Phase 9 — parked on something outside this repo

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
**Why:** winit 0.30 pins `objc2` 0.5.2; everything else is on 0.6.4. No type
crosses between them, so it costs build time only.
**Done when:** a stable winit on `objc2` 0.6 is taken and the lock holds one.

#### P9.5 — Python majors that cannot be taken yet
**Status:** WATCH
**Why:** `multidict` 7 (aiohttp caps <7), `pyee` 14 (playwright caps <14) and
`playwright` 1.63 (camoufox 0.5.5 caps <1.61) are unreachable, not declined.
**Done when:** each parent widens its cap and the major moves in its own commit.

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
| Python coverage floor | 88.5 (see P0.4) | `scripts/py_ci.sh` |
| Rust coverage floor | 42 | `scripts/rust_coverage.sh` |
| File length | 500 lines, allowlist empty | gates_of_heck structural layer |
| Daemon/client duplication | 0 DIRECT, 0 WRAPPED | `tools/capability_census.py` |

**Flake ledger** (one line each; a repeat earns an investigation):
- 2026-09-13, full gate at load ~20: `socket_bind::tests::clears_a_stale_socket`
  saw `UnresponsiveListener` (a connect to a dropped listener's file succeeded,
  then silence). 5/5 green alone.

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
- **`routines` needs an in-process self-watchdog** for the same reason as P1.6.
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

**Shipped, by release** (detail in `CHANGELOG.md`; older rounds R3-R67 in
`git log -p -- docs/ROADMAP.md`):

| Release | Date | Theme |
|---|---|---|
| Unreleased | 2026-10-05 | tray glyph back to 18pt at 2x; memory-gauge harness and v0.41.0 correction; handoff folded into this file; roadmap rephased and gated |
| v0.41.0 | 2026-10-05 | every dependency current; the gates that were lying about it |
| v0.40.0 | 2026-09-25 | the device stack is Rust; C encoder chain and Python MCP retired |
| v0.39.0 | 2026-09-21 | MCP negotiation, Python 3.14 floor, menubar off tao |
| v0.38.0 | 2026-09-14 | the direct-to-device library retired to `examples/` |
| v0.37.0 | 2026-09-12 | active panel, Keychain, Now Playing per client, CLI as a daemon client |
| v0.36.0 | 2026-09-12 | one struct per panel; six user-reported defects; prompt-free rebuilds |
| v0.35.0-v0.35.4 | 2026-09-11/12 | spatial stage, per-display previews, virtual wall, queue serialization |
| v0.34.0 | 2026-09-07 | the invisible weather widget, and a harness that could not have found it |
| v0.30.0-v0.33.0 | 2026-08-31/09-07 | gates made real; unreachable daemon fixed; residuals |
| v0.28.0-v0.29.0 | 2026-08-30 | version parity structural; the GUI is a client |
