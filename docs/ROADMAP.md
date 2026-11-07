# Roadmap — divoom-control

The ONE forward-looking document (`AGENTS.md`). It holds what is not done yet,
in the order it should be done, the owner's rulings, and the standing rules new
work must respect. What shipped is in `CHANGELOG.md`. Closed narrative --
every "Landed" paragraph, the Phase 0-6 histories and the release table -- is
in git history: the last full version before the 2026-11-07 rework is
`git show 1c13851:docs/ROADMAP.md`, and the one before the 2026-10-14
rephase is `git show a8a848d:docs/ROADMAP.md`.

**How to read the Plan.** Stages run in EXECUTION order: Stage 1 is what an
agent can do now, top to bottom; the stages after it wait on something
outside the agent's hands, and each names what. An item's id (`P<n>.<m>`) is
kept from the phase that opened it, so commits and the umbrella queue that
cite it still resolve; the stage it sits in is where it is worked. Statuses:

| Status | Meaning |
|---|---|
| `OPEN` | Ready to work. |
| `BLOCKED (on X)` | Cannot move until X changes; X is named. |
| `DECISION (owner)` | Needs the owner's call before any code. |
| `WATCH` | Nothing to do until an outside event; the trigger is named. |

`tests/test_roadmap_shape.py` enforces that shape: every item has a status and a
**Done when**, no dependency points at a later phase id, and every repo path
cited anywhere in this file exists. Shipped items are deleted from the Plan, not
marked SHIPPED -- that marker is refused.

**Premises checked 2026-11-07** at `593408f` (local main, one commit ahead of
`origin/main` at `6372678`): the newest tag is `v0.45.0`, the installed app
reports `0.45.0`, and the Homebrew cask is `0.45.0` (tap `f001d4b`). Every
item below was re-read against that tree; the evidence for each change is in
the commit that made this rework.

**Umbrella queue ids** (`~/Projects/ROADMAP-consolidated.md`) that map here:
D3 -> P5.16; D7 -> P6.1; D8 -> P6.2; OW.46 -> P4.8; RS.DV -> P1.25;
WG.5 and WG.7 -> P9.12; WG.LIGHTDARK -> P9.13.

---

## Plan

### Stage 1 — agent-runnable, in execution order

**Goal:** main green in CI, the dependency graph current, and the per-panel
model finished. **Exit:** every Stage 1 item deleted. The divoom gate runs 8
camoufox browsers (~8 GB): run it once per landing, never in a loop.

#### P1.22 — CI's browser step is red on main since v0.45.0 (D.CIB85)
**Status:** OPEN
**Why:** the `tests` job failed on the `v0.45.0` tag (run 42158445750) and on
main at `6372678` (run 42158513910): 5 failed, 2364 passed, 222 skipped. All
five die before a page opens, inside camoufox's fingerprint generator:
`launch_options` (`tests/support/browser_options.py:64`) ->
fpgen's `unpacker.lookup_value_list` -> `base64.b85decode` ->
`binascii.Error: Incomplete Base85 group` (one, the host-OS test, as the
subprocess's exit status 1). The same five pass on this machine
(2026-11-07, `--run-browser`, 5 passed) with the SAME camoufox 0.5.9, fpgen
1.3.0 and Python 3.15 -- so the difference is the fingerprint DATA fpgen
holds, which CI fetches fresh on every run and this machine has cached. That
is the shape the local gate cannot see: the dev machine's cache masks a
broken fresh install. The release was cut over a red CI.
**Done when:** a fresh-cache run reproduces it locally (fpgen's data
directory pointed at an empty temp dir) and is watched red; the cause is
fixed or the data pinned the way `.camoufox-build` pins the browser; the
local gate runs the browser suites on a fresh fpgen cache so the class
cannot hide again; and CI's `tests` job is green on main.

#### P1.23 — The dependency graph is current
**Status:** OPEN
**Why:** measured 2026-11-07 (`cargo update --dry-run --verbose`): 64
compatible updates are waiting in `Cargo.lock` (among them btleplug 0.13.5,
bluez-async 0.9.0, ksni 0.3.7, aws-lc-sys 0.47.0), and three DIRECT majors
are behind in `divoomd/Cargo.toml`: `color_quant` 1.1 -> 2.0, `rusqlite`
0.40 -> 0.41, `sysinfo` 0.39 -> 0.40. On the Python side camoufox 0.5.9
allows `playwright` <1.63 and 1.62.0 is out, while 1.60.0 is installed. House
rule: the newest release, each major in its own commit.
**Done when:** the lock is refreshed in one commit; each of the three majors
moves in its own commit (`sysinfo` re-derived with
`tools/mem_gauge_compare.py`, per the standing rule on what a number MEANS);
`playwright` is on the newest version camoufox allows, with the browser
suites run against it; `cargo update --dry-run --verbose` prints no
`Unchanged` line except the ones P9.11 and P9.4 name.

#### P1.24 — The export-keep fix is observed proven on an unchanged tree
**Status:** OPEN
**Why:** P1.17 (`42e3dc4`, 2026-11-01) stopped `GOH_EXPORT_KEEP` naming
`target/debug/divoomd`, so the six steps that rebuilt it can be recorded as
proven (`tests/test_export_keeps_no_build_output.py`). goh's half -- the
proven cache honouring the artifacts a step declares -- landed in goh
`1c2f9a6`. Nobody has yet seen a second `tools/gate.sh --full` on an
unchanged tree report those steps proven.
**Done when:** two back-to-back `tools/gate.sh --full` runs on one tree, the
second reporting the daemon-building steps proven (and skipped), are cited
here, or the step that is not is named and fixed.

#### P5.11 — Every art listing is per panel, like the gallery (D14 follow-up)
**Status:** OPEN
**Why:** D14 made `fetch_gallery` list by the named panel's size and refuse
pixel art not drawn for the panel (`art_not_native`), but four other listings
still answer with no panel and no size: `get_category_file_list`,
`get_dial_list`, `get_my_playlists`/`get_playlist_images` and
`get_aid_sleep_list` (re-checked 2026-11-07: `get_category_file_list(classify,
limit)` still takes no mac; `divoomd/src/daemon/dispatch.rs`,
`divoomd/src/cloud_cmds.rs`). A GUI or MCP client can list art from them that
the panel would then refuse, or a playlist the panel would play scaled. Which
of them carry a per-item size (the gallery's `FileSize`), and which are
already per device type on the cloud's side, is not yet measured.
**Done when:** each listing either takes `mac` and lists only what that panel
shows natively (the reply counting what it left out, as `fetch_gallery`'s
`not_native` does), or is recorded here as device-type-scoped by the cloud
with the evidence; a mock-panel test per command, 16x16 and 64x64.

#### P1.25 — The protocol core and the CLI in Rust (umbrella RS.DV)
**Status:** OPEN
**Why:** the owner put it on the roadmap ("add 1-5, 7 to the roadmap. old
phones runs once per device, speed is not an issue"): packet framing,
escaping, the 16-bit LSB checksum, frame timing and the daemon IPC client
still have Python copies in `divoom_lib` and `divoom_client` on the
hardware and CLI paths. It must keep the standing rule below that Python is
the WIRE FORMAT oracle until the Rust is byte-equal on recorded frames, and
the one structural exception: macOS Classic SPP is unreachable from Rust, so
`divoom_client/spp_bridge.py` stays until that changes. Largest item here;
it goes last in this stage and is split into its own lanes when started.
**Done when:** packet framing, escaping, checksums, frame timing and the
daemon IPC client live in Rust (`divoomd` or a `divoom-cli` crate),
byte-equal to the Python on recorded frames, with no Python left on the
hardware or CLI path except the SPP co-process; released and installed.

### Stage 2 — owner-gated (the owner's hands, eyes or call)

#### P5.16 — The menubar's menu held open through a fleet change, on screen (umbrella D3)
**Status:** BLOCKED (on a session that may take the screen)
**Why:** P5.3 updates rows in place and rebuilds only when the set of rows
changes (`divoom-menubar/src/menu_model.rs`); the model half is unit-tested
and the live model is confirmed through the status item's AX help text. Since
D.MENULIVE/D.MENUEVENT (v0.44.0) an open menu refreshes from the daemon's
event stream through a tracking-mode run-loop source
(`divoom-menubar/src/menu_live.rs`, unit-tested). What no agent has seen is
the NSMenu itself staying open while a row renames: on 2026-11-01 full-screen
control was refused ("user interrupt") and `AXPress` on the status item opens
no menu, so there is no route from a session that must leave the owner's
screen alone. The owner's ruling for this queue: "automate everything you
can" -- this is the part that cannot be.
**Done when:** the menu is held open (a real click) while `select_device`
moves the active panel and a row renames over the socket, and two captures
show the check and the name change in the open menu with no close/reopen,
light and dark; or the defects found are filed.

#### P6.1 — Snap adjacent panels into one surface: the hardware check (umbrella D7)
**Status:** BLOCKED (on a photograph of the two real panels; the machine half is done)
**Why:** the snapping and the LAN refusal are tested in the browser and the
daemon (`divoom_gui/web_ui/spatial_snap.js`, `tests/test_e2e_bench_snap.py`),
and on 2026-10-20 the daemon's cut was CONFIRMED exact on Pixoo-1 +
Timoo-light-4 (grid and free-form layouts, 0 of 256 pixels off per half). What
is left is the glass: the bench geometry is chassis-based (`getWallSlots` in
`divoom_gui/web_ui/spatial_rooms.js` uses `enc.w_mm * 0.65`) while the visible
screen square is inset, so the picture ON the panels is discontinuous by the
bezel width -- measured 21 bench px for Pixoo + Timoo. No camera here sees the
two panels; four panels are present at the bench.
**Done when:** two real panels dragged edge to edge on the bench show one
image across the seam with no gap, overlap or step (photographed), or the
error is measured and the slot geometry corrected.

#### P6.2 — A panel on Wi-Fi as a wall slot (umbrella D8)
**Status:** BLOCKED (on a LAN panel bound to the account; the upload path is KNOWN)
**Why:** the daemon cannot draw an image on a LAN panel at all (a LAN
transport has no `send_command` or `stream_animation_8b`;
`divoomd/src/device_call/lan.rs` has no image command), and the refusal is
stated (`divoomd/src/wall/refusal.rs`). The request shape is known from the
APK: `DesignSendModel.sendByLocalHttp` -> `Draw/PixelLocalHttp`, a multipart
POST to `http://<DevicePrivateIP>:9000/upload`, plus `Draw/EqLocalHttp`;
`DrawPixelLocalHttpRequest` carries fileName, imageName, flag, authorId,
nickName, headFileId, headFileName, lcdIndex and soundFileName. The blocker
(measured 2026-10-20): the account (user_id 401414409) lists no device
(`Device/GetListV2` and `Device/GetList` both `DeviceList: []`) and port 9000
is closed on the LAN. The Timoo and the Tivoo-Max are the Wi-Fi models; one
of them bound to the account unblocks it.
**Done when:** a Wi-Fi image command is written against the smali's own
`Draw/PixelLocalHttp` shape (or the public HTTP API's `Draw/SendHttpGif`
checked on a real LAN panel), the daemon draws a slot over it, and the
refusal is deleted.

#### P5.14 — One hot-channel pipeline? (U.5 follow-up)
**Status:** DECISION (owner)
**Why:** the Auto-Sync switch (the daily schedule) stores the cloud's
Recommend gallery (classify 18) on each panel, while Sync Now beside it and
the Hot tab's button run the panel's own Hot pull -- two contents under one
card. Since U.5 the verdict line says which path ran ("by the schedule", "by
Sync Now"), so the difference is visible, not solved.
**Done when:** the owner has picked one pipeline for all three paths (the
panel's Hot pull, or the stored Recommend push) or kept both, recorded here
with the date.

#### P9.13 — Each widget follows light and dark and magnetises to the Dock (umbrella WG.LIGHTDARK)
**Status:** DECISION (owner)
**Why:** the owner asked for it on the roadmaps and NOT built now: "it should
be possible to magnetize the spaces to the dock. routines mascot (and all the
other widgets) should respect light/ dark mode, and should be able to
magnetize to the dock as well. do not implement now, just add to the
roadmaps". The umbrella holds it behind OW.86 ("Say go when you want them
built") and ZoneWM's ZW.DOCKMAG; divoom's widget is P9.12's.
**Done when:** the owner says go, and then: a both-appearance render test of
the divoom preview widget watched red first, and the installed widget read
in Light and Dark docked to the SpaceBar and to the Dock.

### Stage 3 — hardware-gated (a panel, a capture, or a trace)

#### P4.8 — Phase 4's hardware half: a 64x64 Bluetooth panel runs the lease (umbrella OW.46)
**Status:** BLOCKED (on a 64x64 panel linked over Bluetooth or SPP; the bench's four are 16x16)
**Why:** Phase 4's exit is green against the real `divoomd mcp` entry point
with a mock 64x64 panel (`divoomd/tests/mcp_lease_e2e.rs` decodes the 0x8B
stream: two 4096-pixel frames, red then blue, then the widget's own 64x64
frame after the lapse). A REAL 64x64 panel has never drawn a full-resolution
multi-frame image through this path. The owner's step is one command:
`scripts/hw_verify.py --only mcp_lease` with a 64x64 panel selected
(`scripts/hw_mcp_lease.py`; it ends UNKNOWN, never PASS, when nobody looked:
`tests/test_hw_mcp_lease.py`). Two things the run settles besides the glass:
(1) the panel must be on Bluetooth or SPP -- a Wi-Fi-only Pixoo-64 cannot run
it until P6.2's LAN image command exists, and the check SKIPs saying so; (2)
the one-`AA`-frame 4096-pixel encoding the daemon streams has never been
accepted by a 64x64 panel (the cloud's own 64x64 art is the tiled magic-26
format, `divoomd/src/art_codec/iframe.rs`), so a panel that shows nothing is
that finding, not the lease's.
**Done when:** `scripts/hw_verify.py --only mcp_lease` on a Bluetooth-linked
64x64 panel records PASS and a camera frame shows the multi-frame draw; or
this item records why no 64x64 Bluetooth panel is in view.

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

#### P9.6 — The June 2026 hardware deferrals, re-checked on the Rust daemon
**Status:** BLOCKED (on a hardware session with an SPP panel and the 4-panel rig)
**Why:** three items from the June 2026 adversarial review (Python era) were
never re-checked after the port: (a) SPP framing vs BLE (escaping, packet
number, write pacing, response-timeout clearing) now that
`divoom_client/spp_bridge.py` carries bytes the daemon frames; (b) a 0x8B
retransmit request arriving in the re-arm window of the animation stream
(`divoomd/src/ble.rs` phase 3); (c) a custom-art ACK treated as success while
no read-back exists (`divoomd/src/device_call/animation.rs`; P9.10).
**Done when:** each of (a)-(c) has a `DIVOOMD_BLE_DEBUG` trace read with the
A/B rule (Hardware reference below) and is either closed with the trace cited
or becomes its own OPEN item with a reproduction.

#### P9.10 — The stored gallery cannot be READ BACK on this hardware
**Status:** WATCH (the trigger is named: a panel that answers `0x8E`)
**Why:** the push STORES the art in the device's own gallery
(`divoomd/src/gallery_store.rs`, the custom-art page; save `0xB1`, play
`0xBD [0x17, page]`). The write's only proof is the device's ACK: `0x8E`
("App get user define info") timed out on all four of the owner's panels
(measured 2026-10-21), so the read was REMOVED (D.DV1, owner ruling OW.36,
2026-10-31: "drop gallery read, keep local record"). What the device was
given is the app's own record (`hotchannel_fetches.json`,
`hotchannel_state.json`). Re-checked 2026-11-07: with the read gone, nothing
in the daemon asks `0x8E` any more, so this trigger fires only on a NEW panel
model probed by hand.
**Done when:** a panel model answers `0x8E` with the ids of what the push
stored (then the read comes back for that model and the run reports the store
CONFIRMED), or the owner says the art is on the panel and this item is
deleted.

### Stage 4 — time-gated (waits for the data to arrive)

#### P9.9 — The magic-26 family's other frame flags are not read
**Status:** WATCH
**Why:** `divoomd/src/art_codec/iframe.rs` reads the flag-`0x0C` gallery form,
the raw forms (`0x0B`, `0x11`), the 128x128 palette form (`0x12`) and the
quadtree (`0x15`). Two flags in the app's own dispatcher are REFUSED rather
than guessed at: `0x00` (the standard 7-byte `AA` form; the app sizes it from
the picture) and `0x14` (the palette form in the "net" colour order, converted
by `convert_rgb_local_to_net_128`). No gallery file has carried either. The
run prints the frame flag of every file it could not show, so the first
`0x00` or `0x14` is visible in the daemon's log. (A magic-26 animation is
decoded to its first 24 frames, the same bound as magic-9 and magic-18.)
**Done when:** a gallery file carries a flag this decoder refuses, and the
refusal is lifted by reading that flag out of the native library the same way
`0x0C` was -- or the flags are shown never to appear and this item is deleted.

### Stage 5 — upstream-gated (another project must move first)

#### P9.4 — Two `objc2` majors in the lock
**Status:** WATCH
**Why:** winit 0.30 (0.30.13 in the lock) pins `objc2` 0.5 (0.5.3); everything
else is on 0.6 (0.6.5). No type crosses between them, so it costs build time
only. Re-checked 2026-11-07: the newest winit is `0.31.0-beta.4`, not a
stable release.
**Done when:** a stable winit on `objc2` 0.6 is taken and the lock holds one
(`cargo tree -i objc2` prints one version).

#### P9.5 — Python majors that cannot be taken yet
**Status:** WATCH
**Why:** re-checked 2026-11-07: `multidict` 7 (7.2.1 out; aiohttp 3.14.4 caps
<7), `pyee` 14+ (16.0.1 out; playwright 1.60 caps <14) and `playwright` 1.63+
(1.64.1 out; camoufox 0.5.9 caps <1.63) are unreachable, not declined. The
reachable step inside the caps (playwright 1.62) is P1.23's.
**Done when:** each parent widens its cap and the major moves in its own commit.

#### P9.11 — zbus 6 for the Linux tray (`ksni`)
**Status:** WATCH
**Why:** `divoom-menubar/Cargo.toml` builds the Linux tray with tray-icon's
GTK-free `ksni` backend; ksni (0.3.7, the newest) depends on `zbus` 5
(5.19.0 in the lock) while zbus 6 (6.2.1) is out. The umbrella's upstream list
carries it with monitor's `secret-service`.
**Done when:** a ksni release on zbus 6 is taken and `cargo tree -i zbus`
prints one 6.x version.

#### P9.12 — One live preview widget per panel (umbrella WG.5, under WG.7)
**Status:** BLOCKED (on WG.7's design record in ZoneWM: where the shared SpaceBarKit client lives and how a Rust app draws with it)
**Why:** the owner's rulings: "let's add additional routines like desktop
widgets (magnetised box/ system style) - remaining account usage on each of
our sources (claude, opencode, agy, gemini web), bigkoff routine like widget,
ztaxes fire, divoom control preview for each device." (2026-10-25); "The FIRE
widget belongs to Zinc, the divoom devices previews widgets belong to
divoom-control, etc" (2026-10-26); "Correction - each app will have it's own
widget. they are drawable without zonewm. theyll just be system widgets
otherwise, and token-pool will be a widget app" (2026-10-26); "have options
for both" (2026-10-26). The widget draws from divoom-control's own frame
renderer (the same pixels it sends), one per paired device, with no device
writes. WG.7's design is ZoneWM's (the protocol's owner) and comes first;
OW.54 answered 2026-11-02 that a self-signed WidgetKit extension appears in the
macOS 27 widget gallery.
**Done when:** divoom-control draws one live preview widget per paired device
with SpaceBarKit from its own frame renderer, docking when ZoneWM runs and a
system widget otherwise, with no device writes; released and installed.

---

## Decisions not to re-litigate

Each is a ruling or a measured choice; reopening one needs new evidence, not
a new opinion.

- **CI uses the local machine's camoufox version** (owner ruling, 2026-10-19).
  The build is declared once, in `.camoufox-build`, read by CI and by
  `scripts/browser_e2e.sh` through `tools/camoufox_installed.py`.
- **The stored-gallery read is dropped, the local record kept** (owner ruling
  OW.36, 2026-10-31: "drop gallery read, keep local record"). See P9.10.
- **One hot-channel verdict line per panel** (U.5, the owner's pick
  2026-10-31: "A: verdict line (Recommended)"). Option C is P5.14's question.
- **"Automate everything you can"** (owner ruling for queue D3/D5,
  2026-11-01): a hardware or on-screen check is done by machine wherever a
  machine can see it; what is left for the owner is named, as in P5.16.
- **The "monthly best" push is classify 18 (the cloud's Recommend gallery)
  on a 24-hour cadence**, because the content turns over daily: measured
  2026-11-07 over four days, the 10 files a panel gets share nothing with the
  previous day's and are dated anywhere from 2019 to 2026 -- a daily pick,
  not a sliding window (`CHANGELOG.md`, Unreleased; was P9.8).
- **The daemon refuses a panel only on a definite switch, never on an absent
  screen.** The app's home list is its UI, not the protocol (the D-base gets
  an empty list); `MicEnum` is not claimed (it is ON for the plain Pixoo,
  which has no microphone); the chassis table is the products' published
  sizes (Phase 3, 2026-10-22).
- **A lease gives back only a channel that re-selecting restores**: the
  clock (0) and the cloud channel (2); a pushed image gets `restored: "none"`
  and the light channel (1) is not restored, because its one-byte select left
  the panel dark at brightness 0 (`divoomd/src/lease.rs`
  `RESTORABLE_CHANNELS`; P9.7, 2026-11-01).
- **The shared test browser is async-only.** The sync API (`launch_sync`)
  keeps one browser per module or test, because `sync_playwright()` keeps its
  loop registered while a test's `with` block is open (P1.21, 2026-11-02).
- **The startup lock's SOCKET variant is named, not fixed.** A child that
  inherited the listener's descriptor keeps the socket listening
  (`UnresponsiveListener`, `divoomd/src/socket_bind.rs`); its exposure is
  bounded because the daemon unlinks the socket path before it exits (P1.15,
  2026-10-21). New evidence of it in the field reopens it.
- **Gated capabilities are decisions, not gaps** (see Standing rules).

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
still owns the device. (P1.25 moves the rest of the wire to Rust under this
rule: byte-equal first, then the Python goes.)

### Rules that came from shipped bugs

- **A re-render is not a selection.** Anything that runs on every status or scan
  event (`SpatialStage.refresh`, `PanelLevels.show`) repaints; it never moves
  the user's tab, rebuilds the node under a drag, or sets a control the pointer
  holds. Selection side effects belong to the gesture that selects
  (`tests/test_e2e_rerender_keeps_user_state.py` fires the refresh mid-gesture).
- **A test owns the in-flight state it asserts on.** A mock that answers on a
  timer makes "during the call" a window a loaded runner overshoots; hold the
  promise and release it from the test (`tests/test_e2e_ux_feedback.py`).
- **The app's startup never overwrites state it already has** (the persisted
  snapshot over live state, a pending connect's link flag; `0627eb5`).
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
  `tools/camoufox_installed.py` prints (or `--install`).
- **A dependency bump can change what a number MEANS.** sysinfo 0.30 -> 0.39
  changed `used_memory()`'s formula under the same signature; v0.41.0 then
  misread its own measurement. Re-derive with `tools/mem_gauge_compare.py`
  (gated by `tests/test_mem_gauge_parity.py`), and judge visual bumps on
  `tools/render_tray_icon.py` sheets, not on a full live menu bar.
- **A `flock` belongs to the open file description**, so a child that
  inherited the descriptor keeps the lock; release it explicitly
  (`flock(LOCK_UN)` on drop), never by "the last descriptor is gone" (P1.15).
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
connected. `album_art` needs something PLAYING — with no track the music job
has nothing to push, and a dark panel then means "nothing playing", not
"broken". `search_weather_city` is the XFAIL canary (P9.1).

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
"already in progress" while the GUI scans.
`cargo test` rebuilds `target/debug/divoomd` WITH default features, so a
BLE-free build does not stay BLE-free across a test run.

**Reading a trace.** A device ECHOES `basic frame cmd=0xNN` for opcodes its
firmware implements. A silence proves nothing on its own — send a known-good
command (`0x45`) first in the SAME window and compare.

**The bench.** Four 16x16 panels (Pixoo-1, Ditoo-light-2, Tivoo-Max-light-3,
Timoo-light-4) and a calibrated bench webcam that sees the Ditoo; no 64x64
panel and no LAN-bound panel.

---

## Quality baseline

Measured 2026-10-05 unless dated otherwise. These are the numbers a regression
is judged against; when one moves, change it here in the same commit.

| Measure | Value | Where it is enforced |
|---|---|---|
| Local gate | 30 `GOH_CI_STEPS` (incl. the browser suites and CI's Linux `--all-features` lint, 2026-10-20) + `scripts/py_ci.sh` = 31 steps, run by `pre-push` on the pushed commit in a clean worktree | `.gatesrc`, `tools/gate.sh`, `scripts/ci_local.sh` |
| Python tests (default) | 2364 passed, 222 skipped, 5 failed (CI run 42158513910, 2026-11-06; the 5 are P1.22) | `pytest.ini` (`testpaths = tests`) |
| `examples/tests` | 1022 passed, 73 skipped (2026-10-19) | `scripts/py_ci.sh` |
| Browser subset (serial) | 313 passed, 5 min 15 s (2026-11-02, `24ab74e`); CI step 331 s on run 41544702215 | `scripts/browser_e2e.sh` |
| Rust tests | 659 (2026-10-20) | `cargo test --locked` |
| Python coverage floor | 89.0 | `scripts/py_ci.sh` |
| Rust coverage floor | 42 | `scripts/rust_coverage.sh` |
| File length | 500 lines, allowlist empty | gates_of_heck structural layer |
| Process calls | 73 in 53 files, every one declaring its stdin (2026-10-21) | gates_of_heck structural layer (`goh subprocess-stdin`) |
| Daemon/client duplication | 0 DIRECT, 0 WRAPPED | `tools/capability_census.py` |

**Flake ledger** (one line each; a repeat earns an investigation):
- 2026-09-13, full gate at load ~20: `socket_bind::tests::clears_a_stale_socket`
  saw `UnresponsiveListener` (a connect to a dropped listener's file succeeded,
  then silence). 5/5 green alone. (The named variant in Decisions.)
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
- **PATH decides which build of a tool runs, and installers do not check.**
  `app_updates` shows the fix: after copying, ask the binary its identity and
  confirm `command -v` resolves to the copy just written. The user's `.zshrc`
  PATH entry for routines is theirs to change, not this repo's.
- **`routines` needs an in-process self-watchdog** for the same reason as P2.6
  (it has an external one, `routines watch` under launchd, re-checked
  2026-11-07; the in-process half is routines' call).
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
capabilities above. MCP: 26 tools (22 offered unless `--allow-destructive`),
on rmcp.

**Shipped, by release:** `CHANGELOG.md` -- the newest stanza is `v0.45.0`
(2026-11-05: Camoufox 0.5.9 and browser 158.0.1-beta.41).

**Sources consolidated.** Every agent session that worked on this repo was
read and given a disposition on 2026-10-12, then removed; the table is
`git show a8a848d:docs/ROADMAP.md`.
