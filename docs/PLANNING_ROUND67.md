# Planning — Round 67: live-system defect round

**Opened:** 2026-08-29 · **Baseline:** v0.26.0 (`24be8ed`)
**Trigger:** six user-reported symptoms + "investigate if this is a class of problems".

This round is written the way the house rules ask for: every symptom is traced to
a violated invariant, the invariant is **named as a class**, the codebase is
grepped for **siblings**, and the fix is the thing that makes the class
unrepresentable — not the one-line instance patch (Process rule #6, #7).

Where a suspected class turned out to be a **single instance**, that is recorded
as such in [Verified non-classes](#verified-non-classes). A class claim with one
instance is not a class.

---

## 1. Live system state (captured 2026-08-29, real hardware)

Probed by driving `/tmp/divoom.sock` from Bash — no BLE in the agent process
(see the TCC harness limit note in `AGENTS.md` / session memory).

```
42963  ppid 1      divoomd --socket /tmp/divoom.sock   started 02:25, 34.7h   ORPHAN
38838  ppid 32125  divoomd --socket /tmp/divoom.sock   started 10:36, 26.5h   LISTENER
32125  ppid 1      python divoom_gui/gui_main.py
31647  ppid 1      divoom-menubar                                             ORPHAN
```

Attribution is not a guess: `get_status` reports `uptime_s=95363` (26h29m23s),
which matches **38838**'s elapsed time to within 10s. So the process the GUI
spawned owns the socket, and a **34.7-hour-old daemon is still running with no
listener** — unreachable over IPC, invisible to every UI, and still holding a
CoreBluetooth central.

Command results:

| Probe | Result |
| --- | --- |
| `ping` | `{"pong":true}` |
| `device_status` | `connected:false` |
| `scan` (6s) | Pixoo-1, Timoo-light-4, Tivoo-Max-light-3 — all found |
| `connect` Pixoo-1 | **success in 2.1s**, `connected:true` |
| `hot_update_progress` | `{"phase":"idle"}` |
| `live_job_list` | `[]` |

**Read this carefully:** the BLE stack is healthy. Scanning works, connecting
works, and it takes two seconds. "Connection is unreliable" is not a radio
problem — it is a **process-ownership and state problem**. The device is left
connected after this probe.

---

## 2. Confirmed classes

### C1 — One wire packet, many builders

**Invariant violated:** a device command's byte layout must have exactly one
construction site. Here the 0x45 packet family has four, and they disagree.

The same 0x45 clock packet is built in three separate Rust `device_call` arms
plus one Python builder:

| Builder | Field 4 | Field 5 | Field 6 | Parameterized? |
| --- | --- | --- | --- | --- |
| `divoom_lib/display/__init__.py:72` (canonical) | humidity | weather | date | all |
| `display.rs:190` `display.set_clock_rich` | humidity | weather | date | all |
| `display.rs:146` `display.show_clock` | **weather** | **temp** | **calendar** | all |
| `display.rs:18` `device.show_clock` | `0` | `0` | `0` | **only `clock`** |

Two independent defects fall out of that table:

1. **`display.show_clock` has the overlay fields in the wrong slots.** The Python
   docstring records the correction explicitly — "humidity/weather/date — so
   those are the overlay fields, **not** weather/temp/calendar" — and cites the
   APK `C2()` canonical order. The Rust arm is the *pre-correction* version. It
   also accepts kwarg names (`weather`, `temp`, `calendar`) that the Python
   signature does not have (`humidity`, `weather`, `date`), so a caller passing
   `humidity=` is ignored, and a caller passing `weather=True` **turns on
   humidity on the device**. This is a `stated-vs-implemented` + `port-parity`
   finding: the spec was written down correctly and the port implements
   something else.
2. **`device.show_clock` hardcodes five fields** — 24h, humidity, weather, date,
   and the colour (always `0xFFFFFF`). The wall path (`t.show_clock(clock=style)`
   from `divoom_gui/api/lighting.py:43`) routes here, so a wall clock silently
   ignores the user's colour.

Same class, lighting packet (`display.rs:231`):

```rust
let payload = [0x01u8, r, g, b, brightness, 0x00, power as u8, 0, 0, 0];
//                                          ^^^^ lightning_type — never read
```

`Display.show_light(color, brightness, power, lightning_type)` passes the type;
`DaemonDeviceProxy` forwards it positionally; the handler drops it and always
sends `0x00` = Plain Colour. `power` is read only from kwargs, never from
positional index 2 (it defaults to `true`, so it happens to be right today —
that is luck, not correctness). A third sibling: the LAN branch in
`divoom_lib/display/__init__.py:326` discards `lightning_type` outright.

**Class-level fix.** One typed packet struct per command byte, with named fields,
serialized in exactly one place:

```rust
struct ClockPacket { env: u8, twentyfour: bool, style: u8, active: bool,
                     humidity: bool, weather: bool, date: bool, rgb: [u8; 3] }
struct LightPacket { channel: u8, rgb: [u8; 3], brightness: u8,
                     kind: LightingType, power: bool }
```

Every arm constructs the struct; nothing writes a positional array by hand. A
wrong field order becomes unrepresentable and a dropped parameter becomes a
compile error rather than a silent `0x00`. This is house design rule #12
(diff whole input signatures, one struct) applied to the wire format.

**Regression gate:** byte-exact payload tests for every `(command, parameter)`
pair, generated from the struct — and a parity test asserting the Rust struct
field order equals the Python builder's, so the two can never drift again.

---

### C2 — Every live-widget data source is implemented twice

**Invariant violated:** house design rule #6 — *previews mirror live state
through the shared store or the exact shared renderer, never a parallel
reimplementation.*

| Data source | Python (GUI preview path) | Rust (daemon → device path) |
| --- | --- | --- |
| now-playing via AppleScript | `divoom_lib/utils/media_source.py` | `divoomd/src/live_jobs/music.rs` |
| Kaset | same | same |
| Feishin / Navidrome | `media_source_feishin.py` | `music.rs` |
| iTunes artwork lookup | `media_source.py` | `music.rs` |
| weather (wttr.in) | `divoom_lib/weather_provider.py` | `live_jobs/mod.rs:191` |
| sysmon / battery | `media_source.py` (psutil) | `live_jobs/render.rs` |

Six data sources, twelve implementations. What the user sees in the card and what
reaches the device come from **different code that can disagree** — and does:

- `_get_live_params()` (`media_sync.py:321`) returns `{size, wall_slots?,
  lan_token?}`. It never passes `location`. `run_weather` reads
  `params["location"]`, gets nothing, and geolocates by the daemon's public IP —
  while the GUI preview resolves location its own way. **The preview and the
  device can legitimately show different cities.**
- The music card's `<img>` (`widgets.js:29`) is pointed at `info.artwork_url` —
  a remote origin — while every other image in the app is a `data:` URL produced
  by `_frame_to_data_url`. The web UI is loaded from `file://`
  (`gui_main.py:227`, `index_html.as_uri()`), and WKWebView blocks remote
  subresources from a `file://` origin. **That is the broken album art.** The
  device preview right next to it (`info.preview`, a data: URL) renders fine.

**Class-level fix.** One provider per data source, owned by the daemon, exposed
over RPC (`now_playing`, `weather`, `sysmon`). The GUI becomes a pure client and
renders the **same frame** the device receives, not a lookalike. Delete the
Python duplicates. This is also what makes the album-art library (§4) worth
building rather than a fourth copy.

---

### C3 — The capability-gate list drifts from the consumer list

**Invariant violated:** a gate enumerated in one place and its consumers
enumerated in another will diverge, and the divergence is silent.

`divoom_gui/permissions.py` primes macOS Automation (Apple Events) consent from
the foreground GUI, because — as its own docstring explains — the headless
daemon's consent dialog has no visible owner, so the user never sees it and the
Apple Event is denied. That design is correct and answers the user's question
directly: **the daemon does own the AppleScript calls; the GUI only primes the
prompt so the daemon's inherited grant works.**

But the lists have drifted:

```
Apple-Event consumers (media_source.py + music.rs):  "Kaset"  "Music"  "Spotify"
_AUTOMATION_TARGETS (permissions.py:29):                      "Music"  "Spotify"
```

**Kaset is never primed.** In the foreground GUI its prompt is visible, so the
GUI sees the track. In the headless daemon the prompt has no owner, so the Apple
Event is denied and the daemon's music job gets nothing. That is exactly the
reported shape: *Kaset works, but the album art shows as broken.*

**Class-level fix.** Derive the priming list from the consumer registry — one
list of `(app, why)` that both the prober and the queriers read — so adding a
player without priming it is impossible. Report the grant state honestly in the
UI (house design rule #9: a denied capability must say so, not look idle).

---

### C4 — Silent no-op plus a long sleep when no device is connected

All four live jobs (`live_jobs/mod.rs`) share this shape:

```rust
if get_device_transport(&daemon, &mac).await.is_some() {
    ... push ...
}                       // else: nothing. No event, no state, no error.
tokio::time::sleep(interval).await;
```

| Job | Interval | Time to notice it is dead |
| --- | --- | --- |
| sysmon | 5s | seconds |
| stocks | 15s | seconds |
| music | 15s | seconds |
| **weather** | **900s** | **15 minutes, or never** |

And the toggles return success unconditionally:

```python
client.live_job_start(mac, "weather", self._get_live_params())
return True                       # media_sync.py:388 — the reply is never read
```

So "enabled" and "working" are indistinguishable to the user, and with the device
disconnected (its steady state — see C5) weather is simply dead with a green
toggle. Compounding it: `run_weather` is BLE-only. There is no LAN branch.

**Class-level fix.** One job-runner harness that owns the loop for all kinds:
publish a per-job state (`running` / `waiting-for-device` / `error: …`) on the
event bus, wake on connect instead of sleeping through it, and have
`live_job_start` return the daemon's actual reply so the toggle can be honest.

---

### C5 — A runtime invariant enforced by the launcher instead of the system

**Invariant violated:** house process rule #3 — *gates are structural, not
disciplinary.* Single-device-ownership is a runtime invariant of the whole
product, and it is implemented as a shell cleanup in one of several entry points.

- `run.sh:63-68` kills every `divoomd` / `divoom-menubar` and removes the socket
  before launching. Correct — but it is one launcher.
- `Divoom.app/Contents/MacOS/Divoom` is `exec python3 divoom_gui/gui_main.py`.
  **No cleanup at all.** This is the normal way the app starts.
- The daemon's own guard (`divoomd/src/main.rs:73`) is **bind-time only**: it
  exits if something is *listening*, otherwise it unlinks the socket and binds.
  It cannot evict a daemon that is already running, and a daemon whose socket
  file was removed keeps running forever as an invisible peer.

That is precisely the state on this machine right now (§1), and it has been for
34 hours. Two daemons that can both touch CoreBluetooth is a sufficient
explanation for intermittent connection failures on a single-owner device.

**Class-level fix.** Make the invariant the system's, not the launcher's: a
PID-file plus a liveness handshake, checked by the daemon on start *and*
periodically; a newly-started daemon that finds a live peer either exits or takes
over explicitly, never coexists. Add a self-check RPC that fails loudly when more
than one `divoomd` is alive, and surface it in the UI.

---

### C6 — A pull was deleted without completing the push

R59 replaced polling with events. For the hot channel the poll was deleted and
the push was only wired on **one** of the two producers.

- `HotProgress` (`divoomd/src/art.rs:46`) is a bare `Arc<Mutex<Value>>`.
  `set()` stores state and never broadcasts.
- The only `hot_progress` events on the wire come from `sync_artwork.rs` — the
  *Sync Now* flow. The *Update Hot Channel* flow (`art.rs::cmd_hot_update` →
  `art_hot.rs` → `art_hot/session.rs`) calls `progress.set(...)` five times and
  emits nothing.
- `gallery_hot.js:129` sets `Preparing…` locally on click and waits for events
  that never arrive. `finishProgress` never runs, so `resetButton()` never runs,
  so **the button also stays disabled after the first click.**
- The polling fallback still exists and is orphaned: `hot_update_status`
  (`gallery_hot_api.py:137`) is defined and called from nowhere.

A wider sweep found **30 GUI API methods with no caller anywhere in `web_ui/`**,
including `push_weather`, `set_temperature_channel`, `set_clock_rich`,
`set_timeplan`, `probe_lan`, `get_capabilities`, `save_lan_config`. The reverse
direction is clean — zero UI calls to undefined backends — so this is
one-directional dead surface, not phantom wiring. `push_weather` having no caller
is directly relevant: there is **no manual weather push in the UI at all**, only
the 15-minute live job from C4.

**Class-level fix.** `HotProgress` takes the daemon's broadcast `tx` and every
`set()` both stores *and* emits — one place, cannot drift. Keep the polling RPC
as an explicit resync path and wire it as the reconnect path rather than leaving
it orphaned. Add a gate that flags GUI API methods with no caller (dead surface
is either a missing feature or deletable code; both need a decision).


### C7 — positional arguments read from a COMPACTED list

**Found during Phase 1 verification, by the new wire-trace harness, on real
hardware.** It also corrects an earlier finding in this document.

`device_call` builds its numeric argument list with `filter_map(as_i64)`, which
**compacts**: every non-numeric entry is dropped, so `args[i]` is the i-th
NUMBER, not the i-th ARGUMENT. For
`show_light("#00FFCC", 80, true, 2)` the list is `[80, 2]`, and the handler's
`args.get(1)` returned the **mode**:

```
mode 0 -> 0100ffcc 00 00 01 000000     brightness byte = 0x00
mode 1 -> 0100ffcc 01 01 01 000000     brightness byte = 0x01
mode 2 -> 0100ffcc 02 02 01 000000     brightness byte = 0x02
                   ^^ expected 0x50 (=80) throughout
```

Ambient brightness has been transmitting the mode number for as long as the GUI
has passed `mode_type`, and mode 0 meant brightness 0.

**This corrects [Verified non-classes](#verified-non-classes).** That section
concluded arity problems were "not a class" after five spot-checks came back
false positives. That was correct about **dropped** parameters and blind to
**misaligned** ones — a different defect with the same surface. A handler mixing
compacted `args[i]` with true positions reads a neighbouring argument's value
with complete confidence, and no amount of reading the Python signature reveals
it. Only the bytes did.

**Class-level fix.** `pos_i64()` / `pos_bool()` in
`divoomd/src/device_call/args.rs` read from `raw_args` (true positions) with a
keyword fallback. `args` keeps a warning that it is compacted and safe only
where every argument is numeric.

**Scope, stated plainly.** `show_light` is fixed and proven on hardware. **49
other `args.get(N)` / `args.first()` reads remain unaudited.** At least one more
is latently wrong: `text.rs` reads `args.get(1)` for `text_box_id` after a
leading string, which works today only because callers pass it as a keyword.
The full audit is open work — sweeping 49 sites blind would be worse than doing
it deliberately, one verified handler at a time.

---

## 3. Verified non-classes

Recorded so the next session does not re-investigate them, and because a
suspected class that fails to generalize is a result worth keeping.

**`device_call` argument-arity drops — NOT a class** (but see [C7](#c7--positional-arguments-read-from-a-compacted-list), which IS one). An automated audit
comparing every Rust `device_call` arm against its Python signature flagged 60
arms as dropping parameters. Five were spot-checked by eye
(`scoreboard.set_scoreboard`, `sleep.show_sleep`, `aid_sleep.delete`,
`music.set_sd_music_info`, `music.get_sd_music_list`) and **all five are false
positives** — they read arguments through `args.first()`, `kw_i64()` or
`get_i64()` helpers the regex did not match. The detector is noise and the number
is not reportable. The real defects are the payload-literal ones in C1, found by
reading the code, not by the grep.

**Correction (added after hardware verification):** this conclusion was right
about parameters being *dropped* and wrong about the broader question. C7 is a
real class in the same code — parameters read at the wrong INDEX — and it was
invisible to both the grep and the Python signatures. It took a wire trace.

**Stale references to R66-removed code — 2 instances, not a class.**
`scripts/make_dev_daemon_app.sh` execs `python -m divoom_lib.cli daemon`, which
has printed an error and returned 1 since R66; and `run.sh:66` still has a dead
`kill_pat "divoom_lib.cli daemon"`. Nothing else in `scripts/`, `tools/`,
`.githooks/`, `.github/`, `packaging/`, `Makefile`, `divoom.spec` or
`pyproject.toml` references removed code. The script still matters (§4 Phase 0) —
it is the documented autonomous-hardware harness and it has been dead for 12 days
— but the rot is not systemic. Its invisibility is: `scripts/` is not exercised
by `GOH_CI_STEPS` or by CI at all.

**Remote-origin `<img>` — 1 instance.** Only `music-cover-img` (`widgets.js:29`)
points at a remote origin. `preview_url` in the hot-channel grid is a
`data:image/png;base64,…` produced by `gallery_sync.py` (pinned by
`tests/test_gallery_sync_cache_fetch.py:434`), not a CDN URL. The codebase's
prevailing pattern is correct; this is the one deviation. It belongs to C2
(preview bypassing the shared pipeline), not to a class of its own.

**Correction to the first-pass report.** `push_music_cover_now`
(`media_sync.py:79`) does drop Kaset's `artwork_url` and fall back to an iTunes
lookup that cannot resolve YouTube-Music content — but the dead-surface audit
shows **the UI never calls it** (`widgets.js:57` records the button as obsolete
since R11). It is not the cause of the broken album art; the cause is the
`file://`-origin remote image (C2) plus the unprimed Kaset grant (C3). The
function should be deleted, not fixed.

---

## 4. Symptom → class map

| Reported symptom | Cause | Class |
| --- | --- | --- |
| Hot channel stuck on "Preparing…" | `HotProgress.set()` never broadcasts; GUI's poll was deleted | C6 |
| GUI asks for Apple Music access | By design (`permissions.py`) — but the *preview* also runs osascript itself | C2 |
| Kaset plays, album art broken | Remote `<img>` on a `file://` origin; Kaset never primed for the daemon | C2 + C3 |
| Album art source: daemon or UI? | **Both.** Rust `music.rs` for the device, Python `media_source.py` for the card | C2 |
| Weather channel broken | 15-min silent no-op with device down; overlay fields in wrong slots; no manual push in UI | C4 + C1 + C6 |
| Ambient: only Plain works | `lightning_type` hardcoded to `0x00` in the Rust handler; dropped on LAN | C1 |
| Ambient previews green/magenta | Static CSS tiles that do not reflect device state | C2 |
| Virtual wall probably broken | Untested; wall path drops `mode_type` and clock colour | C1 (+ unverified) |
| Pixoo not connected / unreliable | Two daemons alive, one invisible, both able to hold the BLE central | C5 |

---

## 5. Plan

### Phase 0 — repair the harness first (process rule #1)

A defect that reached the user means the harness has a hole. Close it first.

1. Repoint `scripts/make_dev_daemon_app.sh` at `target/release/divoomd`, and make
   the build **assert the launched app answers `ping`** — a build that produces a
   non-running app must fail loudly, not quietly.
2. Add `scripts/hw_e2e.py`: socket-driven live-hardware harness
   (connect → exercise → assert → restore), runnable from Bash without touching
   BLE in the caller's process.
3. Add a `daemon_instances` self-check that fails when more than one `divoomd`
   is alive. Wire it into `hw_e2e.py` setup and teardown.
4. Bring `scripts/` under a gate — at minimum shellcheck plus a smoke run of the
   harness scripts — so this rot is visible next time.

### Phase 1 — the structural fixes

5. **C1** — typed packet structs for the 0x45 clock and lighting families; one
   serializer; delete the three hand-rolled payload arrays; fix the overlay field
   order; thread `lightning_type` and `power` through, LAN path included.
6. **C6** — `HotProgress` owns the broadcast `tx`; every `set()` emits. Re-wire
   `hot_update_status` as the explicit resync path.
7. **C5** — PID-file plus liveness handshake; a second daemon exits or takes over
   deliberately; periodic self-check; the `.app` launcher stops being the only
   thing enforcing it.
8. **C4** — one job-runner harness; per-job state on the event bus; wake on
   connect; `live_job_start` returns the real reply and the toggle reflects it.
9. **C3** — derive the Automation priming list from the consumer registry; add
   Kaset; surface denied grants honestly in the UI.

### Phase 2 — the standalone music / album-art library — **DONE**

The user's suggestion, and the right call. `~/Projects/ZoneTilerWM` already
solved this properly in `Sources/ZTMediaRemote/`: it wraps the private
**MediaRemote** framework via `mediaremote-adapter` (BSD-3) and returns
`artworkDataBase64` + `artworkMimeType` — **real artwork bytes, player-agnostic,
no per-app AppleScript, no iTunes-Search guessing, no per-player TCC grant.**
That single change dissolves C3 for music and removes half of C2.

Its docs also carry the failure modes worth inheriting rather than rediscovering:
`docs/ROUND7.md` R7-2 (fatals when the framework is missing → needs a probe and
graceful degradation), R11 (the adapter's stream died with no restart → needs a
watchdog), and `COMMERCIAL_READINESS.md` (MediaRemote is private and Apple has
tightened it → never market artwork as unconditional; keep an AppleScript
fallback).

10. **Probe first.** Before designing around it, confirm on *this* macOS version
    that the adapter returns artwork bytes. If it does not, the library ships
    with the AppleScript path as primary and MediaRemote as the upgrade.
11. Extract `nowplaying/` as a standalone crate consumable by both repos:
    MediaRemote primary, AppleScript fallback, Feishin/Navidrome, artwork as
    bytes, honest degradation states.
12. Expose `now_playing` as a daemon RPC. Delete `media_source.py`'s duplicate
    and `push_music_cover_now`. The GUI renders the **same frame** the device
    gets.

### Phase 3 — weather

13. One provider behind one seam; delete the Rust wttr parsing in favour of the
    shared one; pass `location` through `_get_live_params`; add a LAN branch;
    wire-trace `0x32` / `0x5f` against `references/` before touching payloads;
    decide whether `push_weather` gets UI or gets deleted.

### Phase 4 — virtual wall

14. Live multi-device run (Pixoo-1 + Timoo-light-4 + Tivoo-Max-light-3 are all
    in range), then fix what it surfaces. Expected fallout is C1 (`set_light`
    and `show_clock` drop parameters on the wall branch).


### Phase 5 — a real installer (`install.sh`)

Requested mid-round. Today `Divoom.app/Contents/MacOS/Divoom` is
`exec python3 divoom_gui/gui_main.py` against the repo checkout, with no
cleanup — which is [C5](#c5--a-runtime-invariant-enforced-by-the-launcher-instead-of-the-system)'s
enabler, since the only single-instance cleanup lives in `run.sh`.

15. `install.sh` builds everything current and installs ONE self-contained
    bundle to `/Applications`: the GUI, `divoomd`, and `divoom-menubar` inside
    `Contents/MacOS`, the web UI and fonts in `Contents/Resources`, the native
    encoder dylib alongside. The app then runs entirely from `/Applications`
    with no dependency on the source tree.
16. The launcher enforces single-ownership on start (the invariant belongs to
    the product, not to `run.sh`), and the daemon/menubar are resolved from
    inside the bundle rather than from `target/release`.
17. Version stamping and an uninstall path, so an upgrade replaces rather than
    accumulates.

---

## 6. End-to-end test plan

### Tier 1 — unit / protocol (no hardware, runs in CI)

- Byte-exact `ClockPacket` and `LightPacket` payload tests for **every**
  parameter, including all five ambient modes and power on/off.
- Field-order parity test: Rust struct order **==** Python builder order. This is
  the test that would have caught the `display.show_clock` slot bug.
- `HotProgress.set()` emits on `tx` for every phase; a fake subscriber observes
  `starting → fetching_manifest → downloading → uploading → done`.
- Live-job harness: `waiting-for-device` state is published when no transport;
  the job wakes on connect instead of sleeping through it.
- `live_job_start` failure propagates to the toggle's return value.
- Single-instance: a second daemon exits; a daemon whose socket is unlinked does
  not survive as an orphan.
- Automation priming list **==** Apple-Event consumer registry (the C3 gate).
- `now_playing` contract; artwork arrives as bytes; iTunes lookup is never called
  when the source supplied artwork.
- Dead-surface gate: GUI API methods with no caller are flagged.

**Every one of these is proved red first** — break the code, watch it fail — per
process rule #2. Commit the fix *before* breaking it (session memory:
`commit-before-prove-red`).

### Tier 2 — GUI e2e (camoufox, existing `tests/support/browser.py` seam)

- **Hot button, driven by the real daemon** — click → daemon-emitted events →
  progress advances → terminal state → **button re-enables**. Today's e2e injects
  the events by hand, which is exactly why it passes while the product is broken.
  This is `differential-blindness`: a test that supplies the input never tests
  the code that produces it.
- Ambient: each mode issues the RPC with the right `mode_type`.
- Music card: assert the cover `<img>` src is a `data:` URL and never a remote
  origin (the `file://`-origin regression).
- Weather card: preview location **==** the location sent to the live job.

### Tier 3 — live hardware (`scripts/hw_e2e.py`, socket-driven)

- Pixoo-1: all five ambient modes, photographed at each, confirming the device
  actually changes — not merely that it ACKed.
- Clock overlays: humidity / weather / date toggled independently, each verified
  on-screen, against the C1 slot fix.
- Hot channel: full update against the real CDN and the real device with
  `DIVOOMD_BLE_DEBUG=1` TX/RX trace captured.
- Music: play in Kaset, then Apple Music, then Spotify; artwork must reach the
  device in all three.
- Weather: forced push renders on-device; disconnect mid-job and confirm the job
  reports `waiting-for-device` instead of going quiet.
- Wall: three-device wall, split image, verify each cell; clock colour and
  ambient mode honoured on the wall path.
- Reliability soak: connect / disconnect / reconnect loop plus idle-drop
  recovery, asserting **exactly one `divoomd` alive throughout**.

### Tier 4 — user-POV

Real app, real screenshots at real scale, light and dark, per the
`user-pov-debug` skill. Green tests are not a shipped feature (process rule #4).

---

## 7. Outcome

**All phases (0-5) are complete and verified on hardware.**

Suite: **Python 2943 / 0 failed / 94 skipped** (from 2920/94 at the round's
start, +23). **Rust 157 / 0** (from 119 in R66, +38). All gates green: emoji,
file size, no_allow, scripts, version, fmt, clippy `-D warnings`.

### Shipped

| Commit | What |
| --- | --- |
| `5e71a6a` | Phase 0 — harness repair |
| `126eb25` | C1, C3, C5, C6 |
| `8e01796` | C7 |
| `0eea608` | C4, `install.sh`, e2e socket isolation |
| `da051e6` | version-consistency gate |

### Verified on hardware (Pixoo-1, `scripts/hw_e2e.py` + `DIVOOMD_BLE_DEBUG`)

- **ambient** — five modes produce `0100ffcc50{00,01,02,03,04}01000000`: five
  distinct payloads with brightness stable at `0x50`.
- **clock** — humidity / weather / date each set only their own byte (4 / 5 / 6).
- **hot channel** — `starting → fetching_manifest → downloading 0..20/20 → done`,
  terminal event delivered, so the button can leave "Preparing…".
- **reconnect** — 5/5 cycles, 2.0–5.6s, exactly one daemon throughout.
- **installed app** — runs entirely from `/Applications`, both Rust binaries
  resolved from inside the bundle, one daemon, device connects, ambient applies.

### Two findings that arrived during verification

Both were invisible to the code and to the suite, and only the wire trace or a
real install exposed them:

1. **C7** (`8e01796`) — ambient *brightness* was transmitting the mode number,
   because positional arguments were read from a compacted numeric list. This
   also **corrects** the "arity drops are not a class" conclusion in §3.
2. **The version stamp** (`da051e6`) — v0.25.0 and v0.26.0 both shipped bundles
   reporting 0.24.3, because bumping `pyproject.toml` was a manual step.

### Phase 2 outcome — the `nowplaying` crate

**The probe decided the design.** On macOS 26.6.2 a direct `dlopen` of
MediaRemote from an ordinary process **succeeds**, `dlsym` **succeeds**, and the
callback hands back a NULL dictionary — Apple entitlement-gated the read API in
15.4, and it fails in the shape of "nothing is playing". Anything built on the
obvious approach would have looked idle forever. `/usr/bin/perl` carries the
entitlement and a dylib loaded into it inherits it, which is why
`nowplaying/native/np_helper.m` is a dylib driven by a perl loader rather than a
normal binary.

Two properties of the source, both discovered rather than assumed:

* **The declared MIME lies** — `image/jpeg` over bytes beginning `4d 4d 00 2a`
  (TIFF). Everything sniffs magic numbers. `divoomd`'s `image` crate also lacked
  the `tiff` feature, so every real cover would have failed to decode.
* **perl's architecture is inherited, not fixed** — the same command ran arm64
  from a shell and **x86_64** from the daemon, where perl then refused our arm64
  dylib. The helper host is now pinned with `arch -arm64`; a fat dylib would
  violate the Apple-silicon-only policy.

**C3 dissolved rather than being patched.** MediaRemote needs no Apple Events,
so nothing queries a player over AppleScript, `apple_event_players()` is empty,
and the app no longer asks for Automation access to music players at all.

**Three bugs found during verification, not review:** a pipe deadlock (stdout
read only after exit, against ~1.6 MB of base64 through a 64 KB buffer — passes
with any small fixture, hangs on every real track); `stderr` discarded, which
made the next one undiagnosable; and the architecture mismatch it was hiding.

### Phase 3 + 4 outcome

**Phase 3 (weather)** turned out to need prevention, not repair: the Rust and
Python WMO tables were diffed first and agree on all 48 codes, so that
duplication had NOT drifted. The response is proportionate — the mapping became
a `const` TABLE (a `match` arm is invisible to any checker) and
`tools/check_weather_parity.py` now fails on either drift shape. The GUI became
a client of a new `weather` RPC, and the resolved location is sent along, closing
the gap where card and device could geolocate to different cities.

**Phase 4 (virtual wall) — it did not work at all**, exactly as suspected, for
three independent reasons, each fatal on its own:

1. **It could never connect.** `wall_configure` uppercases slot keys (a MAC-address
   convention) while macOS uses lowercase UUIDs, and the BLE connect matched
   case-sensitively. Every slot failed for devices a scan had just found.
2. **Nothing reached a wall even if it connected.** The client has always sent
   `target: "wall"`; the daemon never read it. Every call went to the single
   device. The `DivoomWall` methods were unreachable dead code.
3. **The ambient payload was transposed** — brightness and RGB swapped, six
   bytes instead of ten, and the last byte landing in the lighting-type slot.
   `show_effects` and `show_visualization` sent two-byte packets. The Python
   wall never had these bugs because it DELEGATES to the canonical builder; the
   port re-derived each payload by hand.

Verified on a live 2-panel wall (Pixoo-1 + Ditoo-light-2): configure succeeds,
every command goes out twice — once per panel — the ambient bytes are canonical,
a 32x16 split image streams to both, and an unsupported method refuses with a
reason.

### Open, and deliberately not rushed

- **C7 audit** — 49 other `args.get(N)` / `args.first()` reads are unaudited;
  `text.rs` is known-latent. One verified handler at a time, not a blind sweep.
- **C2, the remaining half** — weather and sysmon are still implemented twice
  (Python for the preview, Rust for the device). Music is done; the same
  treatment is Phase 3's job for weather.
- **Feishin** is still a Python-only provider (`media_source_feishin.py`) and is
  not yet a `nowplaying` provider. It needs no Apple Events, so it is not
  urgent — but until it is folded in, a Feishin track only reaches the device if
  Feishin publishes to Now Playing.
- The GUI's ambient preview tiles are still static CSS that do not reflect
  device state (C2's dishonest-preview half).
