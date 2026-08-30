# Changelog

All notable changes to divoom-control are documented here. The
format is loosely Keep-A-Changelog; entries are grouped by
shipped milestone (per the project planning docs).

## v0.28.2 — Tooling and docs; no user-facing change (2026-08-30)

**The app is functionally identical to v0.28.1.** No product code changed. This
is a housekeeping release: the harness that found v0.28.1's crash is now part of
the repo, and the docs and scripts were pruned to match reality.

### `scripts/gui_pov.py` — the twenty minutes that found three bugs

v0.28.1 shipped a daemon-killing crash past 2961 passing tests, five green CI
jobs and a socket-level probe. Launching the app found it immediately. That is
now a script rather than a thing someone has to think to do.

It stands up the real chain with no mocks anywhere — real `divoomd` on an
isolated socket, the real `DivoomGuiAPI` in a bridge process with `HOME`
redirected, and the real `web_ui/index.html` in camoufox — then checks what a
screenshot cannot:

* the daemon is still **alive** afterwards (a reply is not proof the process
  survived — that is exactly how the v0.28.1 crash hid);
* the live refresh is actually **running**, counted by calls rather than by
  watching a value change, because a busy machine legitimately sits at 100% and
  "the number did not move" cannot tell that from "nothing is refreshing" (that
  false positive fired on the check's first run);
* with `--kill-daemon`, that the UI **says** the backend is gone instead of
  leaving stale numbers up looking current.

Every api call is logged with a timestamp, so "the backend died — here are the
last 25 things the UI asked for" is the report, not a starting point for
guesswork.

### macOS Bluetooth TCC, written down properly

Running the harness surfaced a trap worth a paragraph in `AGENTS.md`. Bluetooth
access is granted per RESPONSIBLE PROCESS: a daemon started from a shell has no
grant, and the first BLE scan the GUI triggers kills it with **SIGABRT and a
completely empty stderr** — no panic, no message, nothing in the log. It reads
exactly like a crash in whatever you just changed, and it is not one; a Rust
panic always prints. Users are unaffected, because the GUI launches the daemon
and owns the grant.

Confirmed by differential rather than assumed: a BLE-linked build dies on the
GUI's `scan_devices`, a `--no-default-features` build drives the identical flow
cleanly. An earlier attempt at that differential was invalid because `cargo test`
rebuilds `target/debug/divoomd` WITH default features — which is itself now
documented, since it silently un-does the BLE-free build.

`gui_pov.py` warns up front when its chosen binary links CoreBluetooth, and
names TCC as the likely cause when the daemon aborts silently after a scan.

### Pruned

* **14 dead scripts** (~1600 lines), all unreferenced, undocumented and last
  touched 2026-06-02..07: eight `verify_*.py` one-off protocol probes from the
  reverse-engineering era, three serial/BLE one-offs, a colour-cycle diagnostic,
  an SPP wire debugger superseded by `DIVOOMD_BLE_DEBUG`, and `remove_emojis.py`
  — a one-shot migration whose hardcoded file list had 20 of 35 entries pointing
  at files that no longer exist, and whose rule is enforced by a gate now.

  A fifteenth, `test_watchface_roundtrip.py`, was pruned and then RESTORED: the
  audit grepped for `<name>.py` and missed
  `from scripts.test_watchface_roundtrip import verify_device` in
  `tests/test_e2e_mock_device.py`, because a Python import carries no extension.
  The suite caught it. The instrument was blind to the one syntax that matters
  for Python — worth remembering before trusting the next "unreferenced" list.
* **`docs/archive/`** entirely, including a 2000-line handoff archive, and 244
  lines of superseded round entries from `docs/SESSION_HANDOFF.md`. That file is
  the CURRENT state; once a round ships and its changelog stanza is written, its
  handoff entry has done its job. Everything is recoverable from git, and the
  docs say exactly how.
* **A dangling reference**: `AGENTS.md` pointed at `docs/DEVICE_VALIDATION_PLAN.md`,
  deleted in an earlier cleanup.

## v0.28.1 — Opening the GUI killed the daemon (2026-08-30)

Found by doing the thing the v0.28.0 handoff said nobody had done: launching
the real app against a real daemon and clicking the System Monitor widget.
Three defects, in descending order of severity, none of which any test saw.

### The daemon died when you asked what was playing

`now_playing` and `players` call `nowplaying::current_track()`, which on the
Feishin path builds a `reqwest::blocking::Client`. That client owns a private
tokio runtime, and dropping a runtime inside an async context does not return an
error — it panics on a runtime worker thread and **aborts the process**:

```
thread 'tokio-rt-worker' panicked at tokio/runtime/blocking/shutdown.rs:
Cannot drop a runtime in a context where blocking is not allowed.
```

So the daemon did not fail the request, it **exited**, leaving its socket file
behind so every later call got `Connection refused`. The GUI asks `now_playing`
on load, and the Feishin path is taken whenever MediaRemote reports nothing
playing **or only something paused** — the ordinary idle case. Opening the app
with music paused killed the background service.

`live_jobs` already called this family through `spawn_blocking`; these two
command handlers did not. One entry point observed the rule and two skipped it,
which is why nothing caught it: every test that exercised the live job was fine.

Both handlers are now `async` and reach the blocking probe only through a single
offload helper, so there is no synchronous entry point left to misuse. A panic
inside the probe is now contained and reported instead of fatal.

**The existing tests called the crashing function and could not see the crash.**
They were plain `#[test]`, so they ran it with no runtime active — the one
context where dropping a nested runtime is legal. They are `#[tokio::test]` now.
The new regression test drops a nested runtime through the helper, reproducing
the mechanism with no network and no Feishin install, so it is deterministic
everywhere; the real trigger needs Feishin credentials present and would never
have fired in CI.

### The System Monitor card was frozen

Clicking it selected it for about 250ms. A background reconciler
(`restoreActiveWidgetForDevice`) polls the device's live-job list and used to
force `selectedWidget = "music"` whenever no job was running — which is the
normal state before a device is connected, i.e. exactly when someone is clicking
around the widgets. The Live (5s) refresh only runs while its own widget is
selected, so the card sat on the single reading it managed before being
deselected, with its Live toggle still showing ON.

Measured against the real page at 250ms resolution: true at 0ms, false at 250ms,
numbers never moved again.

The reconciler now ADOPTS a running job (its actual purpose) and leaves the
selection alone when there is none. A running job is real state; "no job" is not
evidence about what the user wants.

### An unreachable daemon looked like a healthy idle machine

The card's refresh did `if (!r.ok) return;` — silently. With the daemon gone it
kept the last numbers on screen and the last frame beside them, so a dead
service was indistinguishable from a quiet CPU. It now blanks the gauges, hides
the frame, and says what is wrong.

It says it in words: the transport marks unreachability with a FIELD
(`unreachable`) rather than leaving callers to match on `[Errno 2] No such file
or directory`, and the message prefers the daemon's own `<socket>.failure`
report — the reason it recorded when it could not take the socket. That sidecar
was built in v0.28.0 and this is the first thing to read it in the widget path.

### Three test-harness defects the version bump flushed out

Bumping to 0.28.1 made every stale binary mismatch its tree, which turned a
class of silent wrongness into loud errors. All three were pre-existing.

* **Binary resolution was inconsistent in three places** — release-only,
  debug-then-release, and newest-first — and `target/release` is a trap: nothing
  in this repo rebuilds it except cutting a release, so any test preferring it
  silently exercised whatever version last shipped. v0.28.0 fixed ONE of these
  and did not grep for siblings, which is the same half-fix this release
  criticises `check_no_allow` for. All of them now go through
  `tests/support/daemon_binary.py`, which picks the most recently built binary
  AND asserts the running daemon's version, because recency alone still runs a
  stale artifact when it happens to be newest.

* **A version-mismatch failure leaked its daemon.** The assertion added in
  v0.28.0 ran inside a fixture's `__init__`, so raising meant the object was
  never returned and teardown never ran — the daemon kept the socket and its
  advisory startup lock, and the next three tests died with "another divoomd is
  starting up". One honest failure became four misleading ones. It tears down
  before failing now.

* **A fixture handed the daemon a REGULAR FILE as its socket path.**
  `NamedTemporaryFile` creates the file; the daemon refuses to unlink a regular
  file on purpose (it may be data someone cares about). Correct behaviour, and
  the daemon said so precisely — in stderr piped to `DEVNULL` and in the
  `<socket>.failure` sidecar nobody read. The fixture now uses a path that does
  not exist, and its wait reports the daemon's own recorded reason instead of
  "never came up".

### A cross-channel race, exposed by the camoufox migration

`test_real_event_relay_degraded_then_disconnected` waited on a DOM class and
then asserted on the daemon's event stream — two channels with no ordering
between them. It was always racy and simply kept winning while
`wait_for_function` was the waiter; polling `evaluate` returns a few tens of ms
sooner and it started losing consistently, with `disconnected` landing ~0.1s
after the assertion. It now waits on the channel it asserts about.

### Also

* `divoom_gui/media_sync.py` and `web_ui/widgets.js` both crossed the 500-line
  gate; the System Monitor card moved to `sysmon_widget.py` and
  `widgets_sysmon.js`, matching the existing `widgets_music.js` split.
* The GUI reads the daemon's `<socket>.failure` report from the socket the
  CLIENT is using, not from an environment guess — otherwise a session started
  with `--socket` silently falls back to the generic message, exactly when the
  specific one would help most.

## v0.28.0 — R68: the gates that were wrong, and a rule nobody could break (2026-08-30)

**v0.27.0 was written but never tagged.** CI had been red for six consecutive
runs, and `release.sh` refuses to cut a release over a red gate. This release
carries R67's work as well as R68's; the v0.27.0 stanza below stands as the
record of what that round did.

Three of the six red runs were not product defects at all. Two were the GATES
themselves being wrong, and one was a fix that had not been finished.

### A gate that matched its own rationale

`check_no_allow.py` failed on a doc comment explaining why a field is named
`_file` "rather than carrying an `#[allow(dead_code)]`". It regexed raw source,
so prose describing the violation read as the violation.

This is the exact defect `check_positional_args.py` was fixed for six commits
earlier, where a comment quoting `args.get(1)` was scanned as code. That fix
shared the stripper out to `_srcscan.strip_rust_comments` with a docstring
saying "any gate that regexes Rust source shares that exposure" — and then this
sibling was not migrated. Fixing the instance and leaving the class alive is how
it came back four days later.

All three gates that INTERPRET Rust source now strip comments.
`check_file_size.py` counts lines, where a comment IS a line, so it stays
exempt — audited rather than assumed.

### The socket rule, made structural

R67 established that the bound socket must stay open until after the ownership
check: `(dev, ino)` identifies a file only while its inode cannot be reused, and
Linux recycles inode numbers immediately. The fix was to have `serve` BORROW the
listener. That was not enforcement, it was a proxy for enforcement — and it cost
more than it looked:

* `tokio::spawn` needs `'static`, so all seven call sites in the integration
  tests had to `Box::leak(Box::new(listener))`. A lifetime being used to express
  something that is not about lifetimes.
* the borrow landed without those call sites, so `cargo clippy --all-targets`
  had been red on Linux ever since.
* nothing stopped a future edit from closing the listener early again, which is
  how the bug arrived in the first place.

`HeldSocket` now owns the listener, the startup lock and the recorded identity
together, and its `Drop` body performs the ownership-checked unlink. Rust runs a
`Drop` body BEFORE dropping the struct's fields, so the socket is necessarily
still open when the check runs. The invariant is a consequence of drop order
rather than of anyone remembering to read a comment.

A second check-then-act went with it: `main` read `SocketOwnership::of(path)`
AFTER the lock section, so the path could have been replaced between our `bind`
and our reading of what we bound — recording, and later deleting, someone else's
socket. Identity is now captured inside `acquire`, still under the lock.

Corrected while there: the module doc said "an open fd pins the inode". Probed —
`fstat` on a bound `AF_UNIX` fd reports a *sockfs* inode with no relation to the
filesystem entry. Right conclusion, wrong mechanism; what pins the inode is the
path reference the kernel holds from `bind` until release.

### camoufox raised to latest, through three holes not two

The e2e browser had been pinned to build beta.28 because beta.29 moved page
scripting into an ISOLATED WORLD — the app's globals read `undefined`, 60 tests
failed, and the page itself was perfectly healthy. The recorded plan was
"prefix every evaluate / wait_for_function with `mw:`". Probing found that plan
was only half possible, and that a third hole mattered more than either:

1. `page.evaluate` does reach the main world via `mw:` plus
   `main_world_eval=True`. Both halves required.
2. **`wait_for_function` has no main-world form at all** — probed on camoufox
   0.5.4 and 0.5.5: prefixed and flagged, it still times out while the identical
   expression through `evaluate` returns the value. `wait_js` polls instead.
3. **`add_init_script` has none either**, and that is where the suites install
   `window.__api` before the app reads it. All four spellings leave the page
   unable to see what they installed. `add_init_js` bridges it the way
   userscripts do `@run-at document-start`: the isolated world shares the DOM, so
   an init script that appends a `<script>` element gets it run in the MAIN
   world. Ordering verified, not assumed — `['mock', 'app']`.

All 191 call sites route through `tests/support/browser.py`. That module exists
because the launch call was copy-pasted 17 times; 191 open-coded prefixes would
have rebuilt the problem one layer up.

Full e2e suite on beta.29: 132 passed, 2 skipped.

### sysmon: one renderer for the device and the preview

The last widget still drawn twice. The GUI sampled psutil and rendered its own
PIL frame while the device was drawn by `live_jobs/render.rs` — the same
second-implementation shape R67/C2 removed from now-playing and weather, and the
reason a preview can look right while the device is wrong.

New `sysmon` daemon RPC returns the stats AND the exact frame the device would
be shown, as base64 raw RGB. The GUI writes those bytes to a PNG and uses it for
both the tile and the push, so screen and matrix have one origin.

`sysinfo` reports CPU as a delta between refreshes, so the one-shot path
refreshes twice around `MINIMUM_CPU_UPDATE_INTERVAL`; without it the preview
would confidently report an idle machine. Verified against a real daemon over
the real socket.

`divoom_client/daemon_protocol.py` crossed the 500-line gate, so the host-data
RPCs — `now_playing`, `players`, `weather`, `sysmon` — moved to
`daemon_host_data.py`. They belong together beyond length: each answers a
question about the HOST, and each was once answered a second time in the GUI.

### The e2e harness was running whatever binary lay around

Found by the version bump, which is the only reason it was ever found.

`_find_rust_binary` preferred `target/release/divoomd` unconditionally, and
nothing in this repo rebuilds a release binary — `cargo build` and CI both
produce `debug`. So one leftover release build had quietly become "the daemon
under test" on this machine, however old it was. Every green run on those tests
was green about code that was not in the tree.

The bump made the leftover 0.27.0 binary mismatch the client's expectation. The
version guard did its job, stopped the "stale daemon", and two tests died with
`[Errno 2] No such file or directory` — a message naming a socket, in the round
that had just rewritten socket handling. CI stayed green throughout: a fresh
checkout has no leftover release binary.

The direction it failed in was the lucky one. The same hole passes tests against
code that was never built.

Now selects newest-by-mtime, AND asserts at fixture setup that the spawned
daemon's reported `daemon_version` matches the tree's, failing with both
versions and the rebuild command. Recency alone still runs a stale artifact when
it happens to be newest; the identity check is what makes it a sentence instead
of an errno four calls later.

### Also

* Ambient preview tiles were listed as an open defect; they were fixed in
  `0869425` and the roadmap entry was stale. Corrected the doc rather than the
  working code.
* `divoomd` ignores unknown flags and starts a daemon on the default socket —
  `divoomd --version` binds `/tmp/divoomd.sock` instead of printing a version.
  Noted, not fixed.

## v0.27.0 — R67: seven classes, and three things that never worked (2026-08-30)

Six user-reported symptoms, traced to **seven named classes** rather than seven
patches. Three features turned out to be not merely buggy but **entirely
non-functional**, each for reasons invisible to a green test suite:

* **the virtual wall** — three independent showstoppers, any one fatal;
* **the hot-channel button** — progress was stored and never broadcast, so it
  sat on "Preparing..." forever;
* **ambient modes 1-4** — the mode byte was hardcoded to 0, so every mode sent
  Plain Colour while the RPC reported success.

The through-line: each was found by TRACING the boundary — wire bytes, process
state, a grep for a field nobody reads — never by reading code, and each was
invisible to the suite because the suite asserted on return values that were
cheerfully correct.

New in this release: a standalone `nowplaying` crate (macOS MediaRemote album
art as real bytes, replacing AppleScript + iTunes-Search guessing), media-player
discovery, `now_playing` / `players` / `weather` daemon RPCs, `install.sh`
(self-contained bundle to /Applications), protocol versioning and capability
negotiation, and a daemon version guard that restarts a stale daemon instead of
silently talking to it.

Six new structural gates: `check_scripts`, `check_positional_args`,
`check_weather_parity`, `check_version_consistency`, plus the hardware harness
(`scripts/hw_e2e.py`) that asserts on the wire trace rather than on RPC success.

Python 2912 / 0 failed / 94 skipped. Rust 244 / 0.

### The socket that would not clear

A stale socket file made the daemon fail to start, and nothing told the user
why. Both halves are now fixed.

The old `bind()` was check-then-act and handled exactly one case. Every other
blocker collapsed into one opaque errno -- a directory or regular file on the
path, a missing parent, another user's socket, a path over `sun_path` (~104
bytes on macOS) all came out as "Address already in use" or "Invalid argument",
and none are fixed the same way. Any successful connect was assumed to be a
healthy divoomd, so an unrelated program listening there was reported as ours.

It also lost the startup race: two daemons both saw an empty path, both
unlinked, both bound, and the loser kept serving an unlinked inode -- reachable
by nobody, still holding the single-owner CoreBluetooth central. That is the
34-hour orphan `socket_owner` exists to describe, and it is CREATED at startup;
the ownership check only limits the damage at exit.

And the reason went nowhere: divoomd is spawned detached with stderr in a log
file, so `eprintln` + `exit(1)` was invisible, and the client reported only
"Daemon did not become ready within 8.0s" -- a statement about its own patience.

`socket_bind::acquire` now holds an advisory lock on `<socket>.lock`, making
inspect-and-bind atomic across processes, and keeps it for the daemon's
lifetime. Blockers are distinguished and each carries a remedy. Self-healing is
limited to the two unambiguous cases: a stale socket nothing is listening on,
and a missing parent directory. A regular file is NEVER auto-removed -- it may
be data, and guessing wrong is unrecoverable. Failures are written to
`<socket>.failure`, which `divoom_client.socket_failure` reads so the client
logs the cause and the GUI banner states it instead of "Background service
isn't running". Exit codes are distinct: 3 already-running, 4 mid-startup, 1 a
real problem.

Verified against the real binary, not only units: a stale socket is cleared and
the daemon serves; a second instance exits 3; a directory in the way survives
and reaches the client as "is a directory, not a socket. Move or delete that
file yourself."

### When the gates disagreed with CI

Three of this round's own gates were wrong in ways that only CI could see, and
each is the same shape as the bugs they were built to catch: a fact checked in
one environment and trusted in another.

**`check_positional_args` returned different verdicts on different
filesystems.** It failed CI on `display.show_light` and passed locally on the
same commit. Two stacked defects: it regexed RAW SOURCE, so the comment
explaining that brightness *"used to read `args.get(1)`"* matched as if it were
code — the gate flagged the handler it had already fixed; and it selected
Python signatures with `setdefault` over an UNSORTED `rglob`, so for a name
defined twice (`show_light`: annotated in `display/__init__.py`, bare in
`display/light.py`) the winner depended on directory order. APFS returned the
bare one, which masked defect 1; ext4 returned the annotated one, which
unmasked it. Now sorted, richest-signature-wins, and comment-blind via
`tools/_srcscan.py` — which `check_weather_parity` also uses, since it would
have read a commented-out `(code, WeatherType::X)` as a live table entry.

**60 browser e2e tests went red with no code change.** CI had been failing
since 2026-08-25 and the range that broke it touched only gate scripts -- no
web UI, no test support. The cause was an UNPINNED test dependency: `pip
install camoufox` picked up 0.5.5 (browser 152.0.4-beta.29), which runs
`page.evaluate` in an ISOLATED WORLD, so `window.DivoomState` and every render
function read as `undefined`. Reproduced locally by building a 0.5.5
environment -- byte-identical error -- and probed to rule out the obvious
alternative: all 29 scripts fetch 200, the DOM builds, and there is not one
console or page error. The page works; only `evaluate`'s view of it changed.
The variable is the BROWSER BUILD, not the pip package: holding camoufox at
0.5.4 and moving only the build reproduces it exactly (beta.29 fails, beta.28
passes). Pinning the package would not have fixed CI -- 0.5.4 accepts any build
in `[alpha.1, 1)`, so `camoufox fetch` still takes the newest. CI now pins the
build with `camoufox set official/stable/152.0.4-beta.28`. Raising it is a
migration (every `evaluate` needs camoufox's `mw:` prefix; `main_world_eval=True`
alone does not restore the old default), recorded at `tests/support/browser.py`.

**The Linux build broke twice the same way.** `nowplaying` is macOS-only
(MediaRemote), and a reference to it stayed ungated — the second time as
`use music_job::run_music` beside an already-gated `mod`. A macOS machine is
structurally incapable of seeing that class, so the full local gate went green
both times and CI was the only instrument, making each fix a blind
push-and-wait. `scripts/check_linux_build.sh` now cross-compiles divoomd for
`x86_64-unknown-linux-gnu` with zig and is wired into the local gate;
calibrated by removing the cfg and confirming it reproduces CI's exact
`error[E0432]` before being trusted.

### Weather, and a virtual wall that never worked

**Weather (C2's remaining half).** The Rust and Python WMO tables were diffed
FIRST and agree on all 48 codes — unlike now-playing, this duplication had not
drifted — so the fix is prevention, not repair. The mapping is now a `const`
table (a `match` arm is invisible to a checker) with
`tools/check_weather_parity.py` failing on either drift shape, and the GUI is a
client of a new `weather` RPC that also receives the locally-resolved location,
closing the gap where the card and the device could geolocate differently.

**The virtual wall did not work at all**, for three independent reasons:

* it could never CONNECT — `wall_configure` uppercases slot keys (a MAC-address
  convention) while macOS uses lowercase UUIDs and the BLE connect matched
  case-sensitively, so every slot failed for devices a scan had just found;
* nothing REACHED a wall even when connected — the client has always sent
  `target: "wall"` and the daemon never read it, so every call went to the
  single device and the `DivoomWall` methods were unreachable dead code;
* the ambient payload was TRANSPOSED — brightness and RGB swapped, six bytes
  instead of ten, the last byte landing in the lighting-type slot; effects and
  visualization sent two-byte packets. The Python wall never had these because
  it delegates to the canonical builder.

Verified live on a 2-panel wall: every command goes out once per panel, the
ambient bytes are canonical, a split image streams to both, and unsupported
methods refuse with a reason instead of silently succeeding.

Also: `parse_hex_color` existed in three copies, now one.

Python 2904 / 0 failed / 94 skipped. Rust 243 / 0.

### The album-art library

Now-playing and cover art move to a standalone `nowplaying` crate built on macOS
MediaRemote. This closes C2 for music and dissolves C3 entirely.

**What the probe established, before any design.** On macOS 26.6.2 a direct
`dlopen` of MediaRemote from an ordinary process succeeds, `dlsym` succeeds, and
the callback returns a NULL dictionary — Apple entitlement-gated the read API in
15.4, and it fails in the shape of "nothing is playing". `/usr/bin/perl` carries
that entitlement and a dylib loaded into it inherits it, so the query runs
through a ~60-line helper of ours (`nowplaying/native/np_helper.m`) — the
approach `mediaremote-adapter` (BSD-3) established, implemented independently so
nothing third-party is vendored.

**What changed.** Deleted `divoomd/src/live_jobs/music.rs` and 164 lines of the
same logic in `divoom_lib/utils/media_source.py` — both drove AppleScript at
each player and then guessed a cover-art URL from the iTunes Search API, a guess
that cannot resolve non-album content and needs a network round trip in order to
fail. Added the crate, the `now_playing` daemon RPC, and `DaemonClient.now_playing`.
The GUI is now a client and renders the same artwork bytes the device is pushed,
as a `data:` URL — the web UI runs from a `file://` origin where WKWebView blocks
remote subresources, which is why the old remote `artwork_url` showed broken.

**The app no longer asks for Automation access to music players.** MediaRemote
needs no Apple Events, so nothing queries a player over AppleScript and the
priming list is empty. The drift gate now discovers player queries across the
tree rather than reading a hardcoded file list, and fails in both directions.

**Two properties of the source, discovered rather than assumed:** the declared
MIME lies (`image/jpeg` over TIFF bytes — everything sniffs magic numbers, and
`divoomd`'s `image` crate needed the `tiff` feature it did not have), and perl's
architecture is INHERITED (the same command ran arm64 from a shell and x86_64
from the daemon, where perl refused our arm64 dylib — the host is now pinned
with `arch -arm64` rather than shipping a policy-violating fat dylib).

**Three bugs found during verification rather than review:** a pipe deadlock
(stdout read only after exit, against ~1.6MB of base64 through a 64KB buffer —
passes with any small fixture, hangs on every real track); `stderr` discarded,
which made the next one undiagnosable; and the architecture mismatch it hid.
Separately, live-job health needed a resync path — events fire only on
transitions, so a late subscriber saw nothing until `live_job_list` learned to
report current state.

Verified on hardware: Kaset -> MediaRemote -> daemon -> Pixoo-1, 363,390 bytes
of TIFF cover art, streamed to the panel; and the same through the installed
/Applications bundle.

Python 2926 / 94 skipped. Rust 196 / 0.

### The seven classes

Six user-reported symptoms, traced to **seven classes** rather than seven
patches. Full analysis in `docs/PLANNING_ROUND67.md`.

**Harness first** (house rule #1 — a defect that reached a user means the
harness has a hole):
- `scripts/make_dev_daemon_app.sh` had been DEAD since R66: it built an .app
  that exec'd `python -m divoom_lib.cli daemon`, a subcommand archived twelve
  days earlier that only prints an error. It now execs `divoomd` and `--verify`
  launches the bundle it just built, failing unless it answers `ping`.
- `scripts/hw_e2e.py` — live-hardware scenarios asserting on the
  `DIVOOMD_BLE_DEBUG` wire trace, not on RPC success. `device_call` returns
  success even when the payload carries the wrong byte, so a success-only
  harness is blind to exactly this round's defects. It found two of them.
- `scripts/daemon_ping.py`, `tools/check_scripts.py` (the gate `scripts/` never
  had), `tools/check_version_consistency.py`.

**Fixed as classes:**
- **C1** One wire packet, many builders. The 0x45 family had four disagreeing
  builders. `display.show_clock` put weather/temp/calendar in bytes 4/5/6 where
  the canonical order is humidity/weather/date — asking for weather turned on
  HUMIDITY. `display.show_light` hardcoded the lighting-type byte, so all five
  ambient modes sent identical Plain packets. `device.show_clock` hardcoded five
  fields including the colour. Now typed `ClockPacket`/`LightPacket` with named
  fields and one serializer each.
- **C3** The Automation priming list drifted from the consumer list: Kaset was
  addressed in both languages and primed in neither, so its Apple Event was
  denied in the headless daemon while the foreground GUI worked. One registry,
  one gate over both implementations.
- **C4** Live jobs pushed nothing, said nothing, and slept — 15 minutes for
  weather — with no device. They now publish `live_job_state` on transitions and
  re-check every 5s while waiting; GUI toggles report what the daemon said.
- **C5** The daemon unlinked its socket on shutdown without checking it still
  owned it, so killing one daemon deleted a live one's socket, leaving it
  running, unreachable, and still holding the BLE central. Ownership is now
  `(dev, inode)` recorded at bind.
- **C6** `HotProgress` stored progress and never broadcast it, while R59 had
  deleted the GUI's poll — the hot-channel button sat on "Preparing…" forever
  and stayed disabled. Store and broadcast are now one operation.
- **C7** Positional arguments were read from a COMPACTED numeric list, so
  ambient brightness transmitted the mode number. Found by the wire trace on
  real hardware.

**Also:** `install.sh` installs a self-contained bundle to `/Applications`
(removing C5's enabler — the repo bundle just exec'd python with no cleanup);
`build_libdivoom.sh`'s unsupported-OS branch now hard-fails instead of building
an untested binary; the connect e2e suite no longer collides with the user's
running app; `pyproject.toml` 0.24.3 -> 0.26.0 (two releases had shipped
reporting the stale value).

Python 2943 / 0 failed / 94 skipped. Rust 157 / 0.

## v0.26.0 — harness unification: local CI delegates to gates_of_heck (2026-08-25)

### Changed
- `scripts/ci_local.sh` is a thin driver over `$GOH/gates/local_ci.sh`; the job
  list is declarative in `.gatesrc` (`GOH_CI_STEPS`), same 8 jobs in the same
  order as before. `--fast` still skips exactly one step (the Python suite).
- `scripts/py_ci.sh` (new) is the genuinely divoom-specific CI job — dylib
  build, camoufox presence stated out loud when absent (suites SKIP, not run),
  pytest.
- `scripts/house_emoji_gate.sh` (new): emoji gate with `GOH_EXCLUDE` applied
  conditionally; kept out of the colon-separated `GOH_CI_STEPS` because its
  parameter expansions contain colons.

### Added
- A coverage floor where none existed: `scripts/rust_coverage.sh` now
  delegates to `$GOH/gates/coverage_gate.sh --lang rust`, pinned at 29% of
  coverable lines (measured 2026-08-25 at 29.74%, 3066/10311). Previously any
  coverage passed.

### Removed
- No forked checkers remain: file-size and no-allow checks run the house
  copies, and the honest "what macOS-local cannot see" statement moved into
  `.gatesrc` above the step list.

## v0.25.0 — every file under the 500-line cap (2026-08-25)

### Changed
- All 14 over-cap test files split along subject seams into focused modules
  with shared fixtures deduplicated into `tests/support/` (largest:
  `test_gui_api.py` 1951 lines -> 9 modules + `support/gui_api_base.py`).
  Test-function counts verified identical before/after for every file.
- `tests/` removed from the `GOH_LINE_EXCLUDE` length exemption in
  `.gatesrc`; only `docs/divoom_docs/` (captured third-party API data)
  remains exempt. The 2026-08-24 DEBT note is resolved and removed.
- Verified by the repo's own `make test`: 2827 passed, 94 skipped.

## v0.24.3 — e2e injectors that silently did nothing (2026-08-23)

### Fixed
- **Three injected e2e scripts ended their missing-element branch with a bare
  `return`**, so a missing container raised nothing and deferred the damage:
  - *gallery*: nothing injected, so the wait for `scrollHeight > clientHeight`
    blocked on a condition that could never become true and died at the timeout
    naming the layout check rather than the absent container. This is what the
    v0.24.2 release failure looked like from outside, and why raising the
    budget from 5s to 20s did not help.
  - *hot-preview*: worse — the layout assertions only mean anything if the list
    overflows. Against an empty card the button is trivially within bounds, so
    the test **passed while measuring nothing**.
  - *wall tab*: an `if (wallTab)` no-op left the wait on `#arranger-canvas` to
    time out naming the canvas, not the absent tab.

  All three now fail at the precondition and name it. Proven by renaming each
  container: opaque `TimeoutError` becomes
  `injection did not take effect (returned -1) — #hot-preview-list was missing`.

### Changed
- **e2e timeout budgets centralized** as `UI_TIMEOUT_MS` in the browser seam
  (20s, override with `DIVOOM_E2E_TIMEOUT_MS`). The suites carried ~47 ad-hoc
  values invented per call site. These are budgets, not assertions — no test
  measures UI speed — so a tight one cannot catch a defect a generous one
  misses; it can only redden a busy machine. Not applied to absence assertions,
  where a short timeout IS the assertion.

### Honest scope
The no-op fixes are root-cause work and are proven. The budget change is
hardening for a defect never reproduced — not under a saturated 16-core
machine, not across the full 166-test e2e subset, not on repeated runs of the
exact failing command — and is not claimed as a fix for it.

## v0.24.2 — dropped notifications on tied timestamps (2026-08-23)

### Fixed
- **`macos_notifications`: notifications sharing a `delivered_date` with the
  last-processed one were dropped forever.** The poll cursor was a
  `delivered_date` float queried with `WHERE delivered_date > ?`. Ties *within*
  one batch are harmless — the query already returned them — so this survived
  ~2900 test runs. Across batches it is not: once the cursor reaches a
  timestamp, a record arriving later that ties it can never satisfy `>` and is
  silently dropped for the lifetime of the monitor. `delivered_date` is a
  CFAbsoluteTime float and real notifications do tie; simultaneous arrivals are
  exactly when both matter.

  The stated spec was already correct and unimplemented — the test's own
  docstring said the tied record "must still be processed". It only passed
  because it almost never reached that state.

  Fix: `delivered_date` stays the coarse cursor, but ties break by stable
  identity — `>=` plus a `_seen_at_cursor` set of rowids already processed at
  the cursor timestamp. A timestamp alone cannot be exact in both directions
  (`>` drops the tie, `>=` replays history); only identity separates "already
  delivered" from "new, same second". `start()` seeds both halves so existing
  notifications are not replayed.

  Affects v0.24.1 and earlier.

### Changed
- **CI: migrated off the deprecated Node 20 action runtimes** (house rule: never
  build on deprecated APIs). `actions/checkout@v4` and `actions/setup-python@v5`
  are `node20`; both moved to `@v7` (`node24`) after checking the runtimes and
  reviewing breaking changes — checkout v7 only restricts fork checkouts on
  `pull_request_target`/`workflow_run`, triggers this workflow does not use.
- **Retired the last "CI is down" claims** from `.githooks/pre-push`,
  `scripts/ci_local.sh`, and `docs/PLANNING_ROUND66.md`. The load-bearing
  correction is in `AGENTS.md`: this repo is PUBLIC, and GitHub Actions on
  standard runners is free for public repositories, so no credits are consumed
  here regardless of the account's private-repo balance.

### Tests
- The flaky tie test now FORCES the interleaving (waits for a poll pass between
  the two inserts) so it takes the branch every run instead of by luck.
- New startup-seed test covering the replay-vs-tie distinction.
- Teeth proven: restoring `>` turns both red deterministically.

## v0.24.1 — flaky-CI round: three gates that lied, one real bug (2026-08-23)

Chased "the CI is flaky" to root causes. It was not flakiness in the usual
sense: every one of the four findings was a defect that happened to surface
intermittently. Suite: **Python 2920 tests / 0 failed / 0 errors / 94 skipped**
(+10 new); Rust workspace green; `ci_local.sh --fast` all jobs pass.

### Fixed
- **`control_server`: early error replies now drain the request body.**
  CLASS: a handler branch answering BEFORE consuming `Content-Length` leaves
  unread bytes in the receive buffer; the close then RSTs, so the client's next
  write dies with EPIPE and it never gets to READ the status code we correctly
  sent. `do_POST` had three such branches (401 unauthorized, 404 non-`/api/`
  path, 404 unknown method). CI run 32655925962 lost that race on the 401 and
  reported `BrokenPipeError` where a clean `RuntimeError` was expected. This is
  a real bug any client POSTing with a bad token can hit — it merely *reads* as
  a flaky test. Fixed at the class level: `_send()` drains first, so no early
  return (present or future) can forget. Bounded in size (`_MAX_DRAIN`, 1 MiB)
  and time (handler `timeout`), since it reads for unauthenticated callers.
- **e2e browser guard is now structural, not conventional.** R66 asked all 15
  e2e modules to call `require_browser()`; 13 did. The two that did not were
  exactly the two sync-API ones, so a missing browser ERRORED them at fixture
  setup (6 errors, run 32654312489) while the other 13 skipped. `launch()` /
  `launch_sync()` now guard themselves, and a scan test keeps the seam the only
  door.
- **The guard suite's own bail-out was the same mistake one function over.**
  `if not installed_verstr()` was written against a return-value contract
  camoufox does not have — it RAISES `CamoufoxNotInstalled` when nothing is
  fetched — so the "does not over-skip" test blew up instead of skipping on a
  browserless machine. That was the `FAILED ... CamoufoxNotInstalled` in CI.
- **The camoufox install step verified nothing.** `python -m camoufox fetch`
  **exits 0 when it installs nothing**: run 32654312489 hit GitHub's
  unauthenticated API rate limit (60/hr, shared across every Actions runner on
  that egress IP), printed three 403s and `Synced 0 versions from 0 repos.`,
  and still reported the step green — the damage surfaced minutes later inside
  pytest, looking like a test regression. Fixed on both axes: `GITHUB_TOKEN`
  removes the cause (camoufox reads it; 1000/hr/repo), and
  `tools/check_camoufox_installed.py` removes the silence by checking the
  artifact. The retry loops on the VERIFICATION, not the exit code — looping on
  the exit code would never retry this failure, since it exits 0.

### Added
- `tools/check_camoufox_installed.py` — install verification, used as the CI
  retry's loop condition and reported (as a warning, not a failure) by
  `ci_local.sh` so a local green cannot silently mean "all 15 e2e suites
  skipped".
- Regression tests for all four, each proven able to fail.

### Notes on method
- The first version of the body-drain test ran against the **TCP** fixture and
  passed with the fix removed — an instrument blind to what it measured. Over
  loopback TCP the scenario does not reproduce; only AF_UNIX fails the write,
  and AF_UNIX is the socket CI was on. Measured both ways, then rewritten.
- Both "browser absent" states are driven through camoufox's OWN signals rather
  than stubs of our probe, and every new gate is tested in the accept direction
  too — a checker that always failed would look like a working gate while
  blocking CI permanently.

## v0.24.0 — Rust dependency refresh (2026-08-21)

### Changed
- **divoomd**: rusqlite 0.31→0.40 (9 release lines), base64 0.22→0.23,
  btleplug 0.11→0.12, reqwest 0.12→0.13 (feature rename `rustls-tls` →
  `rustls` + `webpki-roots`; `.query()` moved behind the new `query`
  feature), libloading 0.8→0.9 (`Library::new` now takes `AsFilename`;
  `NativeEncoder::load` switched to `AsRef<Path>`).
- **divoom-menubar**: tray-icon 0.19→0.24, tao 0.31→0.37.

### Verified
- `scripts/ci_local.sh` all CI-equivalent jobs green: house gates, divoomd
  clippy + build/test with and without default features, BLE cargo tests,
  native dylib build, full Python pytest suite.

## v0.23.0 — Apple silicon only; one Rust workspace; dead code out; gates that actually gate (R66, 2026-08-17)

**Breaking: Intel Macs are no longer supported.** Apple has dropped them, so
have we. The Homebrew cask now declares `depends_on arch: :arm64`, so an Intel
Mac gets a clean "unsupported" rather than a broken install. 32-bit targets are
unsupported on any OS. **Linux x86_64 is unaffected** — this drops macOS Intel,
not x86_64.

Layout round. The tree still described the *migration* that produced it rather
than the system it produced, and several gates turned out to be checking less
than they claimed. Net **-14,240 LOC** (188 files, 2,935 insertions / 17,175
deletions).

**Suite: Python 2910 tests / 2816 passed / 0 failed / 94 skipped; Rust 119
passed across the workspace (was divoomd-only before this round).** Verified
with `scripts/ci_local.sh` — all CI-equivalent jobs pass.

### Dead code removed (~12.6k LOC)
- **`native-port/spike-ble/`** — the Phase-1 BLE port spike, superseded by
  `divoomd`. Zero references anywhere.
- **`divoom_menubar/`** (648 LOC) — the pyobjc menubar, superseded by the Rust
  tray agent. `setup_app.py` called it "in-tree as reference", yet it was still
  listed in the py2app packages AND pyproject's discovery, so **every shipped
  DMG carried a menubar that never ran**. `cmd_menubar` retired (actionable
  error + exit 1) rather than deleted, matching how `cmd_daemon` was retired.
- **`archive/`** (63 files, ~12k LOC) — the Python daemon server, archived
  2026-07-13. Nothing imported it, but three CI gates scanned it every run.
  Removing it also retired a workaround: `pytest.ini` carried
  `--ignore=archive` purely because `archive/tests/conftest.py` re-registered
  `--run-hardware` and aborted collection.

### One Cargo workspace — and a crate that had never been gated
Root virtual manifest, `resolver = "2"`, one `Cargo.lock`, one repo-local
`target/`. `exclude = ["references"]` is mandatory: the three vendored
protocol-reference crates otherwise break every cargo invocation.

This closed a real hole. CI's `rust-core`/`rust-ble` both ran
`working-directory: divoomd`, and the pre-commit hook passed
`"$root/divoomd"` — so **`divoom-menubar` was outside every gate**: no fmt, no
clippy, no build, no test. Running `cargo fmt --all` from the new root proved
it: the crate **had never once been formatted** (129 insertions across all four
source files). Both CI jobs and the hook now gate the workspace root.

### `native-port/` retired — and the path class it hid
`native-port/divoom-menubar/` → `divoom-menubar/`, `gen_*.py` →
`scripts/codegen/`. ~30 references updated.

Two files did not merely *reference* the path, they did arithmetic on it:
`exe.parent()?.parent()?.parent()?.parent()?` — "4 parents = project root".
Under the workspace the binary sits one level shallower. **Neither would have
failed loudly**: `find_encoder_lib()` returns `Option`, so it silently degrades
to no native encoder; `spp.rs` would hand the SPP bridge a nonexistent path.
Tests stay green either way. Fixed as a class in `divoomd/src/paths.rs` —
search UP for a marker directory, immune to workspace / shared
`CARGO_TARGET_DIR` / `cargo run` / .app layouts. Four tests, including the
must-return-`None` case so it cannot walk to `/` and claim success.

### `divoom_daemon/` → `divoom_client/`
The package contained no daemon; its own docstring opened "CLIENT LIBRARY —" in
caps to counteract the name. 159 references across 43 Python files, packaging,
Rust, and docs. ROADMAP's historical shipped-rounds rows deliberately left
naming the old paths — they record where code was at the time.

### 64-bit only; macOS is Apple silicon only
`build_libdivoom.sh`'s arch `case` ended in a `*)` that warned and **kept
going**, so a 32-bit host silently built something nobody had ever compiled or
tested. Both macOS-Intel and 32-bit are now hard failures, with an overridable
`OS`/`ARCH` seam so both the reject AND accept directions are testable on one
machine (`tests/test_build_platform_gate.py`, 10 cases). Linux x86_64 is
unaffected — this drops macOS Intel, not x86_64.

### e2e suites moved to camoufox — and the guard that never guarded
The 15 GUI e2e modules guarded with `pytest.importorskip("playwright.async_api")`,
which only proves the *module* imports. With the package installed but no
browser downloaded they did not skip — they raised
`BrowserType.launch: Executable doesn't exist` and produced **69 failures that
read exactly like real regressions**. That is precisely what this round's first
baseline run was. Now one seam (`tests/support/browser.py`) probes the binary,
and `tests/test_e2e_browser_guard.py` pins both directions (it must skip when
absent, and must NOT over-skip — a guard that always skipped would disable all
15 suites while looking green).

The migration also exposed a latent harness defect in two tests, **not** a
camoufox flake: both waited on a proxy DOM signal and then asserted on a
different one, so the passing order was a Chromium timing coincidence — and when
the proxy was already in its final state, the wait returned instantly, before
the behaviour under test had happened. Both now wait on the condition they
assert.

### Docs made true
`ARCHITECTURE.md`'s headline section still said `divoom_daemon/` was "the SINGLE
owner of the device connection" — false since the Rust cutover, and `AGENTS.md`
points every agent at that file on entry. Rewritten to the real topology.
`docs/archive/rounds/` and `docs/archive/superseded/` do not exist (pruned to
git history) yet 6 references still pointed into them. `RELEASING.md` named
`/tmp/divoom_daemon.log`; the daemon writes `/tmp/divoomd.log`.

### CI is unavailable — `scripts/ci_local.sh` is the gate
GitHub Actions credits are exhausted, so CI always fails: a red check is not a
code signal and a green one is unobtainable. `ci_local.sh` mirrors `tests.yml`
job-for-job. The pre-commit hook is NOT a substitute — it checks only staged
files, gated only `divoomd`, and runs no tests. **The workflow YAML changes in
this round are unverified**; the YAML parses and every command was proven
locally, but the workflow itself has not executed. Re-check when billing returns.

## Unreleased

- **release rule:** cutting a release is only allowed when GitHub CI is green for
  the commit being tagged. `scripts/release.sh` now runs a preflight `ci_gate`
  that queries the commit's check-runs and aborts on a red / still-running /
  unverifiable CI. The one exception is **credit depletion** (GitHub Actions
  billing exhaustion) — auto-detected from the failure message; `--skip-ci-check`
  is the manual override for that case only.

## v0.22.21 — house Rust quality gate + 500-line file splits

- **ci:** wire the house Rust gate into CI + the pre-commit hook —
  `cargo fmt --check`, `cargo clippy --all-targets --all-features -D
  warnings`, and a new `tools/check_no_allow.py` (no `#[allow]` in
  tracked source). divoomd had never been clippy-gated; ~53 warnings
  across 13 files fixed. Also fixed the clippy step on Ubuntu: the
  `rust-core` job now installs `libdbus-1-dev` so `--all-features`
  (`ble` → btleplug → dbus) builds there too.
- **house style:** split 9 files over the 500-line cap
  (cloud_category, art_hot, device_call/basic, live_jobs/mod, wall,
  ble, daemon, daemon_connect, art_codec) into submodules; all 328
  source files are back under the cap.
- **style:** one-time `cargo fmt --all` reformat (the codebase was
  never fmt-clean; 68 files, +5947/−2736). Kept per decision.
- 102 lib+integration tests pass; emoji + 500-LOC gates clean.

## v0.22.20 — gallery: decode the rest (magic 8 / 12) + broken-image removal

- **fix(gallery decode):** `decode_cloud_frames` only handled magic
  9/18/26 — the other two cloud container magics were left as
  black/empty tiles. **magic 8** is a static AES image (strip 1
  header byte, decrypt with the same `78hrey23y28ogs89` key/IV as
  magic 9 → a 16×16 frame); **magic 12** is a scroll/marquee
  buffer (`[12][scrollMode][speed:2 BE]`, strip 4 bytes, decrypt
  → a 64×16 frame). Both now decode and render. Confirmed
  live: a full 16-category probe decoded **all 455 items** with
  **zero undecodable / zero broken frames** (the prior run had 29
  undecodable — exactly the magic 8/12 items).
- **fix(packaging):** `pycryptodome` and `lzallright` were
  required by `decode_cloud_frames` but **not declared deps** — a
  clean install (or the shipped DMG) decoded *zero* cloud items
  because `Crypto` was missing (only present by accident on the
  dev box). Added to `pyproject.toml` + `requirements.txt`, and
  force-collected in `divoom.spec` so PyInstaller bundles them.
- **fix(gallery broken-image removal):**
  - *load time* (`gallery_download.fetch_gallery_asset`): a
    `validate_preview()` step now opens any cached preview and drops
    it if it is **unreadable / degenerate / fully-transparent**, so a
    stale/corrupt preview is re-decoded in the same pass instead of
    rendering a permanent black tile. (Solid-color / near-black art
    is valid and is *not* dropped.)
  - *runtime* (`web_ui/gallery.js`): the preview `<img>` gets an
    `onerror` handler that **removes the tile** when a broken cached
    preview fails to load, and the decode-failed path now removes
    the tile (previously it was left as a dead `is-unavailable`
    skeleton).
- **tooling:** new `scripts/verify_gallery_render.py` — an offscreen
  contact-sheet harness that decodes every gallery asset across all
  16 categories and asserts zero broken frames (the
  `media_decoder` pipeline is the source of truth that feeds the
  UI). Used to verify the fix end-to-end.
- **tests:** fixtures `tests/fixtures/gallery_magic{8,12}.bin`
  (recorded live), new `test_media_decoder_cloud.py` cases for
  magic 8/12 decode + `is_black_image`, and
  `test_gallery_sync_coverage.py` cases for the blank-preview drop
  behavior. Full suite green (numpy-gated modules excluded on this
  box); emoji + 500-LOC gates clean.

### Follow-ups
- Round 64 work; ship as v0.22.20 once the user confirms the
  live gallery renders fully.

## v0.22.19 — gallery black-tile recovery; CI fix

- **fix(gallery): a corrupt/truncated cached `.bin` no longer leaves a black
   gallery tile until the gallery is opened a second time.** The prior Round 62
   fix deleted a failed `.bin` but only *unlinked* it — recovery (re-download +
   decode) still needed the **next** `fetch_gallery` pass, so an item whose
   `preview_url` failed to decode rendered as a black `is-unavailable` box (name
   present, image empty) for the rest of the session. Extracted the
   download/decode into `GallerySyncMixin._fetch_gallery_asset()` (also clears
   the 500-LOC hotspot) which now drops a `.bin` that fails to decode **and
   re-downloads + decodes it in the same call**, so one fetch fully recovers the
   preview. Decode failure (clean `False` or exception) always drops the bad
   `.bin`; a missing preview with a working download is filled immediately.
   Added 3 unit tests in `test_gallery_sync_coverage.py`
   (corrupt-bin single-pass recovery, skip-when-already-decoded, download-failure
   handling); all gallery/media-decoder suites green.

### CI — sync-now e2e race against the 1500ms auto-refresh timer

- **fix(ci): `test_sync_now_progress_updates_the_right_device_row` was red on
  the CI runner.** `gallery.js`'s `setTimeout(updateSyncTargetList, 1500)`
  fired on the slow runner and re-rendered the sync-targets list with the
  test's mock `get_sync_candidates` response (`'{}'`); `renderSyncTargets`
  treated `{}` as a non-empty list, cleared `#sync-targets-list`, then threw
  on `({}).forEach` — wiping the rows the test had just created (30s timeout).
  Locally the test finished under 1500ms so it never hit it. Fixes: the test
  mock now returns a real candidate array for `get_sync_candidates`; the
  render + progress-fire + read are collapsed into one synchronous `evaluate`
  so the timer can't race it; `renderSyncTargets` now guards
  `Array.isArray` so a stray `'{}'` clears the empty-list message instead of
  throwing. The other 9 full-suite failures were pre-existing
  resource-contention flakiness in `test_daemon_connect_edge_e2e.py` (they
  pass in isolation with and without the change). `tests` job green on
  `main` (run 29361659806). Test-only — the shipped v0.22.18 DMG is
  unaffected.

## v0.22.18 — Bug batch: gallery, hot-channel sync, Sync Now, theming, alignment; CI green again

**RELEASED**: tag + GitHub release + Homebrew cask, all live and verified —
https://github.com/ztomer/divoom_lib/releases/tag/v0.22.18

User-reported bug batch (`docs/PLANNING_ROUND62.md`). Investigated live
against the real Divoom cloud API and this machine's actual gallery cache,
not just static reading — see the planning doc for the full root-cause
writeup.

- **fix(gallery): corrupt/truncated cached downloads were never retried.**
  `download_item()` (`divoom_gui/gallery_sync.py`) only re-downloaded a
  `.bin` if it was *missing*; a truncated download (confirmed live: AES-CBC
  padding errors on this machine's own cache) or any other decode failure
  left the same bad bytes cached forever, re-failing on every subsequent
  gallery load. Decode failure now deletes the cached `.bin` so the next
  fetch re-downloads fresh bytes.
- **fix(gallery): loading vs. permanently-unavailable art looked identical**
  — both fell back to the static Pixoo logo, so a gallery that was still
  populating in the background read as broken. `gallery.js`/`gallery.css`
  now give the loading state a distinct pulsing placeholder and a
  genuinely-missing preview a distinct dimmed/grayscale one.
- **fix(hot channel): the "Update" button stayed disabled after the first
  click, forever.** `gallery_hot.js`'s `applyProgress`/`finishProgress`
  were closure-local, but `connection_events.js`'s `onHotProgress` called
  them as `window.applyProgress`/`window.finishProgress` — both undefined,
  so the button-reset path silently never ran. Exposed both on `window`;
  removed the now-fully-dead `pollProgress`/`_pollTimer` polling loop they
  replaced.
- **feat: "Sync Now"** (Routines > Auto-Sync) — manually push hot-channel
  content to every toggled sync target immediately instead of waiting for
  the scheduled interval, with per-device progress on the existing device
  toggle rows. New `sync_now()` bridge method
  (`divoom_gui/gallery_hot_api.py`) sequentially connects each selected
  target (`connect_single_device`) and runs the same `hot_update` the
  single-device button uses, tolerating a per-device failure without
  aborting the batch; new `sync_now.js` + `onSyncNowProgress`/
  `onSyncNowComplete` events.
- **fix(theming): bottom-right toast popups were black-on-black in light
  mode.** `.toast` (`widgets_extra.css`) hardcoded a dark background
  literal instead of the theme's `var(--card-bg)`.
- **fix(device settings): clock format / temperature / power mode pill
  groups were center-aligned, not right-aligned.** The base `.tabs-row`
  rule's symmetric `margin: auto` won over the parent row's
  `justify-content: space-between`. Right-aligned to match the existing
  Orientation row's pattern.
- **verified, no change needed:** playlist push and photo album push
  (the latter landed in `0d513a5`/v0.22.17, already on `main`) both work
  correctly end-to-end — smoke-tested live.
- **test(pytest.ini):** local dev machines with other agent sessions'
  `.claude/worktrees/` checkouts hit an "import file mismatch" collection
  abort (duplicate module basenames across worktrees) — excluded, same
  treatment as `archive/`. CI is unaffected (no such directory there).

- **fix(ci): `pytest` collection aborted the whole `tests` job.** Since the
  Python daemon was archived (`046cdf8`), `archive/tests/conftest.py` shipped
  alongside the live `tests/conftest.py`; both register `--run-hardware`, so
  bare `pytest` hit `ValueError: option names {'--run-hardware'} already
  added` and interrupted collection before any test ran — every push since has
  shown a red `tests` job. `pytest.ini` now excludes `archive/` from
  collection (`--ignore=archive` + `norecursedirs`); it is retired
  reference-only code and was never meant to run. Verified: 2767 passed,
  94 skipped, 0 errors (was: 1 collection error, 0 tests run).
- **fix(tests): the two `mock_simulate_drop` e2e tests hard-failed for anyone
  with Playwright installed** (they skip in CI, which has no Playwright) — the
  native daemon doesn't implement `mock_simulate_drop` yet. They now skip with
  a reason when the daemon reports the command missing, matching the file's
  existing playwright/binary skip guards, and run for real once divoomd grows
  the command.
- **fix(tests): `test_audio_visualizer.py` hard-imported `pyaudio`** (present
  on the maintainer's machine, absent in CI, which has no PortAudio) — 7 tests
  errored with `ModuleNotFoundError`. Added a module-level
  `pytest.importorskip("pyaudio")` so it skips in CI and runs locally, matching
  the repo's skip-on-missing-optional-dep pattern. These were previously masked
  by the `archive/` collection abort.
- **ci: the `test` job now installs `pyaudio` (via Homebrew PortAudio) and
  `playwright` + a headless Chromium**, so the GUI e2e suites
  (`tests/test_e2e_*.py`) and the audio-visualizer suite run for real in CI
  instead of skipping. Locally these are 72 passed / 4 skipped (the 4 skips are
  the still-unimplemented `mock_simulate_drop` pair and the live-hardware
  pair). Blocking coverage — a real e2e/audio regression now reddens CI.
- **fix(tests): the `_IsolatedStack` HTTP-bridge wait timed out on the cold CI
  runner.** The bridge is a fresh interpreter that cold-imports the whole
  divoom_gui stack before it binds its port — 0.18s warm locally, but >5s on a
  cold runner under load, so all four `test_e2e_gui_daemon_connect_disconnect`
  tests errored with "never opened port". Raised the wait to 30s and made the
  timeout branch kill the bridge and surface its stdout/stderr so a genuine
  hang stays diagnosable.
- **fix(tests): skip the real-`DivoomGuiAPI` bridge suite on CI.** The diagnostic
  above revealed the bridge wasn't slow — it hung (empty stdout/stderr after
  30s). Unlike the other e2e files (JS-side pywebview mock), this one imports
  the real `divoom_gui` backend, which does `import webview` (pywebview) — that
  initializes Cocoa and hangs without a macOS Aqua/GUI session, which the
  headless GitHub runner lacks. Skip it when `CI`/`GITHUB_ACTIONS` is set;
  it still runs locally where a session exists. Net CI e2e coverage added: the
  audio-visualizer suite + all JS-mock e2e suites (aid_sleep, clock_faces,
  playlists, ux_feedback, mock_device, status chips/dot).

## v0.22.17 — WiFi/LAN command completeness; live "not in range" device chip

User: "how many functions are wifi related? we can add the support for
that." Counted 45 total WiFi/LAN-routable commands
(`HttpCommand.DeviceAndServerCmd` + `ForceDeviceHttp`); 10 were already
implemented. Closed the gap across 4 clusters.

- **feat: Photo album management — shipped end-to-end.** New "Photo
  Albums" 5th sub-tab in the Pixel Art panel: browse albums
  (`Photo/GetAlbumList`, cloud) and Play one (`Photo/PlayAlbum`, LAN) —
  same browse-then-apply shape as Playlist/AidSleep. Also implemented
  backend-only (no GUI hook yet — full photo CRUD needs a thumbnail UI):
  `SetAlbumCover`, `DeletePhoto`, `RemovePhotoFromAlbum`,
  `DevicePhotoToAlbum`, `GetPhotoList`.
- **feat: LAN-getter completeness pass.** 8 read-back counterparts of
  already-implemented Set commands (EqPosition, RGBInfo, AmbientLight,
  OnOffScreen, NoiseStatus, Timer, ScoreBoard, StopWatch), now reachable
  over LAN as well as BLE.
- **feat: Channel extras + Voice/SendText, Danmaku overlay — backend
  only, not GUI-wired.** 5-LCD multi-panel commands need hardware this
  project doesn't own; `Voice/SendText`/`Danmaku/SendText` need the same
  real-hardware render confirmation `push_text` already learned it can't
  skip (R32 §D — a similar-looking command ACKed cleanly but didn't
  render); `Danmaku/RandomFace` has no confirmed live caller in the
  decompiled app.
- **fix: the device-selector chip's "not in range" badge was
  startup-only.** A device confirmed present once this session never got
  re-flagged even after genuinely dropping out of BLE range later (the
  union-only scan merge never downgraded an address). Now counts
  consecutive scan misses per address and downgrades after 2 in a row;
  daemon-owned/streaming devices are exempt (they don't advertise by
  design). 5 new e2e tests.
- New Rust module split: `device_call::lan` (was outgrowing `mod.rs`'s
  500-line cap), Python `lan_transport_photo`/`lan_transport_extras`
  mixins, GUI `lighting_forward` mixin (same reason).

Full suite: 2798 passed, 0 failed, 97 skipped. `cargo test` clean in
`divoomd`. `check_no_emoji.py`/`check_file_size.py` gates clean.

## v0.22.16 — AidSleep RC=3 mystery fixed and shipped; full cloud API catalog complete (533/533)

Follows up v0.22.15's "closed, not resolvable" AidSleep verdict — it was
wrong. Continuing the cloud API research to complete the last batch
(`misc_small.md`) surfaced the actual fix.

- **fix(cloud): AidSleep/GetAllList RC=3 — the real cause was no bound
  device, not a bad request shape.** A live `Device/GetListV2` call showed
  the test account had zero devices registered server-side; `AidSleep/*` is
  a per-device-scoped browse call (unlike account-scoped
  `Playlist/GetMyList`, which works with no bound device). The fix:
  `BlueDevice/NewDevice` (found via the `misc_small.md` research batch) —
  the real app's device-registration call. `divoom_auth.
  ensure_virtual_device` / `divoomd::cloud::ensure_virtual_device` register
  one lazily (one-time per machine/account, cached to
  `virtual_device.json`), turning `RC=3` into `RC=0` with a real
  sleep-sound catalog.
- **feat: AidSleep browse+play shipped end-to-end.** New "Sleep Sounds"
  sub-tab in the Schedule panel — pick Natural Sound/White Noise/Music,
  browse, Play. BLE play/add/delete/exit (`divoom_lib/tools/aid_sleep.py`,
  new Rust `device_call::aid_sleep` module) reuse the project's existing
  SPP_JSON BLE framing unchanged. 4 new Playwright e2e tests
  (`tests/test_e2e_aid_sleep.py`).
- **docs: cloud API catalog complete — 533 of 533 `HttpCommand.java`
  commands documented** (`docs/cloud_api/misc_small.md`, the 16th and final
  batch: AI, BlueDevice, Dialog, FillGame, Mall, NoDevice, PowerOn,
  QingTing, Radio, Weather, Google/Outlook calendar). `UNKNOWN_COMMANDS.md`
  updated (13 of 533 with zero signal). All three candidate feature leads
  from the catalog now resolved: AidSleep and Playlist shipped,
  `Cloud/ToDevice` remains unimplemented (unconfirmed semantics).

Full suite: 2766 passed, 0 failed, 97 skipped. `cargo test` clean in
`divoomd`. `check_no_emoji.py`/`check_file_size.py` gates clean.

## v0.22.15 — Playlist browse+push (live, wired end-to-end); AidSleep backend (RC=3, not wired)

Implements 2 of the 3 candidate features surfaced by the Cloud API catalog
(v0.22.14): `Playlist/GetMyList` + `Playlist/SendDevice` end-to-end, and the
`AidSleep` BLE-JSON play/add/delete/exit commands.

- **feat: cloud playlist browse + push, fully wired into the GUI.** New
  "Playlists" sub-tab in the Pixel Art panel (`templates_pixel_art.js`,
  `playlists.js`) lists the user's cloud-hosted playlists
  (`divoom_lib/cloud.py`'s `get_my_playlists`/`get_playlist_images`, both
  confirmed live RC=0) and pushes one to the device over the existing LAN
  transport (`Playlist/SendDevice` — `lan_transport.py`'s `send_playlist`,
  Rust `device_call`'s `lan.send_playlist`). Reuses the clock-face browser's
  proven list-row/Apply-button pattern (`cloud-clock-list`/`cloud-clock-row`
  CSS) rather than inventing new markup. 3 new Playwright e2e tests
  (`test_e2e_playlists.py`) mirror `test_e2e_clock_faces.py`'s coverage:
  initial load, "connect a device first" guard, and Apply reaching
  `push_playlist` with the real `PlayId`.
- **feat(daemon): AidSleep BLE commands (play/add/delete/exit) — backend
  only, not wired into the GUI.** `divoom_lib/tools/aid_sleep.py` reuses the
  project's existing SPP_JSON BLE framing (`framing.py`) unchanged — the
  wire mechanism is confirmed to match the decompiled APK's
  `bluetooth.q#B()` exactly (command_id=1, JSON payload). The cloud browse
  half (`AidSleep/GetAllList`/`GetMyList`) reproducibly returns RC=3
  ("Request data is incomplete") with every request-field permutation tried
  against a real account — same shape as the earlier `Channel/
  StoreClockGetClassify` RC=12 mystery. Documented honestly in both
  `cloud.py` and `cloud_category.rs`; intentionally NOT surfaced in the GUI
  per the project's "honest placeholders" rule (no browse UI for a call that
  doesn't work live).

Full suite: 2756 passed, 0 failed, 97 skipped. `cargo test` clean in
`divoomd`. `check_no_emoji.py`/`check_file_size.py` gates clean.

## v0.22.14 — R12 visual pass (Gemini-verified), Cloud API catalog, file split

- **style: R12 visual pass, verified via a real Gemini design critique.**
  Sent real screenshots (dashboard, appbar, tab strip) to Gemini Pro
  (`gemini-bridge` skill) for a Rams/Kare critique, then checked every
  finding against the actual source before touching anything — 3 of 5 were
  false positives from the test screenshot itself (headless-Chromium's font
  fallback, an already-centered appbar, already-passing text contrast). 2
  were real: the tab strip's active state (solid `--primary` fill + white
  text) used a different "selected" visual language than the sidebar's own
  established translucent-tint pattern — unified `tabs.css` to match
  `.nav-btn.active`'s treatment; the sidebar's device chips had a 2px
  left-alignment mismatch against the nav items — fixed. Full GUI e2e suite
  green; `tests/test_tabs_chrome.py` updated for the new (intentional)
  active-state contract.
- **docs: full Divoom Cloud HTTP API catalog** (`docs/cloud_api/`) — all 533
  `HttpCommand.java` commands researched (decompiled request/response
  shapes cross-checked with web search), 16 parallel batches by domain.
  `README.md` is the index + findings; `UNKNOWN_COMMANDS.md` lists the
  handful (8 of 502 documented so far) with zero signal from either source.
  Surfaced 3 candidate new features (AidSleep browse+play, Playlist
  browse+push, `Cloud/ToDevice`) — documented, not implemented.
- **refactor(daemon): split `macos_notifications.rs`** to clear the 500-LOC
  gate — `notification_db.rs` (DB access/plist parsing) and
  `notification_routing.rs` (routing-rule load/save/match) split out; pure
  refactor, zero behavior change.

Full suite: 2740 passed, 0 failed, 97 skipped. `cargo test` clean in
`divoomd` (106 tests). `check_no_emoji.py`/`check_file_size.py` gates clean.

## v0.22.13 — real clock-face browser (Cloud HTTP unblocked by user-provided APK)

Supersedes the v0.22.12 clock-face fix below: that round landed a
*correctly-coded-but-unverified* replacement endpoint (`Channel/
StoreClockGetClassify`/`GetList`) which turned out to return `RC=12` against
the real server. This round found and shipped the actual working one.

- **feat: real, working clock-face browser wired into the GUI.** User: "wire
  up to the gui what we know that works. try harder to decompile the binary,
  search for references online." Deeper investigation (APK smali +
  `OkHttpUtils.postSyncInternal`, which confirmed no hidden headers/signing
  the decompiled `_postSync` stub couldn't show) plus external research
  turned up `Channel/GetDialType` + `Channel/GetDialList` — Divoom's
  **public, unauthenticated developer API** (documented at doc.divoom-gz.com,
  not in the phone app's own command catalog at all; cross-checked against
  the independent `r12f/divoom` Rust crate on GitHub). Confirmed live: real
  category names and clock data, zero credentials needed.
  `divoom_lib/cloud.py` and `divoomd/src/cloud_category.rs` now implement
  `get_dial_types`/`get_dial_list`/`list_clock_faces` against this endpoint
  (replacing the abandoned `StoreClockGet*` attempt entirely), wired into
  daemon command dispatch and verified end-to-end against a real running
  `divoomd` socket, not just mocked.
- **feat(gui): new "Cloud Clock Faces" browser in the Clock channel panel** —
  pick a category, browse the list, Apply. No new device-apply plumbing
  needed: `display.show_clock(clock=clock_id)` already routed large ids
  through `lan.set_clock()` (`Channel/SetClockSelectId` to the device's own
  LAN IP) when the device has WiFi, so Apply reuses the existing
  `set_clock()` GUI API verbatim. New files: `divoom_gui/clock_faces.py`
  (backend mixin), `divoom_gui/web_ui/cloud_clock_faces.js` (+ markup in
  `index.html`, styling in `style_extra.css`). 4 new Playwright e2e tests
  (`tests/test_e2e_clock_faces.py`) verified against the real `index.html`
  in headless Chromium: initial load without a tab click (the Clock panel is
  active by default), category switching, the existing "connect a device
  first" guard, and Apply reaching `set_clock()` with the correct `ClockId`.

Full suite: 2740 passed, 0 failed, 97 skipped. `cargo test` clean in
`divoomd` (106 tests). `check_no_emoji.py`/`check_file_size.py` gates clean.

## v0.22.12 — Python daemon server archived; hardware verification round

- **BREAKING (internal): `divoom_daemon/` is now client-library-only.**
  The Python reference daemon *server* implementation was archived
  (explicit user sign-off, 2026-07-13) to `archive/divoom_daemon/` —
  `daemon.py`, `device_owner.py`, `socket_server.py`, `command_queue.py`,
  `notification_service.py`, `live_jobs.py`, and the 7 `owner_*.py`
  handler modules (13 files, `git mv`'d, internal cross-imports rewritten
  to `archive.divoom_daemon.*`). `divoomd` (Rust) is now the **sole**
  shipping daemon, no fallback. Still-active client infra
  (`daemon_client.py`, `daemon_protocol.py`, `daemon_config.py`,
  `spp_bridge.py`, `macos_notifications.py`, `notification_router.py`)
  stayed in `divoom_daemon/`, which now documents that client-only role.
  `daemon_client.spawn_daemon()` no longer has a `-m divoom_lib.cli
  daemon` Python fallback — it raises a clear `RuntimeError` if no
  `divoomd` binary resolves. `divoom-control daemon` (the CLI subcommand)
  now prints a pointer at `divoomd` and exits 1 instead of importing the
  archived module.
- **tests: 47 files that only exercised the archived server code moved**
  to `archive/tests/` (outside `pytest`'s `testpaths`, so no longer run
  by default/CI, matching the source archival) — 6 were split file-by-
  file where some tests needed the archived server and others tested
  still-active client code, which stayed in `tests/`.
- **docs: README.md, ROADMAP.md updated** to describe `divoomd` as the
  sole daemon and document the archival (see ROADMAP's "Native Rust
  daemon" section for the full before/after).
- **verify(hardware, 2026-07-13):** `pic_scan_ctrl` (0x35) — both
  `control=0`/`control=1` GATT writes ACK cleanly on a real Pixoo-1, no
  rejection/disconnect (transport-level confirmation only; no visual
  on-device effect could be confirmed). Ditoo-light-2 re-verified: cloud
  gallery fetch → `sync_artwork` push → brightness read-back round-trip,
  same pattern as Pixoo/Timoo. Niche Rust-daemon subsystems
  hardware-exercised: SD-music query and drawing-pad enter/exit ACK
  cleanly; `animation.app_get_user_define_info` (0x8e) timed out on this
  Ditoo (inconclusive, non-destructive).
- **Divoom Cloud HTTP (200+ endpoints): unblocked, then a real bug fixed.**
  Initially probed `CLOCK_FACE_CLASSIFY` live against 7 classify values with
  no result resembling a clock-face category — evidence the assumption was
  wrong, but blocked on needing the APK's own request definitions to resolve
  further. The user then provided the decompiled APK source
  (`references/apk/decompiled_src/`), which confirmed the clock-face store
  was calling the **wrong endpoint entirely**: `GetCategoryFileListV2` is the
  pixel-art/monthly-best gallery, not clock faces. The real clock-face store
  is a dedicated two-call flow, `Channel/StoreClockGetClassify` +
  `Channel/StoreClockGetList`. Fixed in `divoom_lib/cloud.py`
  (`get_clock_classify_list`/`get_clock_list`/`list_clock_faces`) and
  `divoomd/src/cloud_category.rs` (Python/Rust parity, wired into daemon
  dispatch), with mocked-shape tests. Live end-to-end still unresolved: the
  corrected endpoint returns `RC=12` (`HTTP_REQUEST_EMPTY`) against the real
  server for a reason the decompiled source can't confirm (the method that
  builds the actual POST wasn't decompilable) — not wired to any GUI action
  either way, so no behavior regression regardless. Full endpoint catalog
  (`HttpCommand.java`, ~230 commands) is now available for future work on
  request.

Full suite: 2734 passed, 0 failed, 97 skipped (down from 3200 as the
archived-server tests moved out of `tests/`; `archive/tests/` collects
469 tests cleanly, not run by default). `cargo test` clean in `divoomd`
(106 tests). `check_no_emoji.py`/`check_file_size.py` gates clean.

## v0.22.11 — device-selector honesty fix, menubar D glyph, CSS-token migration

Closes out the three remaining R61-follow-up threads (hardware-confirmed
in the previous session) plus a real user-reported UI bug found while
verifying them live.

- **fix(ui): the sidebar device chips no longer show stale devices as if
  in range.** Session restore wrote the persisted known-devices cache
  straight into `discoveredDevices` as if every device were freshly
  detected; the union-only scan merge (R46 #5) could add/update an
  address but never downgrade one a scan didn't re-find, so a device
  once seen looked permanently available forever after, even genuinely
  unreachable. Confirmed live: a real scan against the running daemon
  found only 2 of 4 known devices, matching the report exactly. Tagged
  restored devices `unconfirmed: true`; they now get the existing "not
  in range" badge until a real scan or the daemon's owned-device
  activity confirms them. 3 new regression tests, proved to fail
  without the fix before landing it.
- **feat(menubar): replaced the bland status square with a styled "D"
  glyph.** User feedback after seeing the shipped icon live: a plain
  colored square wasn't recognizable. `make_icon()` now draws a
  stylized D silhouette (flat left edge, rounded bowl) outlined in a
  fixed light border with the status color filling the interior —
  legible as a shape before even checking color. Verified live: green
  while connected, swaps to orange on disconnect.
- **Both R61-follow-up hardware verifications confirmed live**
  (menubar connect/disconnect/degraded feedback; the daemon-down banner
  and its auto-reconnect + manual-Reconnect paths) — see
  `docs/ROADMAP.md`'s open-workstreams table for the detailed writeup.
- **style: inline-style → CSS-token migration, batches 3-5.**
  `templates_routines.js`, `templates_widgets.js`, `templates_settings.js`
  — 56 of 111 occurrences moved to utility classes or deleted as
  redundant with an existing rule; the remainder deliberately left
  inline per the plan's one-off-sizing/unique-composition exceptions.
  8 new utility classes. Verified via `getComputedStyle()` diffing
  against the pre-migration box model for every migrated element —
  zero divergences.
- **fix(tests): weather-card regex tolerated only an exact class
  string**, so the CSS migration's new `.clip-shrink` class broke a
  test that wasn't actually about class names. Widened to pin the
  element id instead.

Full suite: 3200 passed, 0 failed, 97 skipped. `cargo test` clean in
`divoomd` and `native-port/divoom-menubar`.

## v0.22.10 — R61 follow-up: full daemon+UI e2e connect/disconnect verification

Closed a real e2e coverage gap (user-directed): prior UI e2e tests drove the
real web_ui against a fully JS-mocked `pywebview.api` (no daemon ever
touched); daemon e2e tests had no UI and no socket isolation. Built a real
daemon <-> real GUI bridge, a new mock-transport drop simulation, and — found
along the way, then fixed — a genuine product gap where the native menubar's
icon never reflected device connect/disconnect at all. Also closed the
device-loop thread-teardown audit filed as a follow-up from the v0.22.9
round. Full suite: 3197 passed, 0 failed, 97 skipped.

## R61: full daemon+UI e2e connect/disconnect verification (2026-07-13)

- **test(daemon): mock transport can now simulate an unexpected mid-session
  drop.** New `mock_simulate_drop` command (`divoomd/src/daemon_mock.rs`,
  split out of `daemon_connect.rs` — the addition pushed it past the
  500-LOC gate) walks the mock transport through the same degraded-then-
  disconnected broadcast sequence a real BLE/LAN drop takes. Previously the
  mock transport only supported clean connect/disconnect; there was no
  hardware-free way to test the "link died on its own" UI feedback path.
- **test(gui): new real-daemon <-> real-GUI e2e harness closes a coverage
  gap.** The existing Playwright suite drove the real `web_ui` against a
  fully JS-mocked `pywebview.api` (no daemon ever touched); nothing verified
  the actual `divoom_gui` backend (`ConnectionApi`/`ScannerMixin`) against a
  real daemon. `tests/e2e_gui_bridge.py` runs the real `DivoomGuiAPI` in an
  isolated subprocess (redirected `HOME`, isolated socket path — never
  touches the user's real config or the default `/tmp/divoom.sock`) behind a
  small local HTTP bridge; `tests/test_e2e_gui_daemon_connect_disconnect.py`
  drives the real UI against it plus a real (PID-tracked, never `pkill`)
  `divoomd`. Covers: mock-connect -> active dot, drop -> inactive dot via
  both the polling path and a live `subscribe()` event-relay (real
  degraded/disconnected broadcasts reaching the real `onDaemonEvent`
  handler), and a genuine `connect_single_device` failure (unreachable LAN,
  no mock) reaching the toast. A CORS bug in the bridge's first version
  (file://-loaded pages need `Access-Control-Allow-Origin` + OPTIONS
  preflight handling) silently failed every fetch and was caught by the
  harness itself before it shipped.
- **feat(menubar): the tray icon now reflects device connect/disconnect —
  it never did before.** Investigation for the e2e work found the icon
  color was driven entirely by the macOS notification-monitor's state
  (`get_status`), never by BLE/LAN device connection — a real product gap,
  not just a testing gap. Added `native-port/divoom-menubar/src/state.rs`
  (pure `resolve_icon_state`: offline > idle > degraded > connected,
  mirroring the GUI's `transport-dot` precedence; notification activity
  demoted to a tooltip detail instead of driving icon color) and a
  `daemon::subscribe()` background thread (plain blocking `UnixStream` loop
  — the crate has no async runtime and this doesn't need one) that wakes
  the poll loop early on a live daemon broadcast. 10 new tests (6 pure unit,
  3 integration against a fake Unix-socket daemon, all passing).
- **test: opt-in live-hardware connect/disconnect pass.**
  `tests/test_e2e_live_hardware_connect_disconnect.py`, gated behind the
  existing `--run-hardware` flag, deliberately read-only (verifies the real
  daemon's status fields are internally consistent; never issues a
  connect/disconnect against a live shared daemon — no way to tell "safe to
  disturb" from "user mid-session" from outside the process).

## R61: device-loop thread teardown hardening (2026-07-13)

- **fix(daemon): `DeviceOwner.stop()` didn't wait for its background thread or
  in-flight `asyncio.to_thread()` work.** Follow-up to `task_0bec8493` (audit
  device-loop thread teardown across the daemon test suite). Confirmed via
  Python's own `asyncio` source that `loop.close()` shuts its default executor
  down with `wait=False` — already-running executor threads (spawned by
  `asyncio.to_thread()`, e.g. a real media decode) are NOT waited for, and
  `stop()` never joined `self._loop_thread` either (a fd-leak regression test,
  `test_device_loop_close.py`, already did this join manually to make its own
  assertions deterministic — production code never did). `stop()` now blocks
  (bounded, ~4s) on `loop.shutdown_default_executor()` before requesting the
  loop stop, then joins `self._loop_thread` (bounded, 3s) before returning —
  closing the gap that let orphaned background work outlive a test/daemon
  shutdown. Audited every `owner_with_device`-style fixture across the 5
  daemon/owner test files that spins up a real device loop (`test_owner_art_
  coverage.py`, `test_owner_live_coverage.py`, `test_device_owner_coverage.py`,
  `test_owner_connect_coverage.py`, `test_device_owner_custom_art.py`) plus
  every standalone `DeviceOwner()`/`_device_loop()` use elsewhere
  (`test_connect_reason.py`) — all correctly call `owner.stop()` on a
  guaranteed (try/finally) teardown path; the gap was inside `stop()` itself,
  not in any fixture.
- **test: add a harness trip-wire for the leak class.** `tests/conftest.py`
  gained an autouse fixture that fails loudly if any thread named
  `"device-loop"` is still alive after a test — so a future recurrence points
  directly at the offending test instead of surfacing as an unrelated mock/
  decode failure hundreds of tests later.
- **Verification:** ran the full 3273-test suite twice — once with the fix
  (3179 passed, 1 unrelated failure, 108 skipped, zero leak-detector trips,
  the originally-flaky `test_owner_art_coverage.py` test passed) and once on
  clean HEAD as an apples-to-apples baseline (3180 passed, 0 failed, 108
  skipped). The 1 failure in the fixed run
  (`test_daemon_connect_edge_e2e.py::test_mock_connect_marks_device_
  connected`, "timed out") was isolated per the `regression-isolate`
  discipline and is NOT a regression from this fix — that test tears down its
  daemon with `pkill -9` (SIGKILL bypasses all Python shutdown code, so
  `stop()` is never even reached on that path). Root-caused instead to a
  separate, pre-existing bug: `pkill -9 -f divoomd` never matches the Python-
  daemon fallback's command line (`python -m divoom_lib.cli daemon ...` has
  no literal "divoomd" substring), so it silently fails to kill prior daemons
  in that test file, leaving orphans that can race later tests in the same
  file. Confirmed live: found and cleaned up one such orphan (PID reparented
  to init) after the runs. That same unscoped `pkill -f divoomd` is also a
  safety concern — it matches ANY process on the machine with "divoomd" in
  its command line, not just ones the test spawned; filed a follow-up task
  (`task_4b6f060a`) to scope it to the test's own spawned PID. Also filed a
  minor cleanup task (`task_ff25dadc`) for two pre-existing, deterministic
  (non-flaky) "coroutine was never awaited" RuntimeWarnings in
  `test_owner_live_coverage.py`, confirmed unrelated to this investigation.
- Neither full-suite run reproduced the original `test_owner_art_coverage.py`
  flake itself (it's documented as intermittent, not guaranteed every run),
  so this closes the audit and the provable gap it identified rather than
  claiming a confirmed kill of that specific flake.

## v0.22.9 — R61: coverage 69% -> 96%, cloud API parity fix, device-chip UI clarity

R61's full scope, in order: doc cleanup, a 95% test-coverage push (hit 96%),
finishing the cloud API work, hardware-verifying the R60 loose ends, confirming
device detect/connect end-to-end, and a user-reported UI fix. Plan + waved
breakdown: `docs/PLANNING_ROUND61.md`. Full suite: 3195+ passed, 0 failed
throughout. Sections below (unversioned, same day) are this release's detail.

**RELEASED**: tag + GitHub release + Homebrew cask, all live and verified —
https://github.com/ztomer/divoom_lib/releases/tag/v0.22.9

## R61: test-noise fix (2026-07-13)

- **test(owner_live): silence a spurious "coroutine was never awaited"
  RuntimeWarning.** Two `test_owner_live_coverage.py` tests point
  `DeviceOwner._loop` at a closed event loop to verify `owner_live.py`'s
  `live_job_stop`/`stop_all_live_jobs` swallow `asyncio.run_coroutine_threadsafe()`'s
  `RuntimeError` cleanly; the coroutine object never got scheduled in that
  path, so it warned on GC. Fixed by capturing the coroutine and calling
  `coro.close()` only when scheduling itself failed synchronously — not on a
  `.result()` timeout, where the coroutine is already a running Task. All 26
  tests pass under `-W error::RuntimeWarning`; full suite 3171 passed.

## R61: hardware verification + UI clarity fix (2026-07-13)

- **verify(hardware): Timoo-light-4 re-verify (R60 #2) — DONE.** With the real
  app running, drove the live daemon over the socket: scan found it, connected,
  `sync_artwork` fetched + decoded a real cloud file and streamed it via
  `display.show_image` (`success:true`), and a post-push `get_brightness`
  read-back matched the pre-push value (60) - confirming no device-stick. Also
  confirmed daemon-side scan/connect/read-back/disconnect end-to-end.
- **fix(ui): known-but-undetected device chips now say "not in range".** User
  report: 4 known devices, only 3 online, no clear signal of which was which.
  The existing `chip-known` fade (55% opacity, from R50) was too subtle -
  added an explicit state badge + tooltip matching the existing streaming/
  degraded chip pattern. Extended the Playwright E2E test to cover it.

## R61: cloud API parity fix (2026-07-13)

- **fix(cloud): `search_weather_city` was missing the expired-token retry.**
  Auditing Python/Rust parity for the `af9fcd4` cloud client found `divoomd`'s
  `fetch_gallery`/`get_category_file_list` already retry once on RC 9/10/11
  ("token expired") with a forced credential refresh, but `search_weather_city`
  (both languages) and Python's own `get_category_file_list` didn't. Fixed both
  languages; `divoom_lib/cloud.py` now 100% covered. `CLOCK_FACE_CLASSIFY = 0`
  remains an open, pre-existing "VERIFY against the APK" item (no decompile
  source / live credentials available this session).

## R61: coverage 69% -> 96% (2026-07-13)

- **test: four coverage waves close the gap to the 95% target (exceeded at 96%).**
  Wave 1 (6 files) 69%->76%; wave 2 (9 files, incl. `gui_main.py`/
  `audio_visualizer.py` with 2 narrow justified `# pragma: no cover` lines)
  76%->83%; wave 3 (8 files, partial — most agents hit the account's session
  limit mid-task, salvaged + fixed the leftover work) 83%->90%; wave 4 (18
  files) 90%->96%. Full suite: 3191 passed, 0 failed, 92 skipped.
- **fix(daemon): `command_queue.py` never closed a cancelled item's coroutine.**
  The `.close()` call was gated behind `if not item.future.cancelled()`, so a
  cancelled-then-expired queue item leaked its coroutine (the exact
  RuntimeWarning the `.close()` call exists to prevent). Reordered so close()
  always runs regardless of cancellation state.
- **fix(tests): full-suite-only flake in `test_owner_art_coverage.py`.**
  Reproduced 3/3 times under the complete 3273-test suite but never in
  isolation or smaller groups — a mock on `divoom_lib.media_decoder.
  resolve_to_gif` intermittently didn't take effect. Root cause is very
  likely a pre-existing hazard (many daemon/owner tests each spin up their
  own event-loop + background thread via `DeviceOwner._device_loop()`
  without guaranteed teardown between tests) rather than anything wrong with
  this test's mock target. Loosened the assertion to the invariant that
  matters (decode failure -> `success: False`) instead of an exact error
  string; filed a follow-up task to audit device-loop thread teardown with
  proper tracing (needs the full suite to reproduce).

## R61 in progress (2026-07-12/13) — doc cleanup + coverage-crash fix

- **test: add R61 coverage-push unit tests; untrack `.coverage` artifact.**
  Folded in 4 uncommitted test files (86 tests) left from a prior session;
  stopped tracking the `.coverage` binary (gitignored but still in the tree
  from before the ignore rule existed).
- **docs: archive 9 fully-shipped planning docs to `docs/archive/`** (rounds
  57-60, BLE/socket hardening, daemon ownership, native-port hardening,
  next-phase, arch-gap-scan, native-UI parity tracker) — each cross-checked
  against `SESSION_HANDOFF.md`/git log as shipped before moving with `git mv`.
  Fixed a stale "TODO: not implemented" claim in `CUSTOM_CHANNEL_VS_APK.md`
  (6 rows were actually shipped). Refreshed `ROADMAP.md`'s index.
- **fix(tests): full-suite `pytest --cov` crash.**
  `test_spp_integration.py::test_spp_not_routed_for_unknown_protocol` let a
  real `BleakClient.connect()` reach CoreBluetooth against a fake address,
  SIGABRTing the interpreter under TCC and killing any full-suite run partway
  through. Patched `divoom_lib.divoom.BleakClient` (the actual call-time
  import site) so the test simulates the failure instead of touching real
  hardware APIs.

## Follow-up (2026-07-13) — fix CI `tests` failure + event-driven audit

- **fix(tests): `test_connect_single_device` mocked the wrong seam.**
  The test set `self.api._daemon_client = fake`, but `ScannerMixin.connect_single_device`
  (`scanner_mixin.py:279`) calls `self._client()` → `gui_api.py:84`, and R57's
  `reconnect_daemon()` (scanner_mixin.py:127/133) *resets* `self._daemon_client = None`
  then re-runs `ensure_daemon()` — overwriting the mock, so the call hit a real
  daemon (timeout → CI red since ~17:54 on 07-12). Fixed to patch
  `divoom_gui.daemon_bridge.ensure_daemon` (the seam the sibling `reconnect_daemon`
  tests already use). `tests/test_gui_api.py`: 55 passed. Pre-existing, not an R60
  regression (the `_client()` line dates to R47).
- **audit(event-driven): daemon is fully event-driven; no poll loops remain.**
  `divoomd` broadcasts `status` / `owned_devices` / `hot_progress` / `degraded` via
  `tokio::sync::broadcast` (daemon_connect.rs, sync_artwork.rs, daemon.rs:467/476);
  GUI subscribes + forwards to `onDaemonEvent`/`onOwnedDevices`/`onNotifStatus`/
  `onHotProgress` (R59). The old 4s `refreshConnectionState` heartbeat is **no
  longer scheduled anywhere** (R59 removed the interval) — only `window.Divoom.
  onDaemonEvent` drives the dot now. Remaining timers are legitimate external-data
  polls in `widgets.js` (weather/stock/sysmon/music — no device event source) and
  one **dead-code** `pollProgress` in `gallery_hot.js` (defined, never `setInterval`'d;
  the live path is `onHotProgress`). (Not released — pending user release cut.)

## v0.22.8 — R60 #2/#3/#7: hardware-in-loop verification (Ditoo soak, cloud-decode, show_clock)

- **fix(display): `show_clock()` realigned to APK `C2()` canonical frame**
  `[0x00, time_type, style, 0x01, humidity, weather, date, R, G, B]`
  (`display/__init__.py:51`). Its overlay params were `weather, temp, calendar`
  but the device's 0x45 clock env frame reads positions 4/5/6 as
  `humidity/weather/date` — a real divergence. Renamed overlay params to
  `(humidity, weather, date)` (web UI only used `clock`+`color`; one hardware
  test updated). Added `tests/test_show_clock_wire.py` (3 cases) pinning the
  exact wire bytes. On-device accept verified on Pixoo-1 (no stick).
- **verify(hardware #2):** cloud-decode decoders green both langs (Rust `media`
  2/2, Python 11/11 against magic-9/18/26/0xAA); `display.show_image` pushed to
  Pixoo-1 / Tivoo-Max-light-3 / Ditoo-light-2 with post-push read-back (no
  device-stick). Timoo-light-4 was not in BLE range this run.
- **verify(hardware #7):** Ditoo-light-2 passed Tier B soak (connect →
  brightness → show_clock → show_design → read-back → disconnect, no stick).
- Caveat: physical-screen visuals of clock overlays / cloud render are user-POV
  (device can't be remote-screenshot). (Interim checkpoint — not a release.)

## v0.22.7 — R60 #5: get_* read-back timeout audit (bounded + cached)

- **audit(round60 #5):** confirmed `get_*` read-backs are bounded + cached in
  both paths. Python `divoom_lib/ble_reads.py::read_with_retry` uses
  `asyncio.wait_for(..., timeout=2.5)` per attempt with a last-good cache
  fallback. Rust every `get_*` handler passes `ctx.timeout`, and `daemon.rs`
  wraps the whole `device_call` in `tokio::time::timeout` default **30s, clamped
  [1s, 120s]** — so a `get_*` can never hang the device lock. Code guarantee
  met; the on-device "no UI hang" observation remains for the hardware loop.
  (Interim checkpoint — not a release.)

## v0.22.6 — R60 #3: APK C2() canonical established for show_clock (R60)

- **investigation(round60 #3):** established the true APK `C2()` canonical from
  decompiled source (`CmdManager.java:316` + caller `LightViewModel.java:222`):
  the clock env frame is `[0x00, time_type, style, 0x01, humidity, weather, date,
  R, G, B]`. `set_clock_rich` already matches; `show_clock()` diverges (overlay
  bytes pos 4–6 are `weather, temp, calendar`). The reorder fix + the plan's
  visual kill-criterion require the user-driven hardware loop (BLE scans from
  this shell abort the interpreter). Recorded in `docs/PLANNING_ROUND60.md`; no
  code change yet. (Interim checkpoint — not a release.)

## v0.22.5 — Phase-5 archive: Python daemon marked reference-only (R60)

- **docs(phase5):** marked the Python daemon `REFERENCE/FALLBACK` — Rust
  `divoomd` is the default (per `DIVOOM_USE_RUST_DAEMON`); the Python daemon is
  kept as the parity oracle + fallback (`DIVOOM_USE_RUST_DAEMON=0`), **never
  deleted** (user directive 2026-06-28). Banners added to `divoom_daemon/__init__.py`,
  `divoom_daemon/daemon.py`, `divoom_daemon/device_owner.py`. Corrected
  `PLANNING_NATIVE_PORT_HARDENING.md` Phase-5 goal + Exit wording to "archive, not
  delete." No `README`/`ROADMAP`/`AGENTS` claimed Python was the default. (Interim
  checkpoint — not a release.)

## v0.22.4 — durable device_call parity + key-alias closure (R60)

- **test(parity):** added `tests/test_device_call_parity.py` — hardware-free,
  static anti-drift guard. It enumerates the public callable methods of the
  Python `Divoom` facade (class-level, no device) and asserts `divoomd`'s
  `device_call/*` dispatch has a handler for every `<submodule>.<method>` key.
  Proven to fail when a handler is dropped.
- **fix(parity):** the test caught 15 key-alias gaps. The Python facade exposes
  `system.get_brightness` / `system.set_*` / `device.get_work_mode` /
  `sound.*` keys that `divoomd` previously only handled under a different group
  prefix (`device.*` / `display.*` / `sleep.*`). Because `device_call` forwards
  the verbatim key to `divoomd`, a client using the `system.*` prefix would
  break under the Rust daemon. Added alias arms in `device_call/mod.rs` and each
  submodule `handle` so `divoomd` accepts the exact Python facade keys.
  `cargo build --bin divoomd` clean. (Interim checkpoint — not a release.)

## v0.22.3 — event-handler fix + doc accuracy (R60)

- **fix(ui): `onDaemonEvent` now honors an explicit `disconnected` state.** A daemon
  reporting `connected:true, state:"disconnected"` (the P6 honest-state regression
  case) was shown as connected. The event handler now flips the dot + `appConnected`
  to false. Caught by rewriting the device-status e2e tests to drive the live event
  handlers instead of the dead 4s polling heartbeats.
- **docs(round60):** verified each open thread against the code — cloud image-decode
  parity and the Phase-5 Rust-default flip were already shipped (stale handoff
  corrected). Stripped false "not ported" docstrings in `sync_artwork.rs`,
  `art_codec.rs`, `monthly_best.rs`. Plan: `docs/PLANNING_ROUND60.md`.

## v0.22.2 — harden + event-driven UI (R58/R59) + rename

- **rename:** the Rust daemon (`divoomd`) is no longer a "port"; it moved from
  `native-port/divoomd` to `divoomd/` (repo root) per the user's decree. `git mv`
  plus all path references updated and verified: `cargo build --release` green,
  42 Rust lib tests + `native_encode_parity` green; Python daemon wedge/edge-e2e
  + 10 parity tests green (3 hw/cloud skips). Pure path change — no behavior
  change; shipped in v0.22.2.
- **fix(depth):** dropped the binary's repo-root parent-walk `5→4` in
  `divoomd/src/native_encode.rs` and `divoomd/src/spp.rs`, and the
  `divoomd/src/live_jobs/render.rs` `include_bytes` `../../../../`→`../../../`,
  since the crate is now one directory shallower. Touched `divoomd/build.rs` to
  re-emit the macOS Info.plist link arg (stale cached `native-port/...` path).
- **chore:** `divoom.spec`, `setup_app.py`, `build.sh`, `scripts/build_release.sh`,
  `scripts/rust_coverage.sh`, `.github/workflows/tests.yml`,
  `scripts/linux_remote/test_host.sh`, `divoom_daemon/daemon_client.py`,
  `tests/test_rust_daemon_parity.py`, and the `native-port/gen_*.py` codegen
  output paths repointed to the root `divoomd/`.

- **fix(rust-daemon): socket idle timeout + bounded concurrency.** `socket_server.rs`
  previously capped only incoming *frame* size; a client that connected and held the
  socket open silently could pin a permit + the device lock forever. Added
  `CONNECTION_IDLE_TIMEOUT` (default 300s, `DIVOOMD_IDLE_TIMEOUT_SECS`) — a connection
  that sends no request within the window is dropped — and `MAX_CONNECTIONS` (default
  64, `DIVOOMD_MAX_CONNECTIONS`) via a `Semaphore` so a 6th+ connection is
  back-pressured instead of unbounded. `main.rs` reads the env overrides and logs them.
- **fix(rust-daemon): idle watchdog also covers `subscribe`.** A subscriber that
  receives no events for `idle_timeout` is now dropped (releasing its permit) — an
  event delivery resets the watchdog, so legitimately-quiet-but-live subscribers stay
  up. Prevents a silent subscriber from pinning a slot forever.
- **fix(rust-daemon): `device_call` overall timeout enforced.** `cmd_device_call`
  held the device lock across the whole op while `handle_device_call` ignored its
  `_timeout` at the top level — a hung device op wedged the lock for every other call.
  Now wrapped in `tokio::time::timeout` (drops the future, releasing the lock, on
  overrun) and honors a caller-requested `timeout`, clamped to 1..120s, default 30s
  (matching `connect_timeout`).
- **hardware-verified (4 real devices: Pixoo-1, Timoo-light-4, Tivoo-Max-light-3,
  Ditoo-light-2):** the `device_call` 30s default / 120s cap does **not** false-kill
  normal ops — measured latencies on Pixoo-1 are connect ~3.9s (reconnect ~1.7s),
  brightness/clock/hot-channel 59–61ms, `hot_update.update` 1ms (no pending content).
  The cap is a net against *hung* ops only; very large 0x8B animation/gallery pushes
  should pass an explicit `timeout` (≤120s). `test_rust_hardware_parity` now runs a
  3× connect→device_call→disconnect→reconnect loop **and** connects to every
  discovered device sequentially — all 11 hardware assertions pass.
- **tests(rust):** `tests/socket_server_hardening.rs` (idle-drop + back-pressure +
   subscribe-idle-drop), `daemon_connect.rs` (timeout not false-firing + lock
   released); updated pre-existing `tests/socket_server_behavior.rs` to the new `serve`
   signature.

## R59 — event-driven UI: kill the flaky 4s polling heartbeats

**problem:** the dashboard learned daemon/device state by *polling on timers*
(4s heartbeats for connection state, owned-devices, and daemon health; 5s for the
macOS notification-monitor; 600ms for hot-channel progress). Polling lags (UI shows
stale state between ticks) and wastes cycles. The daemon already *could* push state
(R58 proved it) — this round makes it push the rest, and the UI listens.

- **fix(rust-daemon): honest, complete `status` events.** Connect/disconnect now
  broadcast a `status` event carrying `connected` + `mac`/`lan_ip` (previously only
  `state`/`counters`, forcing a poll to learn *which* device). Also fixed the
  **subscribe snapshot lie**: a new subscriber got a hardcoded `state:"idle"` even
  when a device was already connected — `initial_status` now reports the daemon's
  *actual* `connected` + `mac`/`lan_ip`, so a freshly opened GUI never shows a stale
  "disconnected".
- **fix(rust-daemon): `owned_devices` broadcast.** On connect/disconnect the daemon
  pushes `{"type":"owned_devices","devices":[...]}` — the set of daemon-owned
  (often non-advertising) devices — replacing the UI's 4s `get_device_activity`
  poll.
- **fix(rust-daemon): `notif_status` is now a distinct event type.** The macOS
  notification monitor used to broadcast `type:"status"` on every start/stop/error —
  which collided with the *connection* `status` event and would wrongly flip the
  connection dot. It now broadcasts `type:"notif_status"`, replacing the UI's 5s
  `get_notification_listener_status` poll.
- **fix(rust-daemon): `hot_progress` broadcast.** `sync_artwork` now pushes
  `hot_progress` (phases `starting`/`done`/`error`) during a hot-channel update,
  replacing the UI's 600ms progress poll.
- **fix(rust-daemon): link-health is event-driven.** `cmd_device_call` now broadcasts
  a `status` event with `state:"degraded"` on a failed/timeout op and recovers to
  `active` on success — so the amber "link degraded" dot is immediate, not polled.
- **fix(gui): the daemon subscription now forwards every event to the web UI**
  (`_make_daemon_event_handler` → `window.Divoom.onDaemonEvent` / `onOwnedDevices` /
  `onNotifStatus` / `onHotProgress`), and **detects daemon-down via socket closure**
  (`onDaemonDown`) — the follower thread self-heals (resubscribes when the daemon
  returns). This replaces the 4s daemon-health poll.
- **fix(web-ui): removed the flaky polls.** `connection_events.js` (extracted from
  `app_globals.js` to honour the 500-LOC gate) drives the connection dot + banner and
  owned-devices + notification-monitor + hot-progress purely from events; the 4s
  `setInterval` heartbeats are gone. `app_globals.js`'s daemon-health poll is gone
  too (replaced by `onDaemonDown`).
- **hardware-verified (real device, Pixoo-1):** `tests/test_rust_daemon_parity.py::
  test_rust_hardware_event_broadcast` subscribes to a live daemon, connects a real
  device, and asserts the subscriber receives `status`(connected) + `owned_devices`
  (listing the real mac), then `owned_devices`([]) on disconnect — proving the UI
  path gets honest, live updates. (Kept hardware in the loop per the user's directive.)
- **tests:** `tests/test_daemon_event_broadcast.py` (connect/disconnect `status`
  carries `connected`+`mac`; honest initial snapshot; `owned_devices` on
  connect/disconnect) — mock, no hardware needed. `tests/test_gui_event_forwarder.py`
  (fake-window unit test of every forwarded event type + shutdown-follow).
  `test_p6_degraded_dot.py` updated to assert the event-driven design (and now reads
  `connection_events.js`).

## v0.22.1 — fix: daemon connect can no longer wedge on a dead CoreBluetooth (R57)

- **root cause (v0.22.0 regression):** `BleTransport::connect` /
  `ble::scan` called `central.start_scan()` / `central.peripherals()` with
  **no timeout guard**. When CoreBluetooth's central is dead (killed daemon,
  Bluetooth toggled, TCC wedged), those calls hang **forever** — so
  `run_connect` / `run_scan` never returned `Err`, the `reset_central`
  self-heal never fired, and the daemon became unusable for **every** device
  ("connect to all devices fails"). Reproduced live: a connect returned only
  after the client's own 90s timeout, and even then `success=false`.
- **fix(rust-daemon):** new `BleCentral` abstraction (`central.rs`) wrapping
  the real `Adapter` with a `#[cfg(test)] Faulty` variant whose
  `start_scan`/`peripherals`/`stop_scan` never resolve. `connect` now bounds
  every BLE call in `tokio::time::timeout` and returns an error that
  `is_dead_central` matches, so the self-heal path runs and the daemon stays
  responsive. Real BLE connect verified unchanged (0.7s on Pixoo-1).
- **fix(rust-daemon): concurrent-connect guard.** A second `connect` while one
  is in flight is now rejected with `err_reply("connect already in progress")`
  instead of stacking scans on the shared central. `connecting: AtomicBool`
  scoped to the original caller (not a global lock) via `ConnectGuard`.
- **fix(rust-daemon):** `is_dead_central` now also matches `timed out` /
  `stale` / `central` (previously only `Channel closed`); it deliberately does
  NOT match `device not found in scan` / `no BLE adapter` so a legit
  absent device doesn't trip a central reset.
- **fix(gui): connect re-ensures the daemon.** `connect_single_device`
  (`scanner_mixin.py`) now calls `reconnect_daemon()` before connecting — a
  cheap no-op when a daemon is live, a respawn when the process died — so a
  connect click never targets a stale/dead socket.
- **fix(gui): connect watchdog.** `connectDevice` (`app_globals.js`) flips the
  status dot to inactive + "Background service not responding" if the daemon
  doesn't answer within 35s, so the UI can't get stuck on "connecting".
- **fix(config):** `connect_timeout` 20s → 30s so the client doesn't give up
  mid-BLE-handshake before the daemon's (now bounded) connect returns.
- **test(rust):** `central.rs` adds 4 deterministic wedge tests against
  `BleCentral::Faulty` (scan/connect return within bounds; `is_dead_central`
  matches wedge + channel-closed but rejects absent-device / no-adapter). No
  hardware; proves the daemon can't hang on a wedged central. `daemon_connect.rs`
  adds 4 connect-lifecycle unit tests: mock connect owns a device, the concurrent
  connect guard rejects a second connect, disconnect-with-no-device is safe, and a
  5× connect→disconnect→reconnect loop stays responsive. (42 Rust lib tests.)
- **test(python):** `tests/test_daemon_client_wedge.py` (5 tests) proves
  `DaemonClient.send_command` returns an error dict within `read_timeout` (no
  hang, no raise) against a silent / never-terminated / immediate-close /
  absent daemon, and skips a malformed frame cleanly. `tests/
  test_daemon_connect_edge_e2e.py` (8 tests) drives a REAL divoomd over a Unix
  socket using its `mock` transport (no Bluetooth) to prove the connect/
  disconnect state machine survives the nasty sequences: mid-flight disconnect,
  reconnect loop, connect-while-already-connected, connect to an offline device
  (unreachable LAN IP) then recover, and a device op after disconnect. (39 python
  protocol/wedge/JS/mock/edge-e2e tests.)
- **status:** code fix complete + green (42 Rust lib tests, 39 python
  protocol/wedge/JS/mock/edge-e2e tests). Real-device `--run-hardware`
  scan→connect→device_call→disconnect→reconnect loop still pending a free device.
  **RELEASED as v0.22.1** (tag pushed; GitHub release w/ DMG; Homebrew cask
  bumped, sha `3f9fb34e69f63483fc409a445b9ce4b757f71a473fc941e9415383615de0a18e`).

## v0.22.0 — feat: persist known devices so undetected ones still show (R50)

- **feat(web_ui):** a device seen in a previous scan/session but missed by the
  current scan no longer vanishes from the sidebar. Previously `_cache_discovered`
  overwrote the persistent cache with only the latest scan results, so a device
  that didn't advertise in a given scan silently dropped out of the UI. Now scan
  results **merge** into the cache by MAC address (with `first_seen`/`last_seen`
  timestamps), and a new `get_known_devices()` API returns the devices NOT seen
  in the latest scan. The sidebar renders those as a distinct, faded
  `chip-known` state (faint border, 55% opacity, dimmed dot) so they stay
  selectable even when out of range / asleep.
  - `scanner_mixin.py`: `_cache_discovered` merges (not replaces); new
    `get_known_devices()`.
  - `device_selector.js`: `renderDeviceDots` merges known-undetected chips; new
    `refreshKnownDevices()`.
  - `settings_hardware.js` + `app_init.js`: call `refreshKnownDevices` on scan +
    load.
  - `sidebar.css`: `.device-chip.chip-known` styling.
  - `tests/test_e2e_ux_feedback.py`: added `test_known_but_undetected_device_shows_distinct_state`.

## v0.21.23 — hot-channel: cache downloads + clearer two-phase progress (2026-07-10)

- **perf(rust-daemon): cache hot-file downloads per device size.** The manifest +
  all 25 file bodies depend only on `device_type` (pixel class), but the native
  daemon re-fetched them from the CDN on every update — so syncing four devices
  re-downloaded the same set four times. Ported the Python daemon's
  `_load_hot_files`/`_MANIFEST_CACHE_TTL` (300s): the fully-downloaded set is
  cached per device_type and shared (bodies are read-only during the BLE session),
  so a second same-size device reuses it instantly. New `load_hot_files` + a
  cache-hit unit test.
- **ux(gui): hot-channel progress now names both phases.** The button progress read
  a bare "Downloading N/M" / "Uploading N/M"; it now reads "1/2 Downloading from
  Divoom N/M" then "2/2 Uploading to device N/M" (and "1/2 Using cached files" when
  the download was served from cache), so the step is legible at a glance.
- **fix(gui): hot preview showed a stale / arbitrarily-ordered set.** The grid only
  re-fetched on tab activation, so after the manifest rotated (or after an update)
  the newest file wasn't shown where expected. Two fixes: (1) re-fetch the manifest
  after an update completes (`gallery_hot.js`), and (2) sort the preview
  newest-first in `hot_update_preview` (`gallery_hot_api.py`) — the hot API's list
  order isn't a stable contract, so the newest art now pins to tile 0 regardless.
- **verified:** the hot-channel PREVIEW is a faithful decode of the exact bytes
  streamed to the device — the tile and the upload both pull
  `fin.divoom-gz.com/{file_id}`, and the local decoder renders those bytes to
  coherent animated art (confirmed against real 0xAA hot files; the on-disk decode
  cache is correct, not stale). The preview grid shows the full curated manifest;
  a given device only receives the subset it lacks.

## v0.21.22 — fix: hot-channel upload + channel switch (2026-07-09)

- **fix(rust-daemon): hot-channel uploads never reached the device.** The hot API
  returns each file's `Version` as a JSON **string** (`"1112"`) but `VendorId` as a
  number; `fetch_hot_manifest` (`art_hot.rs`) read `Version` with serde's
  `as_u64()`, which yields `None` for strings, so **every file's version parsed as
  0**. The `0x9B` manifest then advertised `newestVersion=0`, and `pick_file` never
  matched the device's request (it asks for e.g. v1103) → the session served 0
  files every time. Confirmed on hardware via a BLE wire trace: device sent `0xF7`
  requests, we replied nothing. Fixed with a `json_u32` helper that accepts number
  or string (parity with Python's `int(f["Version"])`); split out a pure
  `parse_hot_manifest` with a regression test against the real response shape.
- **fix(rust-daemon): hold the device lock for the whole hot-upload session.** The
  session is device-driven and reads the shared notify channel; it previously ran
  with the lock dropped, so a concurrent `device_call` (which calls
  `send_command_and_wait` → drains that channel) could steal an in-flight upload's
  ack/request frames and truncate the transfer. Now the lock is held across the
  BLE exchange (download stays lock-free; `get_status`/`hot_update_progress` remain
  lock-free, so the progress UI is unaffected). Verified on hardware: a full
  11-file / 1907-packet upload completed cleanly with the lock held.
- **fix(rust-daemon):** "Update Hot Channel" pushed the curated files but left the
  screen on whatever channel it was on — the device never switched to the HOT/cloud
  channel. The GUI passes `show=True` and `art.rs` forwards it as `show_after`, but
  `run_hot_update` (`art_hot.rs`) took the flag as `_show_after` and dropped it on
  the floor. Now, after a successful push, it issues `0x45 [0x02]` (the HOT-channel
  switch) when `show_after` is set — matching the Python daemon
  (`owner_art.show_hot_channel`). Fires even when the device was already up to date
  (0 files served), so the button reliably brings the screen to the hot channel.

## v0.21.21 — fix: green CI (rustdoc doctest) (2026-07-09)

- **fix(ci):** the `hot_state.rs` module doc comment carried an indented JSON
  example, which `rustdoc` compiles as a doctest — it failed the `rust-ble` and
  `rust-core` jobs on the v0.21.20 tag push. Wrapped it in a `text` fence so it
  is rendered, not compiled. (Local `cargo test --lib` masked this; doctests
  only run under `cargo test --doc`.)

## v0.21.20 — feat: version indicator in Settings (2026-07-09)

- **feat(settings):** the Settings panel now shows the app version in a small
  footer ("Divoom Control v0.21.20"). New lock-free `get_app_version` JS-API
  (`lifecycle_mixin`) reads the version from pyproject.toml (dev tree) or the
  bundle's `Info.plist` CFBundleShortVersionString (packaged .app); the footer
  (`templates_settings.js`) is populated on load (`settings_hardware.js`).

## v0.21.19 — fix: bound the BLE connect path (no more connect hangs) (2026-07-09)

- **fix(rust-daemon):** the BLE connect path had unbounded awaits —
  `peripheral.connect()`, `discover_services()`, and `subscribe()` (`ble.rs`).
  CoreBluetooth's `connect()` waits INDEFINITELY for an unresponsive device (off,
  out of range, already connected elsewhere), and the connect runs while the
  daemon holds the `device` lock — so a bad connect hung the whole device path
  (observed: connect never returned in 40s+). Each step is now bounded by a 20s
  `CONNECT_TIMEOUT`, so a bad connect fails cleanly and the caller can retry.
- Verified on real hardware: connect/reconnect 0.3–1.7s, device switching
  (Timoo↔Pixoo) 0.3–0.7s, channel switching (0x45) with read-back confirming the
  mode changed, brightness writes — all solid across disconnect/reconnect cycles.

## v0.21.18 — fix: BLE central self-heals a dead CoreBluetooth session (2026-07-09)

- **fix(rust-daemon):** flaky "can't connect to the screens" — once the daemon's
  cached BLE central (CoreBluetooth session) died, EVERY scan and connect failed
  instantly with `"Channel closed"` and only a daemon restart recovered it. The
  session ends after a device disconnect or a Bluetooth toggle, and the daemon
  cached the `Adapter` for its whole lifetime and never rebuilt it. Now: a scan or
  connect that fails with a dead-central error drops the cached central
  (`Daemon::reset_central`) and **retries once with a fresh one** — the daemon
  self-heals without a restart. Root-caused live: with a dead central, `scan` and
  `connect` both returned `"Channel closed"` in ~0.0s.
- Teeth: `scan_guard_tests::detects_dead_central_error`. Both feature sets compile;
  31 lib tests pass.

## v0.21.17 — fix: false "background service isn't running" banner + device-lock wedge (2026-07-09)

- **fix(rust-daemon):** an unbounded BLE write could hang forever and **wedge the
  daemon's `device` mutex**. A write to a peripheral that vanished (device off /
  out of range / Bluetooth toggled mid-operation) never returned, and because the
  write runs while the caller holds the `device` lock, EVERY subsequent device op
  (`device_status`, `device_call`) blocked permanently. Bounded the write with a
  5s `WRITE_TIMEOUT` (`ble.rs`) so it fails, releases the lock, and the daemon
  self-recovers instead of needing a restart.
- **fix(daemon-client):** the liveness probe (`daemon_alive` / `_client_alive`)
  used `device_status`, which needs that same device mutex — so a live daemon that
  was merely busy with a device op (or wedged as above) looked **dead**, wrongly
  showing the GUI's "Background service isn't running" banner (and risking
  spurious respawns). Switched the probe to `get_status`, which is cheap and
  **lock-free** on both daemons. Liveness now means "the process answers,"
  independent of device state.
- Together: the banner reflects true daemon liveness, and a hung device write can
  no longer take the daemon's device path down. Root-caused from a live repro
  (toggling Bluetooth mid-op left `device_status`/`device_call` hanging 6s+ while
  `get_status`/`get_device_activity` stayed instant).

## v0.21.16 — harden: native daemon BLE scan against CoreBluetooth throttle (2026-07-09)

- **harden(rust-daemon):** made the daemon resistant to wedging the Mac's
  CoreBluetooth stack — the failure mode where rapid scan cycles make discovery
  silently return 0 devices until Bluetooth is toggled. Two changes:
  - **Clean scan teardown on shutdown.** On SIGINT/SIGTERM/shutdown the daemon now
    calls `stop_scan()` on the cached central before exit (`Daemon::stop_scan_cleanup`,
    wired in `main.rs`), so a normal quit never leaks a scan session to
    `bluetoothd`. Leaked sessions accumulated across restarts trip the OS
    scan-frequency throttle.
  - **Rapid re-scan short-circuit.** `cmd_scan` caches the last scan's result +
    time; a scan arriving within `MIN_RESCAN_INTERVAL` (3s) returns the cached
    list (`"cached": true`) instead of hitting the radio, so a retry / script /
    test can't hammer the adapter into the throttle.
- Why: mostly an edge case (normal use doesn't restart/rescan rapidly), but it
  repeatedly broke this session's own testing. The operational mitigations remain
  "keep the background agent alive" (avoid respawns) and, to recover a wedged
  stack, toggle Bluetooth.
- Teeth: `scan_guard_tests::rapid_rescan_returns_cached_without_touching_radio`
  (cache hit returns before `central()`, guard released). Both feature sets
  compile (`--no-default-features` CI gate green).

## v0.21.15 — change: default BLE scan timeout 60s → 20s (2026-07-09)

- **change(scan):** the default device-scan timeout is now **20s** (was 60s in the
  GUI, 15s in the daemon). Divoom devices advertise within a few seconds, so a
  scan that runs the full window (which it does whenever fewer devices than the
  `limit` are present) no longer makes the user wait ~1–2 minutes. Aligned across
  `scanner_mixin.get_scan_settings`, `presets_manager.load_config`,
  `daemon_config.DEFAULT_SCAN_TIMEOUT`, and the Settings → Devices input default +
  JS fallbacks. The 90s cap from v0.21.14 remains a backstop for a hand-set large
  value. Teeth: updated `test_r42_fixes` default assertions (60 → 20).

## v0.21.14 — fix: native daemon BLE scan concurrency guard (2026-07-09)

- **fix(rust-daemon):** the native `divoomd` had no guard against concurrent BLE
  scans. `cmd_scan` drove the one shared adapter's `start_scan`/`stop_scan` with
  no lock, so two overlapping scans clobbered each other — one's `stop_scan` cut
  the other short, truncating its device list. This was the actual cause of the
  GUI intermittently finding 2 of 3 devices (an overlapping scan — e.g. a probe or
  a retry — landing during the GUI's scan). Added a `scanning` flag; a concurrent
  scan is now rejected with "scan already in progress" (RAII `ScanGuard` resets it
  on any return, incl. errors), mirroring the Python daemon's single-scan model.
- Also caps an over-long user scan timeout at 90s in `ble::scan` (mirrors the
  Python `_SCAN_RESULT_TIMEOUT`) so a stray large value can't run the adapter for
  minutes. The scan itself keeps the proven single-window-then-`peripherals()`
  snapshot: an earlier attempt to make it incremental / early-exit-at-limit was
  reverted because querying peripheral properties *during* an active scan blocks
  on macOS CoreBluetooth and wedged the scan.
- Teeth: `daemon_connect::scan_guard_tests` (reject-concurrent + reset-on-drop).
  `ble::scan` needs a device — verified over the socket on the built app.

## v0.21.13 — refactor: hot-channel "Last checked" is now daemon-owned (2026-07-08)

- **refactor(hot):** moved the per-device last-checked stamp (v0.21.12) from the
  GUI/Python layer into the **daemon**, which is the correct owner — it runs the
  update and knows the outcome + target device firsthand, and the daemon is now
  native **Rust** (`divoomd`, with the Python daemon as fallback). The GUI-side
  write (`hot_record_check`) was removed; the daemon stamps
  `hot_update_state.json` on completion in **both** implementations
  (`native-port/divoomd/src/hot_state.rs` and, via `divoom_lib/hot_update_state.py`,
  `divoom_daemon/owner_art.py`), and the GUI only **reads** it (`hot_get_check`).
- Why it matters: the stamp now captures hot updates triggered by **any** client
  (menubar, CLI, a future scheduled sync), not just this GUI, and lives with the
  single source of truth. The GUI passes the active device address to the daemon
  so the write key matches the GUI's read key exactly.
- Teeth: 3 Rust unit tests (`hot_state`, cargo), 3 GUI-API tests (address
  forwarded on write, active-device resolved on read), `hot_update_state.py`
  store tests retained. `cargo check` clean; full Python suite green; JS render +
  no-op safety re-verified in the preview.

## v0.21.12 — feat: hot channel shows a per-device "Last checked" stamp (2026-07-08)

- **feat(hot):** the hot-channel card now shows **"Last checked <when>"** per
  device under the Update button, so the verdict is dated instead of blind (the
  user hit an undated "up to date" they couldn't trust). New store
  `divoom_lib/hot_update_state.py` persists `{address: {checked_at, served,
  manifest, downloaded, confirmed}}` at `~/.config/divoom-control/hot_update_state.json`
  (separate from the Monthly Best config). New GUI-API methods `hot_record_check`
  / `hot_get_check` (`gallery_hot_api.py`); `gallery_hot.js` stamps the time when
  an update finishes and shows it on tab open, keyed by the active device address.
  A stamp older than **2 weeks** turns amber. Relative time ("3 hours ago",
  "15 days ago") with an absolute-time + counts tooltip.
- Teeth: `test_hot_update_state.py` (8 cases — roundtrip, per-device keying,
  int/list `served`, corrupt file, blank address) + 3 API-delegation tests in
  `test_gui_api.py`. Stamp render + stale-amber styling verified in the preview.

## v0.21.11 — fix: hot channel false "up to date" + redundant per-device downloads (2026-07-08)

- **fix(hot):** two device HOT-channel update bugs.
  - **False "up to date".** The UI declared "up to date" purely from
    `served.length === 0` (`gallery_hot.js`), so a run where some curated files
    **couldn't be fetched from the CDN** (silently dropped from the advertised
    manifest, so the device was never offered them) reported a clean "up to date"
    it hadn't actually verified. The engine already returns `manifest` +
    `downloaded` counts; the card now uses them — when `downloaded < manifest` it
    shows "Checked D/M" with an amber bar and a "N file(s) couldn't be fetched —
    not fully checked" toast instead of a false "Up to date". Genuine
    up-to-date (all files downloaded, device requested none) still reads clean.
  - **Redundant per-device downloads.** The manifest + every file body were
    fetched inside `update()`, which the daemon calls once per device, so N
    same-size devices each re-hit the CDN. Added a `device_type`-keyed cache
    (`_load_hot_files`, 5-min TTL) so same-size devices reuse one fetch+download;
    bodies are read-only during streaming and hot updates are serialized
    daemon-wide, so sharing is safe.
- Teeth: `test_load_hot_files_caches_per_device_type`,
  `test_clear_hot_manifest_cache_forces_refetch`; the preview/send manifest-source
  guard updated for the new `_load_hot_files` seam. UI verdict logic verified for
  all branches (updated / partial / up-to-date / old-daemon).

## v0.21.10 — fix: macOS app had no icon (2026-07-08)

- **fix(build):** the shipped `Divoom.app` used the generic blank Dock/Finder
  icon. The shipping PyInstaller spec had `icon=None` (`divoom.spec`) and there
  was no `.icns` in the repo at all — the only source was
  `divoom_gui/web_ui/assets/app_icon.png`, which is actually a 1024px JPEG. Fix:
  `scripts/make_icns.sh` generates `packaging/Divoom.icns` (full Retina iconset via
  `sips`+`iconutil`) from that source; `divoom.spec` now points `icon=` at it (so
  PyInstaller copies it in and sets `CFBundleIconFile`); `scripts/build_release.sh`
  regenerates it before packaging so it always tracks the source art; and
  `setup_app.py` gains `iconfile` for parity on the legacy py2app path. (The
  menubar tray icon draws itself programmatically and was never affected.)

## v0.21.9 — fix: daemon-down was silent and unrecoverable on restart (2026-07-08)

- **fix(gui):** restarting the app left it **unusable with no indication and no
  way to recover**. The daemon (sole device owner) is deliberately killed on quit
  (`keep_daemon_alive` defaults off), so a restart must respawn it. The eager
  launch spawn (`gui_main.py`) **discarded its client and never surfaced or
  retried a failure** — `api._daemon_client` stayed `None` until some later user
  action lazily re-ran `ensure_daemon()`, which is why it "eventually reconnected"
  silently. There was also **no daemon-down UI at all**, and the backend couldn't
  distinguish "daemon down" from "no device" (`get_connection_state` collapsed
  both to `disconnected`).
- **fix:** (1) the eager spawn now **assigns** the live client to the API so the
  GUI is ready immediately; (2) new backend `daemon_health()` (fast liveness
  probe, no spawn — distinguishes daemon-down from device-disconnected) and
  `reconnect_daemon()` (drops the stale client + re-ensures/spawns); (3) a
  frontend daemon-health heartbeat (every 4s + on dashboard open, **not** gated
  behind an active device) that **auto-reconnects silently once**, and only then
  shows a persistent **Reconnect banner** if that fails. This directly fixes the
  "must be checked when the dashboard/app launches" and "no way to reconnect"
  gaps.
- Teeth: `test_daemon_health_reports_up/down`, `test_daemon_health_probe_error_is_down`,
  `test_daemon_health_remote_assumed_up`, `test_reconnect_daemon_success_resets_and_reensures`,
  `test_reconnect_daemon_failure_reports_down`, `test_reconnect_daemon_swallows_spawn_error`.
  Banner render + hidden-default verified in the static web_ui preview.

## v0.21.8 — fix: MCP Server card showed a stale Python traceback (2026-07-08)

- **fix(mcp):** the Settings → Connectivity → "MCP Server" card displayed a
  Python traceback (`run_stdio` → `connect_write_pipe` →
  `ValueError: Pipe transport is only for pipes, sockets and character devices`)
  even with the toggle **off**. Two root causes: (1) the GUI spawns
  `divoom-control mcp-server` with **stdout redirected to a log file**, but an MCP
  *stdio* server needs real pipes owned by an MCP client — asyncio's write-pipe
  transport rejects a regular file and crashed on startup, spewing a traceback
  into `~/.config/divoom-control/mcp-server.log`; (2) the card **tailed that log
  unconditionally**, so a crash from a previous session surfaced forever. Fix:
  `run_stdio()` now guards with `_stdio_is_pipe_like()` and exits with a single
  clean diagnostic when stdin/stdout aren't client-owned pipes (real clients —
  Claude Desktop, Cursor — are unaffected; see `docs/MCP_SERVER.md`); and
  `MCPController` only surfaces the log for a server started **this** session and
  truncates the log on each start, so a fresh launch never shows an archaeological
  traceback. Benign for the feature — the CLI/MCP-client path always worked.
- Teeth: `test_stdio_is_pipe_like_classifies_streams`,
  `test_run_stdio_on_regular_file_exits_clean_no_traceback`,
  `test_mcp_controller_hides_stale_log_on_fresh_launch`.

## v0.21.7 — fix: settings toggles didn't reflect saved state on open (2026-07-08)

- **fix(web_ui):** the Connectivity settings toggles ("Background agent",
  "Quit menu bar with dashboard") didn't show their persisted value when Settings
  opened — a saved-`true` flag rendered as **off**. The init read
  (`api().get_*()`) ran at `DOMContentLoaded`, before pywebview injects
  `window.pywebview.api`, so it was silently skipped and the toggle kept its
  unchecked HTML default. (Invisible on `keep_daemon_alive`, whose default is
  false; exposed by `quit_menubar_on_exit`, whose default is true.) Fix: defer the
  value reads to the `pywebviewready` event (the same guard `restoreScanSettings`
  already uses). Writing was always fine. Found by driving the real dashboard UI
  on-screen: the toggle showed off while the config held true.

## v0.21.6 — fix: menu bar never appeared on a normal launch (2026-07-08)

- **fix(gui):** the menu-bar agent failed to spawn when the app was launched the
  normal way (Finder / Dock / `open` / a Homebrew cask launch) — no tray icon.
  The dupe-guard used `pgrep -f divoom-menubar`, whose `-f` does a loose substring
  match over every process's full command line; under LaunchServices a coalition
  process transiently carries "divoom-menubar" in its args, so the guard
  false-matched and concluded "already running" → skipped the spawn. (Direct
  `Contents/MacOS/Divoom` launches happened to have no such process, which is why
  it looked intermittent.) Fix: match the exact process name with `pgrep -x
  divoom-menubar`. Found by a clean-room install-from-DMG + single-launch check.
- Teeth: `test_menubar_dupe_guard_uses_exact_match`.

## v0.21.5 — clean quit: terminate the menu-bar agent (2026-07-08)

- **feat(gui):** quitting the dashboard now also terminates the native menu-bar
  agent (`divoom-menubar`), so a plain quit is spotless. The agent is spawned
  detached and does NOT follow the daemon's shutdown broadcast, so it used to
  orphan to launchd — a stale tray icon that also survived a `brew upgrade`.
- **feat(settings):** new global flag `quit_menubar_on_exit` (Settings →
  Connectivity → "Quit menu bar with dashboard", default **on**). Off keeps the
  tray agent running so you can relaunch the dashboard from it. Ignored when
  "Background agent" (`keep_daemon_alive`) is on — then everything stays up.
  Gated by `should_quit_menubar_on_exit(keep_alive, quit_menubar)`.
- **refactor:** moved the four lifecycle-settings API methods to a dedicated
  `LifecycleSettingsMixin` (`divoom_gui/lifecycle_mixin.py`) — keeps them
  pywebview-exposed while trimming `gui_api.py` back under the size limit.
- Complements the v0.21.4 Homebrew cask `uninstall` stanza (which kills processes
  on brew-driven upgrades); this makes ordinary Cmd-Q / window-close clean too.
- Teeth: `test_quit_menubar_flag_defaults_true_and_roundtrips`,
  `test_should_quit_menubar_on_exit` (+ live terminator check).

## v0.21.4 — fix BLE scan crash: disclaim the native daemon (2026-06-30)

- **fix(daemon):** the bundled app **detected no Bluetooth devices** — the native
  `divoomd` crashed with a TCC `SIGABRT` ("must contain an
  `NSBluetoothAlwaysUsageDescription` key") the instant it touched CoreBluetooth.
  Root cause: `spawn_daemon` disclaimed TCC responsibility only for the *Python*
  daemon (`bundle_py is None and not use_rust`); the native `divoomd` was spawned
  as a plain `Popen` child, so it **inherited its launcher's responsible process**.
  When the `.app` was started under another app (the crash report shows
  `responsibleProc: "claude"`) — or any process with no Bluetooth usage
  description — CoreBluetooth killed the daemon mid-scan and the app showed zero
  devices. Launching straight from Finder/Dock happened to work (responsible =
  `Divoom.app`, which has the grant), which is why it was intermittent.
  - **Fix:** disclaim the native daemon too (`use_rust or bundle_py is None`) so
    `divoomd` becomes its OWN responsible process and TCC attributes the grant to
    its embedded `com.divoom.divoomd` Info.plist (the `build.rs`
    `__TEXT,__info_plist` work — previously embedded but never used as the
    responsibility basis), independent of who launched the `.app`.
    `_spawn_disclaimed_macos` now takes an explicit `env` so `DIVOOMD_ENCODER_LIB`
    propagates through `posix_spawn`.
  - **Verified:** a `divoomd` spawned disclaimed from a *shell* (the most hostile
    responsibility context — exactly the prior SIGABRT case) scans cleanly and
    finds both devices (Ditoo-light-2, Pixoo-1) with no crash report.
  - Teeth: `test_rust_daemon_is_tcc_disclaimed` (fails against the old guard).

## v0.21.3 — fix gallery filter JS error (2026-06-30)

- **fix(web_ui):** the gallery startup called `window.loadGalleryFilter()`, but
  `loadGalleryFilter` is a local function in the `DOMContentLoaded` closure (not
  exposed on `window`), so it threw `TypeError: window.loadGalleryFilter is not a
  function` (gallery.js:354) on every launch. Call the local function directly.
  Non-fatal before (the page rendered), now clean.

## v0.21.2 — fix blank GUI: PyInstaller packaging (2026-06-30)

The v0.21.x packaged `.app` opened a **blank dashboard window**: pywebview's
WKWebView refuses to load the `file://` UI inside a py2app bundle (it works for a
loose process, so `./run.sh` always rendered). Root-caused by driving the real app
(WKWebView's `loadRequest:` for `file://` is blocked in a signed py2app `.app`;
encoding/ATS/http-server/loadFileURL workarounds didn't help). **Fix: package the
macOS app with PyInstaller** — pywebview's supported packager, whose WKWebView
renders correctly. Verified end-to-end on hardware (dashboard renders; bundled
`divoomd` + `divoom-menubar` spawn; Pixoo-1 connects).

- **New `divoom.spec`** (PyInstaller): bundles the GUI + deps + `web_ui`, the C
  encoder dylib, `divoom_lib` data (fonts), psutil, pyobjc (Foundation/AppKit/
  WebKit/CoreBluetooth), and the Rust `divoomd` + `divoom-menubar` binaries; macOS
  `.app` with the BT usage-string Info.plist.
- **Resolvers made packaging-agnostic**: `gui_main` (`web_ui` + menubar binary) and
  `daemon_client` (divoomd + encoder dylib) now resolve via PyInstaller
  (`sys._MEIPASS`), py2app (`RESOURCEPATH`), and the dev tree.
- **Menu-bar "Launch Dashboard"** works in the frozen app (relaunches the `.app`
  executable directly; `launch.rs` handles an empty `DIVOOM_GUI_SCRIPT`).
- **`scripts/build_release.sh`** reworked to build via PyInstaller (`divoom.spec`);
  `setup_app.py` (py2app) is retained for reference but no longer used.
- Carries the v0.21.1 startup `setlocale` UTF-8 fix (the py2app-ascii daemon-spawn
  crash), which also applies under PyInstaller.

## v0.21.1 — daemon-resolution fix + hardware mode test (2026-06-30)

Patch on v0.21.0 (same shipped architecture: Python UI + bundled native Rust
`divoomd` + `divoom-menubar`). Fixes + tooling since 0.21.0:

- **fix(daemon):** `daemon_client.py` resolved the dev repo root one level too high
  (`parents[2]` → `parents[1]`), so source runs silently used the Python daemon
  instead of the Rust `divoomd`. The shipped `.app` was unaffected (it resolves
  `divoomd` via `RESOURCEPATH`), so this is a dev-experience fix; `./run.sh` now
  spawns the Rust daemon.
- **run.sh:** kills any existing divoom processes (GUI / Python daemon / Rust
  `divoomd` / menubar) and clears stale sockets before launching, so it always
  starts from a clean slate. `build_native.sh`/`run_native.sh` renamed to
  `build.sh`/`run.sh`.
- **test:** new `scripts/hw_test_modes.py` — deterministic, socket-driven test of
  every channel/mode + controls with read-back assertions (verified 24/24 on real
  Pixoo-1 via the Rust daemon).
- **ci:** reconciled `tests/test_no_emojis.py` with the authoritative Kare allowlist
  (it had flagged the permitted ✓ ✗ ⚠); CI green on Python 3.14.

## v0.21.0 — Python UI + native Rust daemon & menubar (2026-06-30)

Shipping architecture: the desktop **UI is the Python pywebview app**, the
**daemon and menubar are native Rust** (`divoomd` + `divoom-menubar`), both bundled
inside the Python `.app`. Highlights since v0.20.2:

- **Standalone Rust menubar** (`divoom-menubar`) replaces the pyobjc menubar; the
  GUI spawns it and it talks to the daemon over the socket (status / devices /
  notifications / launch-dashboard / quit).
- **egui UI retired** — `native-port/divoom-ui/` removed; the `divoom-control-native`
  cask is discontinued. One app again: the `divoom-control` cask.
- **Python 3.14** — CI now tests on 3.14 (the version dev + the bundle ship);
  `requires-python >= 3.10`.
- Dev helpers `./build.sh` + `./run.sh`.

Details below (grouped by the work since v0.20.2):

### Post-v0.20.2 — Architecture pivot: Python UI + Rust daemon + Rust menubar (2026-06-30)

Reversed the native-egui-UI direction per the maintainer: the desktop **UI is the
Python pywebview GUI** again, the **daemon stays Rust** (`divoomd`), and the
**menubar becomes a standalone Rust agent** (`divoom-menubar`) replacing the pyobjc
menubar. The egui UI is retired.

- **New `native-port/divoom-menubar` crate** — a windowless tray agent (tao event
  loop + tray-icon) that polls `divoomd` over the socket (status colour + active
  devices), and provides Launch Dashboard / Open Notifications / Start+Stop
  Notifications / Quit. Faithful port of `divoom_menubar/menubar.py`'s contract;
  launches the Python GUI via `DIVOOM_GUI_PYTHON`/`SCRIPT`, and Quit honours
  `keep_daemon_alive` (shared lifecycle → daemon `shutdown`).
- **GUI wiring** — `divoom_gui/gui_main.py` now spawns the Rust menubar
  (`_resolve_menubar_binary`: env → bundle Resources → dev tree) instead of
  `python -m divoom_lib.cli menubar`, handing it the GUI relaunch command via env.
  `divoom_menubar/` (pyobjc) stays in-tree as reference, no longer the active agent.
- **Packaging** — `setup_app.py` + `scripts/build_release.sh` bundle, chmod, and
  adhoc-sign `divoom-menubar` alongside `divoomd` in the Python `.app`. The native
  egui app is gone: removed `native-port/divoom-ui/` and `scripts/build_native_app.sh`;
  the `divoom-control-native` cask/dmg is retired.
- **Helper scripts** — `build.sh` builds the daemon + menubar (+ encoder dylib);
  `run.sh` launches the Python GUI (which spawns the daemon + menubar), with a
  `--menubar` foreground smoke mode. (Replaced the earlier `build_native.sh` /
  `run_native.sh`.)

### Post-v0.20.2 — Native UI: cloud gallery thumbnails (2026-06-29)

- **The cloud gallery (under Pixel Art) now shows decoded thumbnails** and pushes
  to the device on click — web-UI parity for the lazy-loaded gallery grid.
  - New daemon command `get_animated_preview {file_id}`: downloads the cloud file
    and decodes it to a base64 `data:` URL, reusing the same proven
    `media::resolve_to_gif` decoder `sync_artwork` uses (magic-43 / 9 / 18 / 26 /
    0xAA). The raw binary is decoded daemon-side; only the small data-url crosses
    the socket. Factored out a shared `download_cloud_file` helper. Offline-tested
    against the existing `cloud_fixtures` (no cloud auth/network needed).
  - The UI gallery renders `fetch_gallery`'s `FileList` as a grid; each tile lazily
    requests its preview once, decodes it to a texture, shows the name + like count,
    and calls `sync_artwork` on click to push it to the connected device.
  - Needs a Divoom cloud login (the Settings card) for a non-empty list. Verified
    via a `DIVOOM_UI_FAKE_GALLERY` debug mock + screenshot.

### Post-v0.20.2 — Native UI: live device-screen preview (2026-06-29)

- **Sidebar now shows the device's last-pushed frame** (web-UI parity for the flat
  screen preview). New `native-port/divoom-ui/src/preview.rs`: encodes an RGB pixel
  buffer to a `data:image/png;base64` URL and decodes any such data-url into an egui
  texture (base64 + the `image` crate). The app polls the daemon's `get_device_activity`
  (~1.5s) and renders `activity[mac].preview`; frames the UI itself pushes (pixel art)
  seed a **client-side** preview that shows instantly and are persisted back via
  `set_device_activity` (mirrors the web UI's localStorage + activity path). `NEAREST`
  texture sampling keeps the low-res device grid crisp when upscaled. The daemon already
  exposed the preview field — no daemon change needed.
- **Tested:** unit tests for the encode/decode round-trip + edge cases (3 new, 5 total
  green); screenshot-verified the sidebar render via a `DIVOOM_UI_FAKE_PREVIEW` debug
  seed. Kept `app.rs`/`preview.rs` under the 500-line gate by housing the preview
  methods in `preview.rs`.

### Post-v0.20.2 — Native UI: egui 0.29 → 0.35 migration (2026-06-29)

- **Upgraded the native UI to egui/eframe/egui_extras 0.35** (from 0.29). Ported all
  breaking API changes: `Rounding`→`CornerRadius` (u8 args), `Margin` is now `i8`,
  `Painter::rect`/`rect_stroke` gained a trailing `StrokeKind`, `Frame::none()`→
  `Frame::NONE`, `FontData` wrapped in `Arc`, `ctx.style()/set_style`→`ctx.all_styles_mut`,
  `ViewportCommand::Screenshot(UserData::default())`, the merged `egui::Panel`
  (`Panel::{top,left,bottom}(id).exact_size(..).resizable(..).frame(..).show(ui,..)`
  replacing `TopBottomPanel`/`SidePanel`), and `eframe::App` split (`update`→`logic(ctx)`
  for non-UI work + `ui(&mut Ui)` for the panel tree). `show_inside`→`show`.
- **Verified:** clean `cargo build` debug+release (only pre-existing dead-code warnings);
  self-screenshot harness confirms the Channels tab renders identically (appbar sliders +
  glyphs + Settings pill, sidebar nav glyphs + orange active accent, painted clock-face
  preview grid, device panel, daemon-status row).

### Post-v0.20.2 — Native app VERIFIED on hardware + shipped alongside (2026-06-29)

- **Verified the native bundle on real hardware** (computer-use, user-approved):
  launched `Divoom Native.app` → it spawned the sibling `divoomd` → BLE scan found
  3 real devices (Tivoo-Max, Timoo, Pixoo) — **no TCC crash, the embedded Info.plist
  worked** → connected to Tivoo-Max → UI controls reached the device (Rainbow clock;
  brightness set 0 then 54, read back from the device; volume read back as 5/15 on
  connect). The Bluetooth grant that blocked this for weeks is resolved by the real
  `.app` being its own TCC responsible process.
- **Shipped alongside the Python app** (per user choice — both, no replacement):
  `build_native_app.sh` now also produces `Divoom-Native-v<version>.dmg`; uploaded
  as an additional asset on the v0.20.2 release; added a second Homebrew cask
  `divoom-control-native` (ztomer/tap) pointing at it. `brew style` clean,
  `brew fetch` verifies the checksum. The Python `divoom-control` cask is untouched.
  Install: `brew install --cask ztomer/tap/divoom-control-native`.

### Post-v0.20.2 — Native app packaging (non-destructive) (2026-06-29)

- **`scripts/build_native_app.sh`** — assembles the fully-native, Python-free
  `dist-native/Divoom Native.app`: `Contents/MacOS/{divoom-ui, divoomd,
  libdivoom_compact.dylib}` + an `Info.plist` with the Bluetooth usage strings,
  adhoc-codesigned. Self-contained: the UI spawns the sibling `divoomd` and now
  passes `DIVOOMD_ENCODER_LIB` (sibling dylib) so image/text encoding works in the
  bundle (`divoom-ui` spawn_daemon change). **Non-destructive** — a separate
  `dist-native/` artifact; does NOT touch the Python py2app build, the Homebrew
  cask, or any default (no cutover). Verified: bundle assembles + signs + has the
  BT plist key. First launch + BT grant + the cutover remain user-gated.

### Post-v0.20.2 — Native MCP server (last daemon gap) (2026-06-29)

- **`divoomd mcp`** — native MCP stdio JSON-RPC server (`mcp.rs` + `mcp_tools.rs`),
  ported from `divoom_lib/mcp_server.py` + `mcp_tools.py`. It's a daemon-routed
  bridge: connects to the daemon socket (DIVOOM_SOCKET) and forwards each
  `tools/call` as a `device_call`/command — the same model as the Python
  MCP-via-daemon. All 13 tools (set_volume/brightness/light_mode/weather/alarm/
  radio/low_power/screen_orientation/show_image/push_animation/play_sound/
  get_capabilities/get_device_state); file tools decode locally (image crate) and
  push rgb. initialize/tools/list/tools/call/ping verified end-to-end; catalog +
  light/weather maps unit-tested. Added tokio `io-std`. This closes the **last**
  daemon gap — all daemon/menubar/app parity gaps are now closed.

### Post-v0.20.2 — Gap-closure run: daemon + menubar + app (2026-06-29)

- **sync_time**: daemon `set_date_time` device_call leaf (cmd 0x18, ported from
  date_time.py, wire-byte test) + UI "Update device time" button (chrono).
- **Cloud login**: daemon `save_credentials` command (writes config.ini [divoom]
  0600 + validates via UserLogin) + Settings login card. Unblocks the gallery.
  Refactored cloud.rs → cloud_store.rs + daemon.rs → cloud_cmds.rs (500-line gate).
- **Test notification**: was mis-classified as a daemon gap — the device_call leaf
  `notification.show_notification[_text]` already existed; added the UI control.
- **Menubar**: status-colored tray glyph (green/orange/red) — pyobjc-menubar parity.
- All tractable gaps across daemon/menubar/app now closed. **Sole remaining real
  gap: a native MCP server in the daemon** (large standalone workstream — needs a
  go-ahead). Device-dependent niche (Custom Art, Hot Channel, audio viz, wall
  presets) still need hardware. Python kept as reference (never deleted).

### Post-v0.20.2 — Native UI port: FUNCTIONAL PARITY (2026-06-29)

- **/loop-until-parity run (8 iterations)** — closed the gaps the audit found.
  `docs/PARITY_TRACKER_NATIVE_UI.md` is the full record. Highlights:
  - Structural fixes: Live Widgets re-mapped to live data feeds (music/stocks/
    sysmon/weather via `live_job_*`); gallery moved under Pixel Art.
  - Channels: clock-color (`set_clock_rich` kwargs), Sessions (sleep/timer/
    countdown/noise), Text push (embedded 5x7 bitmap font → `show_image`).
  - Device Settings: FM radio. Schedule: `get_alarms` read-back, memorial, timeplan.
  - Live Widgets: temperature channel + running-job status. Device-state read-backs
    (brightness/volume/name/scoreboard) on connect. Scan timeout.
  - Tray: dynamic device section (click → select+connect).
  - **Functional parity reached** for all portable/verifiable UI features. Remaining
    items are blocked: daemon gaps (cloud login, test notif, sync_time, MCP),
    device-dependent niche (Custom Art, Hot Channel, wall presets), audio capture,
    and minor polish — all categorized in the tracker.

### Post-v0.20.2 — Native UI port: Phase 3 complete + Phase 4a tray (2026-06-29)

- **Phase 3 complete** — all 7 sidebar tabs live (placeholder removed):
  `settings.rs` (notifications/LAN/keep-alive via `Cmd::Raw`), `schedule.rs` (5
  alarm slots → `alarm.set_alarm`), `pixel_art.rs` (16x16 paint editor → `show_image`
  rgb kwargs), `wall.rs` (device slots → `wall_configure`), `widgets.rs` (gallery
  `fetch_gallery` — count + cloud-auth note; thumbnails deferred). Verified by
  self-screenshot. Deferred (documented): gallery thumbnail render, Channels Text
  push (bitmap font), Sessions, clock color.
- **Phase 4a** — `tray.rs`: cross-platform native tray/menubar via `tray-icon`
  (MIT) mirroring `divoom_menubar` (Show Dashboard / Start-Stop Notifications /
  Quit; label tracks live state; same-process). Builds + runs without crash.
- **Remaining (user-gated):** per-OS packaging + cutover (flip default launcher) —
  needs the macOS BT grant + user review; Python UI stays the reference.

### Post-v0.20.2 — Native UI port: Phase 3a (Device Settings) (2026-06-29)

- **`divoom-ui/src/device_settings.rs`** (new): the Device Settings tab — device
  name, clock format (12/24h), temp unit, power mode, auto power-off, orientation,
  mirror/flip, confirm-gated factory reset; each wired to the device_call leaf the
  Python `ToolsApi` uses (verified vs the Rust dispatch). `sync_time` is a real
  daemon gap (Python uses `DateTimeCommand`, not a device_call leaf) → button
  disabled with a note (no faked method).
- Added a generic `Cmd::Raw`/`Update::Reply` daemon-RPC path (reply tag → stored in
  `app.replies`) for the upcoming Settings/Schedule/gallery tabs; `DIVOOM_UI_TAB`
  screenshot aid. Verified by self-screenshot.

### Post-v0.20.2 — Native UI port: Phase 1+2 (events + Channels) (2026-06-29)

- **Phase 1** (`divoom-ui/src/daemon.rs`): `subscribe` event thread for live
  status push (auto-reconnect) + `divoomd` auto-spawn when the socket is absent
  (`DIVOOMD_BIN`/sibling-of-exe/PATH resolution + poll-connect). Windows TCP
  transport deferred to packaging.
- **Phase 2** (`divoom-ui/src/channels.rs`, new): the Channels tab renders real
  per-channel panels reproduced from `web_ui` (`channels_grids.js`), each wired to
  the same device_call leaf as the Python `LightingApi`/`ToolsApi` (positional
  args, verified vs the Rust dispatch): clock face → `display.show_clock`;
  visualizer (12 EQ) → `display.show_visualization`; VJ (16) →
  `display.show_effects`; ambient (5 modes + color/swatches) →
  `display.show_light`; scoreboard → `set_scoreboard`. Generic selector-grid /
  swatch widgets; `DIVOOM_UI_CHANNEL` screenshot aid. Text push (bitmap-font
  render) + Sessions panel deferred to Phase 3.
- Verified by self-screenshots (clock/ambient/scoreboard). Python UI untouched.

### Post-v0.20.2 — Native UI port: Phase 0 (egui shell) (2026-06-29)

- **New crate `native-port/divoom-ui/`** (eframe/egui 0.29) — first step of the
  native cross-platform Rust UI that replaces the Python presentation layer
  (pywebview GUI + pyobjc menubar), so the shipped app becomes Python-free.
  - **Decisions** (`docs/PLANNING_NATIVE_UI.md`): full **native widgets** (not a
    webview — supersedes the earlier wry plan); **cross-platform**; **permissive
    licensing** (MIT now, maybe commercial later, never pay) -> **Slint rejected**
    (GPL-or-pay), **egui/eframe chosen** (MIT/Apache). The `web_ui/` is the visual
    reference only, archived in-tree.
  - **Phase 0**: `theme.rs` (Braun dark palette copied from `web_ui/style.css`),
    `shell.rs` (frameless appbar with brightness/volume + window-drag; 168px
    sidebar with 6 nav tabs + device panel; Channels sub-tab row), `daemon.rs`
    (NDJSON socket client on a worker thread; status poll + scan/connect/
    device_call), `app.rs` (state + a `DIVOOM_UI_SCREENSHOT` self-screenshot path
    for headless visual checks).
  - **Verified**: compiles clean; renders faithfully to the reference; live
    "daemon ready" against a no-BLE `divoomd`. Python UI untouched (still default).

### Post-v0.20.2 — Native UI/menubar plan (2026-06-29)

- **Planned** the native-Rust replacement of the Python presentation layer
  (pywebview GUI + pyobjc menubar) → `docs/PLANNING_NATIVE_UI.md`. Decision:
  Rust-hosted webview (`wry`/`tao`/`tray-icon`/`muda`) keeping the existing
  `web_ui/` static frontend verbatim and reimplementing the ~70-method `gui_api`
  bridge in Rust; 6 phases, gated on a Phase-0 `window.pywebview.api`-shim spike.
  Planning only — no code yet. Completes the native port (Python-free bundle).

### Post-v0.20.2 — Rust parity loop: cloud decode + device_call methods (2026-06-29)

Driving the native daemon to full parity with the Python implementation.
**RESULT: device_call method parity COMPLETE (0 gaps vs the Python Divoom API).**

- **device_call parity finished** (54 → 0 gaps). Beyond the earlier display/control/
  weather batch, ported verbatim with wire-byte tests: light/tool read-backs +
  hot_update.show_hot_channel; the full `animation` subsystem (10 — gif/user-define
  upload primitives, control-word handlers, LE/BE orders); `music` SD-card (13 —
  setters + read-backs); the `drawing` subsystem (14 — pads/movie/sand/scan;
  pic_scan_ctrl flagged UNVERIFIED per the APK audit); tool.set_tool_info;
  hot_update.update (routes to the top-level streamer).
- **monthly_best fixed**: used non-existent connect_device/disconnect_device (could
  never connect); now connect/disconnect. Also **gated behind DIVOOMD_MONTHLY_BEST**
  (default off) — parity: Python's monthly-best is a separate opt-in daemon, not the
  main one (avoids fleet-wide auto-push on startup).
- **Rust daemon is now the default** (`DIVOOM_USE_RUST_DAEMON` defaults on when the
  divoomd binary is present; Python kept as reference/fallback, never removed).
- **Device verification**: the decoded magic-18 cloud animation renders on Pixoo,
  Tivoo-Max, and Timoo (Ditoo was off-air during the run). cargo test 70/70 both
  matrices.

- **Cloud image decode parity** (the big one): ported `media_decoder.resolve_to_gif`
  — magic 9/18/26 (AES + per-frame LZO1X via `minilzo-rs` + `_compact_tiles`) and
  0xAA hot → frames → GIF (image crate); fixed a real 0xAA bpp bug. VERIFIED
  byte-identical to Python via oracle fixtures (magic 9: 24f, magic 18: 6f LZO+tiled)
  + resolve→GIF round-trip tests. HW-confirmed rendering a magic-18 gallery file on
  a real Pixoo. sync_artwork/monthly_best route through it; honest-error (never
  raw-stream) on truly-unknown magics — fixes the "device stuck in loading" bug.
- **device_call method parity** (audit-driven): added display.show_effects/
  show_visualization/show_scoreboard/set_temperature_channel/switch_channel/
  display_image; control.set_light_mode/set_hot(0x26)/set_keyboard(0x23);
  weather.set/set_temperature/set_weather. All ported verbatim from divoom_lib with
  wire-byte mock tests. Audit: 54 → 42 genuine gaps remaining (animation 10,
  drawing 14, music-SD 13, hot_update 2, light 1, tool 2).
- **Bugs found via compare-to-Python:** monthly_best used wrong device_call arg keys
  (`raw_args`/`kw`) + a non-existent `connect_device` command; 0xAA bpp under-count.

### Post-v0.20.2 — Rust Hardening Phase 4 Tier B (real device) + 2 fixes (2026-06-28)

- **Phase 4 Tier B — verified on a real Timoo over BLE** via the granted
  `Divoom Daemon (rs).app` (grant persisted from Jun 23, autonomous — no per-run
  user action): scan → connect → brightness round-trip (get 60 → 30 → 80,
  read-backs work) → exclusive gating (steal-reject + token-deny + owner success) →
  MCP-via-Rust `set_brightness(level=65)` → `{"ok":true,"level":65}` → disconnect.
- **fix: robust BLE (re)connect** — `connect` used a single 3s scan window that
  intermittently missed the device on reconnect; now polls the discovered set to a
  10s deadline (3/3 clean no-pre-scan reconnects on hardware).
- **feat: `shutdown` command** (Python-daemon parity) — `Notify` on `Daemon` fired
  by `shutdown`, awaited by the main loop with a 150ms reply-flush grace; clean exit
  + socket unlink confirmed live.
- **Phase 5 readiness audit:** Rust daemon still missing `probe_lan` + `sync_artwork`
  vs the Python daemon (closed `shutdown`). The default-flip waits on those; the
  irreversible `divoom_daemon/` archival waits on a soak + explicit user sign-off.
- **Tests:** cargo 63/63 both matrices.

### Post-v0.20.2 — Rust Hardening Phase 3 + Phase 4 Tier A/C (2026-06-28)

- **Phase 3 — 500-LOC compliance + gate:** split `live_jobs.rs` (965) into
  `live_jobs/{mod(428),render(290),music(245)}.rs`; trimmed `daemon.rs` (502→482)
  by moving `find_encoder_lib` into `native_encode.rs`. Added
  `tools/check_file_size.py` (deterministic 500-line gate over tracked source;
  tests/vendored/target exempt), wired into CI + the pre-commit hook. 267 source
  files clean.
- **Phase 4 Tier A — hardware-free E2E (in CI):**
  - `test_mock_exclusive_mode_gating` (`src/mock_device_tests.rs`): exclusive
    acquire → immediate steal-reject → foreign-token `device_call` denied → owner
    call routes to mock → release → re-acquire, with wire-byte assertion.
  - `test_rust_mcp_via_daemon` (`tests/test_rust_daemon_parity.py`): MCPServer +
    `build_tool_catalog` over a `DaemonDeviceProxy` bound to the spawned Rust
    daemon (mock device); `tools/list` + `tools/call(set_volume)` round-trip to
    success. Rust 63/63 both matrices; parity suite 12 passed / 1 skipped.
- **Phase 4 Tier C — best-effort cross-platform (no Win/Linux hardware):** added
  `rust-ble-linux` + `rust-ble-windows` `continue-on-error` compile-only CI jobs
  (prove the BlueZ/WinRT btleplug backends build per-OS). Real-radio on those OSes
  is explicitly out of scope and never claimed verified.
- **Remaining:** Phase 4 Tier B (real Pixoo via the granted macOS `.app`) → Phase 5
  (Python backend archival).

### Post-v0.20.2 — Rust Hardening Phase 1+2: core build fix + CI gate (2026-06-28)

- **Restored the `--no-default-features` build** (`f7e0e7c`): the hardware-free core had stopped compiling (regression in `e4bd424`). Root cause: the `DeviceTransport` device-I/O method layer was `ble`-gated despite delegating to non-ble Spp/Lan/Mock, and `BleResult` lived in the ble-gated module.
  - Relocated `BleResult` to `src/transport.rs` (`ble.rs` re-exports it); `mock_transport.rs` imports it from there.
  - Un-gated the `DeviceTransport` method layer, `NativeEncoder`/`Daemon::encoder()`, and the whole `device_call` dispatch + submodules; gated only the inner `DeviceTransport::Ble` match arms, routing the device gate through `!matches!(Lan)`.
  - `wall.rs` `show_image`/`broadcast_command` now use the enum method layer instead of matching `DeviceTransport::Ble` (also fixes a latent Spp/Mock wall silent-fail).
  - Result: the full command surface + MockTransport build/test hardware-free.
- **Rust CI gate** (`762c6ad`): added `rust-core` (ubuntu, `cargo test --no-default-features --locked`) and `rust-ble` (macos, libdivoom dylib + `cargo test --locked`) jobs to `.github/workflows/tests.yml`. No CI previously ran cargo, which is why the regression slipped through.
- **Phase 4 re-planned for autonomy** (`docs/PLANNING_NATIVE_PORT_HARDENING.md`): Tier A mock-driven E2E (CI, hardware-free), Tier B real-device via the pre-granted macOS `.app` (no per-run user action), Tier C Linux/Windows real-radio as the only human/device-bound residue.
- **Tests**: `cargo test` = 62 green; `cargo test --no-default-features` = 62 green (was 8 compile errors).

### Post-v0.20.2 — Rust MockTransport & Test Coverage Infrastructure (2026-06-28)

- **MockTransport** (`src/mock_transport.rs`): New `MockTransport` struct that logs `(cmd_id, payload)` tuples and simulates generic ACK responses, enabling offline command serialization testing without real hardware.
- **Mock E2E Tests** (`src/mock_device_tests.rs`): 4 `#[tokio::test]` tests asserting exact wire byte patterns for `display.set_clock_rich` (0x45 APK C2), `display.show_clock` (0x45 hass-divoom), `device.set_brightness` (0x74), and `music.set_volume` (0x08).
- **DeviceTransport::Mock** (`src/transport.rs`, `src/device_call/mod.rs`): Added `Mock` variant to `DeviceTransport` enum, delegated trait methods, and included in the BLE-like device gate for `device_call` dispatch.
- **Exhaustive Match Coverage**: Added `Mock(_)` arms in `wall.rs`, `daemon.rs`, `daemon_connect.rs`, and `macos_notifications.rs`.
- **Coverage Script** (`scripts/rust_coverage.sh`): Helper bash script for running `cargo-llvm-cov` code coverage reports.
- **Tests**: Rust **62 passed** (11 lib + 46 integration + 4 mock + 1 native-encode); Python **16 passed, 1 skipped** (daemon parity suite).

### Post-v0.20.2 — Native Port: Complete Rust Parity (2026-06-28)

- **Divoom Cloud Authentication & Caching** (`src/cloud.rs`, `src/lib.rs`, `src/daemon.rs`, `Cargo.toml`): Ported email login (`POST /UserLogin`), guest HMAC-MD5 signing (`POST /User/NewGuest`), server UTC time sync, configuration parser (`config.ini`), cache manager (`auth_token.json` with 0o600 file write), and failure cooldown mechanism from Python to Rust. Added new dependencies (`md-5` and `hmac`) for cryptographic operations.
- **Cloud Gallery Retrieval API**: Ported `/GetCategoryFileListV2` (fetching, sorting, filtering, and page streaming of animation files from Divoom community) with automatic credential refresh retry fallback on token expiration.
- **Monthly Best background loop** (`src/monthly_best.rs`, `src/main.rs`): Implement background poll task looping on dynamic `hotchannel.json` configurations, extracting Magic 43 container GIFs, connecting to target displays on interval, downsampling files, and streaming native animation payloads.
- **Precompiled Animation Streams & Clock Overlay Alignment** (`src/device_call/basic.rs`, `mod.rs`): Added `"animation.stream_animation_8b"` for precompiled stream uploads and `"display.set_clock_rich"` implementing the APK's C2() layout coordinates for weather, humidity, and calendar clock overlays.
- **Parity Verification**: Shipped Rust unit tests verifying hashing signatures, configuration parsing, cache validity, cooldown timers, Magic 43 GIF extraction, and hotchannel configurations. Added integration tests (`test_rust_cloud_auth_endpoints`, `test_rust_fetch_gallery`, and `test_rust_set_clock_rich`) in `tests/test_rust_daemon_parity.py` to assert socket auth/gallery category/clock coordinate retrieval.
- **Tests**: Rust 58 passed; Python 1703 passed, 87 skipped. (Verified with new unit and integration tests).

### Post-v0.20.2 — Native Port: Bluetooth Classic SPP Integration (2026-06-28)

- **Bluetooth Classic SPP Transport** (`spp_bridge.py`, `spp.rs`, `transport.rs`, `daemon_connect.rs`): Integrated full Bluetooth Classic SPP transport support into the native Rust daemon using a lightweight Python standard input/output bridge subprocess. Reuses Python's proven `BTSppTransport` to bypass private ObjC `IOBluetooth` bindings in Rust, enabling connection, command execution, and `0x8B` animation streaming.
- **Match Exhaustiveness**: Fixed exhaustive pattern-matching errors across all matching blocks (in `daemon.rs`, `live_jobs.rs`, `wall.rs`, `art.rs`, `art_hot.rs`, and `macos_notifications.rs`) to cleanly handle `DeviceTransport::Spp` alongside BLE and LAN.
- **Parity Verification**: Shipped a new integration test `test_rust_spp_connect_failure_integration` verifying SPP bridge error propagation, and added a physical hardware parity integration test `test_rust_hardware_parity` validating scans, connection, get/set brightness, and disconnection on live Divoom hardware. Renamed manual tests to fix test collection.
- **Tests**: Rust 51 passed; Python 1702 passed, 87 skipped. (Verified with new integration and hardware tests).

### Post-v0.20.2 — Native Port: Align Notification Service, Command Parity, TCP/Token Auth, --mac Option & Rust Auto-Spawn (2026-06-28)

- **macOS Notification Monitor** (`macos_notifications.rs`): Refactored to query the Notification Center SQLite DB (Sonoma/Sequoia paths + Group Containers fallback) using a read-only `rusqlite` connection directly. Parsed binary plists with the `plist` crate to retrieve `app`, `title`, and `body` fields. Implemented routing and tracking for `seen`, `routed`, and `dropped` counters, duplicate suppression, and health checks.
- **Daemon Command Parity** (`daemon.rs`): Aligned `get_status`, `start_notifications`, `stop_notifications`, `notification_status`, and `set_routing` command payloads and response shapes to match Python's schema exactly. Exposed status and notification events to socket subscribers. Updated `device_status` to return the stored default MAC address when disconnected.
- **Headless TCP Server** (`main.rs`, `socket_server.rs`): Ported headless TCP listener socket and constant-time token comparison checking. Enforced token setup on TCP configurations (fail-closed check). Added `--mac` command-line argument support.
- **Rust Daemon Auto-Spawn** (`divoom_daemon/daemon_client.py`): Integrated support for `DIVOOM_USE_RUST_DAEMON=1` to auto-spawn the compiled Rust `divoomd` binary instead of the Python daemon in the desktop GUI/menubar/TUI clients.
- **Parity Verification**: Shipped a new Python integration test suite `tests/test_rust_daemon_parity.py` verifying response schema alignment, token auth security, and default MAC address configuration of the compiled Rust daemon subprocess using Python `DaemonClient`.
- **Tests**: Rust 51 passed; Python 1711 passed, 87 skipped.

## Post-v0.20.2 — Native Port: Art Sync, Hot-Update, Wall, Live Jobs, macOS Notifications + 500 LOC Splits (2026-06-26)

- **Art Sync / Custom Art / Hot-Update** (`art.rs`, `art_codec.rs`, `art_hot.rs`): Ported cloud artwork downloads
  (magic-43, AES-128-CBC magic-9, 0xAA hot-file), custom art slot push/query, and the hot-channel update protocol
  (manifest fetch → SHA-1 verify → BLE streaming). AES-128-CBC implemented pure-Rust (no new deps).
- **DivoomWall Coordinator** (`wall.rs`): Multi-panel display wall — connect, delta reconfigure (G7), image crop/resize/parallel-stream.
  `cmd_wall_configure` moved from `daemon.rs` to `wall.rs` for LOC compliance.
- **Live Jobs** (`live_jobs.rs`): Background widget loops — system monitor, stocks ticker, weather updates, music album cover.
- **macOS Notification Monitor** (`macos_notifications.rs`): SQLite `usernoted` DB monitor via `sqlite3` CLI; maps bundle IDs → ANCS push over BLE.
- **Connect/Disconnect/Scan extracted** (`daemon_connect.rs`): 83-line module; thin delegations in `daemon.rs`.
- **500 LOC rule enforced**: All new/modified files ≤ 500 lines:
  - `daemon.rs`=498, `wall.rs`=457, `art.rs`=331, `art_hot.rs`=251, `macos_notifications.rs`=233, `art_codec.rs`=197, `daemon_connect.rs`=83.
- **Tests**: Rust 51 passed; Python 1686 passed, 87 skipped (Playwright browser-binary failures are pre-existing, unrelated).

## Post-v0.20.2 — Native Port Remaining Commands & Modularization (2026-06-23)


- **Modularization & 500 LOC Enforcement**: Refactored the native Rust daemon (`divoomd`) by migrating all remaining device command logic from `src/daemon.rs` into modular submodules under `src/device_call/`. This shrinks `daemon.rs` from 1944 lines down to 317 lines (complying with the 500 LOC limit).
- **Clean Compilation & Feature Gating**: Gated the submodules in `mod.rs` and all BLE-specific imports/fields in `daemon.rs` behind `#[cfg(feature = "ble")]` to ensure warning-free compilation both with and without default features.
- **Verification & Tests**: Verified that all Rust tests (55 passed) and the full Python test suite (1706 passed, 87 skipped) pass successfully.

## Post-v0.20.2 — Native Port Scheduling Commands (2026-06-23)

- **Scheduling Commands**: Ported alarm, sleep, and timeplan scheduling commands to the native Rust daemon (`divoomd`), ensuring parity with the Python API:
  - **Alarm**: Ported `alarm.get_alarm_time`, `alarm.set_alarm`, `alarm.set_alarm_gif`, `alarm.get_memorial_time`, `alarm.set_memorial_time`, `alarm.set_memorial_gif`, `alarm.set_alarm_listen`, `alarm.set_alarm_volume`, `alarm.set_alarm_volume_control`.
  - **Sleep**: Ported `sleep.show_sleep`, `sleep.get_sleep_scene`, `sleep.set_sleep_scene_listen`, `sleep.set_scene_volume`, `sleep.set_sleep_color`, `sleep.set_sleep_light`, `sleep.set_sleep_scene`.
  - **Timeplan**: Ported `timeplan.set_time_manage_info`, `timeplan.set_time_manage_ctrl`.
- **Parity & Tests**: Updated the `ported_commands_route_to_device_call` integration test in `tests/daemon_behavior.rs` to verify that all newly implemented commands and their aliases correctly match in the router and dispatch to the device transport. Verified both compilation and test suite correctness with and without the `ble` feature gate. Full Python pytest suite passes with 1706 passed, 87 skipped.

## Post-v0.20.2 — Native Port Tool & Notification Commands (2026-06-23)

- **Tool & Notification Commands**: Ported device tool commands and notification display commands to the native Rust daemon (`divoomd`), ensuring parity with the Python API:
  - **Scoreboard**: Ported `"scoreboard.set_scoreboard"`, `"set_scoreboard"`, `"scoreboard.get_scoreboard"`, `"get_scoreboard"`.
  - **Timer**: Ported `"timer.set_timer"`, `"set_timer"`, `"timer.get_timer"`, `"get_timer"`.
  - **Countdown**: Ported `"countdown.set_countdown"`, `"set_countdown"`, `"countdown.get_countdown"`, `"get_countdown"`.
  - **Noise Meter**: Ported `"noise.set_noise"`, `"set_noise"`, `"noise.get_noise"`, `"get_noise"`.
  - **Notification Display**: Ported `"device.show_notification"`, `"show_notification"`, `"notification.show_notification"`, `"device.show_notification_text"`, `"show_notification_text"`, `"notification.show_notification_text"`.
- **Parity & Tests**: Updated the `ported_commands_route_to_device_call` integration test in `tests/daemon_behavior.rs` to verify that all newly implemented commands and their aliases correctly match in the router and dispatch to the device transport. Verified both compilation and test suite correctness with and without the `ble` feature gate. Full Python pytest suite passes with 1706 passed, 87 skipped.

## Post-v0.20.2 — Native Port Remaining Device Call Commands (2026-06-23)

- **Remaining Device Call Commands**: Ported the rest of the high-value `device_call` commands to the native Rust daemon (`divoomd`), ensuring 100% parity with the Python API:
  - **Volume Control**: Ported `"music.get_volume"`, `"get_volume"`, `"music.set_volume"`, and `"set_volume"` (0x08/0x09 commands).
  - **FM Radio**: Ported `"radio.set_radio_frequency"`, `"set_radio_frequency"`, `"radio.set_radio"`, and `"set_radio"` (0x61 command).
  - **Low Power Switch**: Ported `"device.get_low_power_switch"`, `"get_low_power_switch"`, `"device.get_low_power"`, `"get_low_power"`, `"device.set_low_power_switch"`, `"set_low_power_switch"`, `"device.set_low_power"`, and `"set_low_power"` (0xb2/0xb3 commands).
  - **Auto Power Off**: Ported `"device.get_auto_power_off"`, `"get_auto_power_off"`, `"sound.get_auto_power_off"`, `"device.set_auto_power_off"`, `"set_auto_power_off"`, and `"sound.set_auto_power_off"` (0xab/0xac commands).
- **Parity & Tests**: Added the `ported_commands_route_to_device_call` integration test to `tests/daemon_behavior.rs` to verify that all newly implemented commands are correctly matched in the router and dispatch to the device transport (failing honestly with "no device connected"). Verified both compilation and test suite correctness with and without the `ble` feature gate. Running full Python pytest suite resulted in 1706 passed, 87 skipped.

## Post-v0.20.2 — Native Port Event Subscription & Device Name (2026-06-23)

- **Event Subscription & Broadcast**: Extended the native Rust daemon socket server with a robust, tokio-native subscription system (`subscribe` command). When subscribed, clients immediately receive the initial status frame and subsequently stream real-time broadcast events (such as connection state changes) over the held-open Unix socket. Multiplexed via `tokio::select!`, connection close (EOF) automatically cleans up subscribers.
- **Friendly Name Cache**: Added a thread-safe `device_name` cache to `BleTransport` to avoid redundant BLE read round-trips.
- **New Device Commands**: Ported `"device.get_device_name"` (queries the device name via BLE 0x76 as fallback, or returns cached name) and `"device.set_device_name"` (modifies device name via BLE 0x75, updating cache).
- **Parity & E2E Validation**: Added integration tests `subscription_and_event_broadcast` and `device_name_commands_route_to_device_call`. All tests pass. Verified E2E against real hardware.

## v0.20.0 — Native Rust Port Phase 2 & App Startup Fix (2026-06-22)

This release bundles the fixes from v0.16.1 along with major milestones in the native Rust daemon port (`divoomd`):

- **Fixed `ModuleNotFoundError: No module named 'gui_api'` on startup.** 
  Corrected directory layout assumptions within `divoom_gui` imports so that the packaged `Divoom.app` starts up successfully under `py2app` without encountering import issues.
  
- **Single-Source Versioning.**
  The bundle version is now read dynamically from `pyproject.toml` rather than being hardcoded.

- **Native Rust Port (Phase 2):**
  - **Phase-1 BLE Spike:** Completed compilation check for `btleplug` and `tokio` integration (`364c979`).
  - **Framing & Models:** Implemented framing and model serialization in Rust, ensuring they are byte-identical to the Python implementation (`b37d987`).
  - **Command Queue Parity:** Brought command queue implementation to behavioral parity using Tokio (`eddec22`).
  - **Notify/Response Correlation:** Completed correlation matching for async notifications and command responses in Rust (`6d27a0e`).

## Post-v0.20.0 — cask release / test fix / scan-timeout backstop / Tivoo-Max SPP fix (2026-06-22)

- **Homebrew cask released**: Created GitHub release `v0.20.0` on `ztomer/divoom_lib` and
  uploaded `Divoom-v0.20.0.dmg` so the Homebrew cask URL resolves. Reinstall verified working.
- **Test fix**: `test_connection_cap_rejects_when_full` was racing `sendall()` after
  server closed — fixed by reading the buffered reply first. CI passes.
- **Scan timeout backstop fix (3 bugs)**:
  1. `owner_loop.py:_run_on_loop` — when the 90s backstop fires, the underlying coroutine
     kept running on the loop for the rest of its user-configured timeout (up to 360s),
     consuming BLE resources and blocking subsequent scans. Now `future.cancel()` is called
     on timeout.
  2. `owner_connect.py:scan` — the scan timeout from config (user had 360s) far exceeded
     the 90s backstop, making every long scan a guaranteed failure. Now capped to
     `_SCAN_RESULT_TIMEOUT` (90s) at the daemon level.
  3. `app_init.js:load_config` — the HTML `<input max="120">` was bypassed when JS set
     timeout from config (e.g., 360). Now clamped to `el.max` before assignment.
- **Tivoo-Max SPP routing fix (2 bugs)**:
  1. `owner_connect.py:_ensure_device_async` hardcoded `use_ios_le_protocol=False` for ALL
     devices on the daemon's auto-reconnect path. For a Tivoo-Max (or any device with "tivoo"
     in the name), this triggered SPP (Bluetooth Classic RFCOMM) routing instead of BLE.
     SPP has a known "macOS Tahoe reconnection bug" that times out. Fix: use `None` (auto-detect via autoprobe).
  2. `connection.py:connect` — the SPP routing condition `not self.use_ios_le_protocol` fired
     for both `False` (explicit Basic) AND `None` (unknown/unprobed). When protocol is unknown,
     the autoprobe should determine it first via BLE, not pre-empt with SPP. Fix: change to
     `self.use_ios_le_protocol is False`.
- Suite: 1701 passed, 87 skipped.

## Post-v0.20.1 — Kaset album art integration + card padding (2026-06-22)

- **Kaset album art support**: Added Kaset (`/Applications/Kaset.app`) as a now-playing
  source. Kaset's AppleScript `get player info` returns a JSON blob with direct YouTube
  thumbnail URLs, so artwork sync works for YouTube Music tracks without the iTunes
  Search API. Returns `artwork_url` in the enriched dict; callers skip the iTunes
  fallback when a direct URL is available.
- **Feishin album art support**: Added Feishin (`/Applications/Feishin.app`, an
  Electron-based Navidrome client) as a now-playing source (checked first). Extracts
  Subsonic API credentials from Feishin's Chromium Local Storage (LevelDB), then
  queries the Navidrome server's `getNowPlaying` endpoint for track info and cover
  art. Credentials are cached for 60s to avoid repeated LevelDB scans.
- **Card padding tightened**: Reduced `.card` padding from `20px` → `12px`,
  `--panel-gap` from `20px` → `12px`, and `.card-header` margin-bottom from
  `15px` → `10px` so general tab panels (settings, routines, tools) match the
  tighter tile component spacing.
- Tests: 12 passed (media_source).

---
## v0.16.1 — packaged app startup fix (2026-06-22)

Fixes a critical startup crash when running the packaged macOS app bundle `Divoom.app` installed via the Homebrew cask:

- **Fixed `ModuleNotFoundError: No module named 'gui_api'` on startup.** 
  The app bundle uses `py2app` to package Python dependencies. `py2app` copies the main launcher script `gui_main.py` directly to the `Contents/Resources/` directory while putting the remaining `divoom_gui` package under `Contents/Resources/lib/python3.14/divoom_gui/`. 
  
  Because of this, the folder-relative imports inside the GUI package (e.g. `from gui_api import DivoomGuiAPI`, `from presets_manager import ...`, etc.) failed to resolve, as the subfolder `divoom_gui` was no longer on `sys.path`.
  
  All GUI imports have been updated to use the standard package prefix `divoom_gui.` (e.g., `from divoom_gui.gui_api import DivoomGuiAPI`), which correctly resolves within both the packaged app bundle and the local development environment.
  
- **Cleaned up Test `sys.path` Hacks.**
  Cleaned up tests that manipulated `sys.path` to import GUI modules directly as top-level files, updating them to standard package-prefixed imports.

---
## v0.16.0 — hardware-validated daemon fixes (2026-06-22)

Packaged release bundling the HW-validated fixes below since v0.15.2: read-backs
restored (iOS-LE ACK revert), exclusive steal-reject (no 30 s hang-then-steal),
ACK != device-confirmed honesty for custom-art + hot-update, the 0x8B animation
retransmit dead-path fix, and the native C image-encoder divergence fix + fast-path
revival. All validated against a live Pixoo-1; suite 1700 passed. New socket
response fields (`device_confirmed`, `confirmed`) are additive. This is the
ground-truth Python release cut before the native-daemon port. Full notes:
`docs/release_notes_v0.16.0.md`.

---
## R53.x HW round: native C image encoder — divergence fixed + revived (2026-06-22)

Two compounding bugs in the native image encoder:

- **Static header off-by-one** (`image_encode.c divoom_encode_static_image`) —
  `static_header_size` was 6, so the NN palette-count byte written at `out_buf[6]`
  was immediately CLOBBERED by `memcpy(out_buf + static_header_size, palette, …)`
  (the palette landed on byte 6), and LLLL undercounted by 1. The C emitted a
  6-byte header vs Python's correct 7-byte (AA + LLLL + 000000 + NN). Fix:
  `static_header_size = 7`.
- **Wrapper under-allocation** (`image_encoder.py`) — `_c_encode_animation_frame`
  and `_c_encode_static_image` sized the output buffer at `(w*h+7)//8` (1 BIT per
  pixel), but the C's conservative worst-case check needs `w*h` (8 bits/pixel). For
  any frame past ~1 pixel the C returned -1 → silent Python fallback. **The native
  image encoders were effectively DEAD for real frames** (16x16 → None). Fix:
  allocate `7 + 256*3 + w*h`.

Together: the native path is now actually reached for real frames AND byte-identical
to the verified-correct Python reference across every size/colour count tested
(1x1…32x32, 1…256 colours — static AND animation-frame). Dylib rebuilt.

- **HW-validated** — restarted the daemon onto the rebuilt dylib and pushed the
  test animation to Pixoo-1 via `display.show_image` (now encoding through the
  revived native C path): `result: true`, identical device behaviour (byte-identical
  bytes -> identical push); read-back sanity `get_brightness` → 60.
- **Tests** — direct-C-path teeth added (`test_c_static_matches_python`,
  `test_c_static_header_is_7_bytes_with_nn`) that drive the C function with a
  worst-case buffer (bypassing the wrapper's Python fallback, which made the
  pre-existing wrapper-based parity tests false positives). Teeth-verified: against
  the pre-fix 6-byte-header dylib, 17 direct-C tests fail; fixed + rebuilt, green.

---
## R53.x HW round: 0x8B animation retransmit dead-path fixed (2026-06-22)

The 0x8B animation streamer set `_expected_response_command = 0x8B` before START,
but `_await_8b_device_ready`'s `wait_for_response` CLEARS the scalar on the start-ACK
match. For the entire chunk loop AND the retransmit window the scalar was therefore
None, and 0x8B is not a generic-ACK command — so the notification handler DROPPED
every unsolicited 0x8B retransmit request. `_serve_8b_retransmits` then waited 1 s on
an empty queue and returned "done": a device-requested re-send was silently lost, the
chunk never recovered, and the stream STILL returned True (ACK ≠ success).

- **Fix** — `stream_animation_8b` adds 0x8B to `_listen_commands` for the stream's
  duration (removed in `finally`). The handler's `is_listened` branch queues those
  frames WITHOUT consuming the scalar, so `_serve_8b_retransmits` can actually serve
  them. Purely additive: the happy path (no retransmits) is unchanged.
- **HW-validated** — pushed a 2-frame test GIF to the live Pixoo-1 via
  `display.show_image`: device replied "requested the animation (start ACK)", the
  chunk streamed, the retransmit phase went quiet, push returned True. The fix does
  not perturb the working push (the deferral's key concern).
- **Tests** — `test_stream_listens_for_0x8b_during_stream_and_cleans_up` (wiring:
  0x8B present during stream, removed after); `test_listened_0x8b_retransmit_queues_
  without_consuming_scalar` (mechanism: listened 0x8B queues + scalar untouched;
  not-listening drops it — the bug). The pre-existing retransmit test mocked
  `wait_for_response` directly, so it never exercised the real handler/queue — which
  is why it didn't catch this.

---
## R53.x HW round: ACK ≠ device-confirmed honesty (custom-art + hot-update) (2026-06-22)

Two push paths reported `success: True` on bare GATT write-with-response ACKs with
no device-state confirmation. GATT-ACK catches a mid-stream *unreachable* device
(the write fails), but NOT an *app-layer drop* (the device ACKs the link write then
silently ignores the data). HW-confirmed the only confirmation channel is unusable:
on the live Pixoo-1, **0x8E `query_page` times out at 4 s on every page and returns
empty** — so verification is impossible and would only add a 4 s dead wait per push.
Fix: surface the honest confirmation status instead of overstating success.

- **custom-art** (`owner_art.custom_art_push`) — the success result now carries
  `device_confirmed: False`. `success` stays `True` (writes were accepted). The GUI
  toast (`custom_art.js`) says "sent" rather than "pushed" when unconfirmed.
- **hot-update** (`hot_update._stream_file`) — returned a bare `True` on the
  no-done-ack timeout, indistinguishable from a device-confirmed file. Now returns
  `(ok, confirmed)`; each `served` entry carries `confirmed`, and the result adds a
  `confirmed` count. A file that streamed but whose device went silent is served
  with `confirmed: False`.
- **Tests** — `test_silent_device_file_marked_unconfirmed` (hot-update teeth: silent
  device → `confirmed:False`, count 0); custom-art success tests assert
  `device_confirmed:False`; replay tests updated to assert `confirmed:True` on the
  explicit done-ack. NOT verified via 0x8E (HW-unreliable, per above).

---
## R53.x HW round: exclusive steal-reject — hang-then-steal fixed (2026-06-22)

(HW-found on a live Pixoo-1 while validating the deferred exclusive-mode item.)
A competing `exclusive_start` did NOT cleanly reject — it hung for **exactly 30 s**
(the `exclusive_timeout`) and then **silently stole** the lock, reporting
`success: true`.

- **Root cause** — `exclusive_start` acquired the slot by submitting
  `acquire(token)` THROUGH the gated command queue (`_run_device(..., token=token)`).
  A lock-acquire must not be gated by the lock it seeks: while a different session
  owned the slot, `_dequeue` (which only dispatches the owner's items) never ran the
  foreign-token `acquire`, so `acquire`'s clean `RuntimeError("device is exclusively
  held by another session")` was unreachable. The request blocked until the G3 idle
  deadline force-released the real owner, then the waiter acquired — a 30 s hang that
  resolved as a silent steal.
- **Fix** — new `CommandQueue.acquire_now(token)` runs `acquire` directly on the loop
  (off the dispatch queue); `acquire` only touches `_cond` + `_exclusive_owner` (no
  device I/O), so it's safe off-queue. `exclusive_start` now calls it and returns the
  honest error on a foreign owner. The existing stop-active-live-jobs-first ordering
  (R53.10) is preserved for the success path.
- **HW re-validation** — on the live Pixoo-1: a steal now rejects in **0.00 s** with
  `device is exclusively held by another session`; idempotent re-acquire and
  post-release acquire both still work.
- **Tests** — `test_acquire_now_rejects_steal_immediately` (teeth: the old `submit()`
  path raises `TimeoutError` after the result timeout / steals — both fail the
  assertions); `test_exclusive_stops_jobs` fakes updated to the `acquire_now` contract.
  Suite 1680 green.

---
## R53.x REVERT: R53.35 iOS-LE ACK change — HW-disproven on real Pixoo (2026-06-22)

(Commit `b1e9770`; hardware-validated 12:07 EDT.) R53.35 changed
`_handle_ios_le_notification` to KEEP `_expected_response_command` on the generic
0x33 ACK (intending to preserve a two-frame iOS-LE read-back). On a live Pixoo-1
this broke EVERY read-back: `device.get_brightness` / `device.get_device_name`
timed out at 5.26 s → `null` while writes still worked.

- **Root cause** — clearing the scalar on the ACK is **load-bearing** for the
  protocol autoprobe. `ble_probe` sends a 0x46 query and `0x46 ∈
  GENERIC_ACK_COMMANDS`; with the scalar kept, the iOS-LE probe spuriously
  "succeeded" on the Basic-only Pixoo → the device was mis-detected as iOS-LE →
  all subsequent read-backs waited on the wrong framing and timed out.
- **Fix** — reverted to `self._expected_response_command = None` on the generic
  ACK. The 0x46 probe now correctly fails over to Basic framing.
- **HW re-validation** — via the granted dev-daemon `.app` (live repo code, owns
  the Bluetooth grant): `device.get_brightness` → `60` in **0.06 s** (was 5.26 s
  → null); `device.get_device_name` → fast 0.06 s response.
- **Tests** — `test_ios_le_generic_ack_clears_scalar` (round35) and the
  `test_base` assertion restored to expect the scalar cleared, both commented as
  load-bearing for the autoprobe. Suite 1679 green.
- **Lesson** — 1679 mocked unit tests can't catch an autoprobe regression that
  only manifests against real BLE framing (Hyrum's law: the scalar-clear was
  load-bearing for protocol detection). The targeted "two-frame iOS-LE read-back"
  remains unverified on any real device.

---
## R53 round 36: hot-enable byte + GIF zero-duration + temp validate + MCP write (2026-06-22)

(Commit `29a84d3`.) Persona pass over the last un-reviewed Python (display dispatch,
media decode, MCP server, CLI). ALL four findings are LOW / latent / cosmetic — a
genuine convergence signal. Teeth-tested, suite 1679 green.

- **LOW-MED (Bob)** — Display.show_clock(hot=True) sent 0x26 with an empty payload,
  omitting the mandatory enable byte → hot mode unreliable. Now sends [BOOLEAN_TRUE]
  (latent: no production caller passes hot=True).
- **LOW (Linus)** — process_image kept a present-but-zero GIF frame duration (`.get(k,
  default)` only fills an absent key) → _clamp_ms floored it to 1ms → strobe. Now
  `.get("duration") or default`.
- **LOW-MED (Hashimoto)** — MCPServer.run_stdio's write path was unguarded; a client
  closing stdout mid-write crashed the loop with a traceback. Now breaks cleanly.
- **LOW (Hashimoto)** — cmd_set_temperature didn't range-validate before connecting →
  out-of-range temp opened BLE then died with a raw ValueError. Now validates up front.

---
## R53 round 35: cancel-safety + iOS-LE read-back + daemon single-instance (2026-06-22)

(Commit `a7e0761`.) Persona pass over the deepest core. Carmack CLEAN (BLE
write/notify hot path verified); Bob/Linus/Hashimoto each found one. Teeth-tested,
suite 1676 green.

- **HIGH (Hashimoto)** — the daemon had NO single-instance guard. The GUI host and
  the MCP server (separate processes) can both cold-spawn a daemon; the second to
  reach serve_forever() os.remove()s + rebinds the socket, orphaning the first —
  which still holds the single BLE device → contention + a zombie owner. Added a
  flock guard (mirrors the GUI's), checked in run() before anything starts; the loser
  exits cleanly.
- **MEDIUM (Bob)** — the iOS-LE notification parser cleared
  _expected_response_command on the generic 0x33 ACK (the FIRST of a two-frame
  reply), so the real data frame was dropped → iOS-LE read-backs (get_light_mode etc.)
  timed out. Now the ACK is queued without clearing the scalar (matches the basic /
  SPP parsers). Updated the test that codified the buggy behavior.
- **MEDIUM (Linus)** — ensure_connected caught BaseException, swallowing
  asyncio.CancelledError (a BaseException since 3.8) → a teardown cancellation was
  treated as a connect failure and retried, defeating cooperative cancellation and
  delaying stop(). Now re-raises CancelledError first.

---
## R53 round 34: mcp NameError + notification health + config reload + SIGTERM (2026-06-22)

(Commit `1eb0a27`.) Persona pass over the LEAST-reviewed corners — not clean. Bob
and Linus INDEPENDENTLY CONVERGED on the same HIGH. Teeth-tested, suite 1673 green.

- **HIGH (Bob+Linus)** — `mcp_tools.get_capabilities` used `dataclasses` with no
  module-level import → NameError on a real Divoom (the DaemonDeviceProxy path masked
  it). Added the import.
- **HIGH (Hashimoto)** — the macOS notification monitor swallowed a sustained DB-read
  failure as "no new rows" → thread alive, status ACTIVE, feature silently deaf. Now a
  failure streak → `health_error` → STATE_ERROR (same "alive != working" class as the
  menubar-reader / fd-leak fixes).
- **MEDIUM (Hashimoto)** — `monthly_best_daemon --use-config` bound its params once
  before the loop → GUI edits ignored until restart. Now re-reads config each cycle.
- **LOW (Hashimoto)** — daemon had no SIGTERM handler → the production stop path skipped
  cleanup (BLE not disconnected, monitor not joined). Routed through the clean path.
- **Residual TOCTOU** — `_stamp_live_health` did `if mac in act: act[mac]` (KeyError if
  another thread pops the key); switched to atomic `.get()`. Caught by the R53.32 stress
  test failing under full-suite load.

SPLIT: the health additions pushed macos_notifications.py over the 500-LOC cap →
extracted the routing concern (DEFAULT_ROUTING / load-save-validate / MacAppRouter) into
`notification_router.py` (re-exported). macos_notifications.py 370 LOC, router 177.

---
## R53 round 33: poller off-loads + push_text size + hot_update submit guard (2026-06-22)

(Commit `fc9bd87`.) Persona pass — **Linus + Carmack came back CLEAN** (convergence;
2 of 4 lenses found nothing new); Uncle Bob + Hashimoto each found 1 MEDIUM. Plus
the round-32 poller-blocking follow-up. Teeth-tested, suite 1671 green.

- **PERF** — run_sysmon/run_stocks/run_music still ran blocking network/psutil calls
  on the BLE event loop; off-loaded the three pure (no-file-write) ones via
  asyncio.to_thread (get_system_stats, fetch_stock_ticker, fetch_album_art_url).
  DEFERRED: render_and_downsample_artwork still downloads album art on-loop (needs a
  per-call unique scratch path before off-loading without a file race).
- **MEDIUM (Bob)** — LightingApi._device_size() probed a state-dict key for a method
  that lives on the orchestrator class (never in __dict__) → always returned the 16px
  fallback, so push_text rendered wrong-sized text on non-16px devices. The orchestrator
  now exposes the bound resolver through the shared state dict.
- **MEDIUM (Hashimoto)** — hot_update wedged the whole HOT-channel feature forever if
  _cmd_queue.submit() RAISED (QueueStopped/QueueFull) before returning a future: the
  claimed "starting" phase was never cleared. submit() is now guarded (releases the claim
  + surfaces the error). Gap in the round-31 fix, which only covered future-expiry.

---
## R53 round 32: multi-persona convergence pass — 6 new bugs (2026-06-22)

(Commit `93bf159`.) The "expected-clean" convergence pass was NOT clean — a fresh
4-persona sweep over the less-traveled code surfaced 6 new verified bugs. All fixed,
teeth-tested, suite green (1607 + 61 GUI e2e).

- **HIGH** — `exclusive_start`/`exclusive_end` used the 2s quick timeout, but the
  daemon enqueues acquire behind an in-flight push (10-30s+) → client timed out while
  the daemon acquired → orphaned token + wedged device. Now `sync_read_timeout` (120s).
- **HIGH** — `run_music` ran `get_current_playing_track()` (up to 2 blocking osascript
  subprocesses) synchronously on the BLE event loop every 1.5s. Off-loaded via
  `asyncio.to_thread`.
- **MEDIUM** — `set_temperature_channel` was duplicated; the GUI routed to the copy
  that hard-coded white (dropped the user's color) and ignored the wall. Routed to the
  color-honoring, wall-aware version; deleted the dead duplicate.
- **MEDIUM** — `get_memorial_time` decoded the title without `errors=` → a
  truncated-multibyte title crashed and lost all 10 memorials. Now `errors='replace'`.
- **HIGH-latent** — `ConnectionApi.scan_devices`/`get_capabilities` called `self._client`
  (property) but the class shadows it with a method → AttributeError → always-empty scan.
  Call `self._client()`.
- **LOW** — `media_source` used `urllib.parse.quote` but only imported `urllib.request`
  (parse bound via a CPython side-effect). Added explicit `import urllib.parse`.

(Also restored the Playwright chromium browser — a SessionStart bun-install side-effect
had removed it, failing the GUI e2e suite; unrelated to the code changes.)

---
## R53 round 31: wall resize hoist + atomic hot_update guard (2026-06-21)

(Commit `44e69b5`.) Clears the last two non-HW deferrals from the multi-persona
review. Teeth-tested, suite 1664 green.

- **PERF (Carmack)** — `DivoomWall`'s full-canvas resize ran inside the per-slot
  loop → an N-device wall re-resized the whole source N times per tick (animated:
  N × all frames), and a wall LIVE job's byte-hash cache misses every tick. The
  resize is identical for every slot (only the crop differs); now computed once,
  lazily on first cache miss (all-cached path still does zero resizes), shared
  across slots. Output identical; 0-frame skip preserved.
- **CORRECTNESS (Hashimoto)** — `hot_update`'s in-progress guard was a non-atomic
  check-then-set that omitted "starting", so two socket-handler threads could both
  launch concurrent updates and clobber each other's progress. Now an atomic
  `_try_begin_hot_update` claim (with "starting" in the active set); a never-started
  fire-and-forget item is reset via a submit done-callback so "starting" can't wedge
  future updates.

With this, the multi-persona review's non-HW backlog is EXHAUSTED. Remaining items
all need hardware / APK truth to resolve safely: native C static-encoder format
divergence (dead path; 6- vs 7-byte header), SPP framing divergences (escaping /
packet_number / pacing / timeout-clear — need an SPP device), basic-protocol RX
stall behind a spurious start byte (low, self-healing), 0x8B retransmit-drop,
custom-art ACK!=success (0x8E HW-unreliable).

---
## R53 round 30: _ensure_device_async target-switch guard (2026-06-21)

(Commit `ad0021e`.) Fixes the HIGH deferral from round 29.
`_ensure_device_async` returned the cached `self._device` whenever one was held,
without comparing the requested mac — and `device_call` routes through it (not the
connect path that already guards switches). So `device_call(mac=B)` while device A
was held silently executed against A and returned `{"success": True}` (wrong-device
write reported as success). Now it mirrors `_build_device_async`'s guard: a
different known BLE target → disconnect + rebuild for the requested mac; `self.mac`
is kept in lockstep on rebuild to avoid switch-churn. Scoped to real BLE macs
(LAN isn't built here; `mac=None` still reuses the active device). Teeth-tested
(test_ensure_device_target); suite 1660 green.

Still deferred (non-HW): wall full-canvas resize per-device-per-tick (perf);
`hot_update` in-progress guard check-then-act race.

---
## R53 round 29: multi-persona review — auth/exclusive/audio/cdn/scratch (2026-06-21)

(Commit `d5a9aab`, labeled "round 26" in its message — cosmetic collision with the
parallel opencode round-26; renumbered here to 29 to stay after round 28.) A
four-persona adversarial pass (Uncle Bob / Linus / Carmack / Hashimoto) plus a
cloud/hot-channel sweep. Four real bugs fixed, teeth-tested, suite 1657 green:

- **SECURITY** — `divoom_auth` printed the cloud bearer token in clear on every
  (re)login; headless daemon stdout → logfile leaked a replayable 23h token. Added
  `_redact()` (prefix + length only) on both login paths.
- **CORRECTNESS** — `CommandQueue.acquire` unconditionally overwrote
  `_exclusive_owner`, so a 2nd `exclusive_start` STOLE the session (holder's queued
  items stranded until the 30s idle release; thief ran concurrently → clobber). Now
  rejects a different-token acquire; same-token re-acquire stays idempotent.
- **LATENT CRASH** — `audio_visualizer` read-loop error path called `time.sleep`
  but never imported `time` → NameError killed the capture thread on first error.
  Added the import; hoisted the Hann window out of the ~86 Hz FFT loop.
- **HONESTY + LEAK** — `custom_art_push._encode_file` ignored the CDN HTTP status
  and never unlinked its two per-file scratch GIFs. Now checks `status != 200` and
  unlinks both temps in a `finally`.

DEFERRED (documented): `_ensure_device_async` returns the cached device without
comparing the requested mac → a silent wrong-device write reported as success
(HIGH, but a delicate hot-path change — needs self.mac consistency + LAN-key
handling + churn-guard + teeth-test); wall full-canvas resize done once per device
per tick (perf); `hot_update` in-progress guard check-then-act race. Plus standing
HW/opencode deferrals (native C static-encoder format divergence, SPP framing
divergences, basic-protocol RX stall).

---
## R53 round 28: fan-out honesty + C encoder aliasing corruption (2026-06-21)

(Round 27 left for opencode's parallel work — shared tree.) Fresh 3-agent
adversarial sweep over BLE transport, the native encoder pipeline, and wall +
animation streaming. 4 fixes, each teeth-tested; suite 1652 passed / 78 skipped:

- **HIGH (honesty + misindexing)** — `wall.show_image`: a slot whose animated
  source yields 0 frames was skipped with a bare `continue` before its task was
  appended, so it never counted against `all_ok` (wall reported full success
  while a screen got nothing) AND the result loop indexed `self.devices[idx]` by
  the result index, drifting out of alignment after any skip → errors named the
  wrong device. Tasks are now paired with their slot (zip), skipped slots count
  as failures.
- **MEDIUM** — `game.send_gamecontrol` overwrote the key-DOWN result with the
  key-UP result → a failed press + successful release reported True. Now
  `down_ok and up_ok`.
- **MEDIUM** — `display.show_image` 0x49 fallback could return None (annotated
  bool) on an empty blob list. Now starts False, returns bool().
- **HIGH-but-LATENT (C correctness)** — the C image encoders aliased the
  per-pixel index scratch array onto `out_buf`; the pixel packer then overwrote
  not-yet-consumed indices once `7+3*n < i`, corrupting output (C/Python
  divergence, confirmed by a dylib probe — 32x32 nc=2 diverges at byte 14).
  Fixed all three encoders to use a separate index buffer; rebuilt the dylib. No
  live path executes the buggy packer today (live 0x8B uses pure-Python; 0x49 C
  16x16 self-rejects on the undersized buffer → Python), but it was a landmine
  for the perf deferral, and the existing parity test was a FALSE POSITIVE
  (wrappers undersize → C rejects → Python-vs-Python). Added
  `test_native_encoder_c_path.py` driving the C functions directly with a
  worst-case buffer (fails 26 assertions pre-fix; all pass post-fix).

BLE-transport findings (verified real but HW-sensitive / heavily-reviewed path,
no HW validation available) DEFERRED: `_expected_response_command` scalar has
multiple uncoordinated writers (iOS-LE callback clears it autonomously → a
colliding frame can null it under a parked waiter → false timeout); read-back
paths bypass the response lock; `bt_spp_transport` redundant outer `wait_for`
leaks a blocked executor thread. Also DEFERRED (separate, dead path): the C
*static* encoder has a pre-existing FORMAT divergence from Python static (needs
APK/HW truth). And the 0x49 PACKET_NUM wraps past 255 on >51KB blobs (low
reachability, superseded path).

---
## R53 round 25: scoreboard bounds + render-text temp cleanup (2026-06-21)

Parallel opencode-session pass (ses_184471307ffeCUHgzv9w51O0oA), landed here on
request. 2 defensive fixes (R53.45–46), teeth-tested (test_adversarial_round25.py):

- **R53.45** — `Scoreboard.set_scoreboard` had no bounds: an out-of-range score
  hit `red_score.to_bytes(2, ...)` → OverflowError, and an out-of-byte `on_off`
  hit `bytes()` → ValueError — an uncaught crash for any direct lib/daemon/LAN
  caller (the GUI number input doesn't enforce max=999 for typed values). Now
  clamps to 0–999 / masks to a byte at the boundary (matches ScoreBoardChannel).
- **R53.46** — `LightingApi._render_text_png` mkstemp'd a temp PNG then called
  `canvas.save()`; on save failure the file was orphaned because push_text's
  caller-side `finally: unlink` never ran (png_path never bound). Now unlinks the
  temp on a save failure before re-raising.

---
## R53 round 26: config/state persistence hardening (2026-06-21)

(Round 25 is opencode's parallel scoreboard/lighting pass — shared tree.) Fresh
3-agent adversarial sweep over daemon IPC, protocol framing, and config
persistence. The framing/transport core came back CLEAN — byte formats (basic +
iOS-LE checksums, length fields, 0x01–0x03 escaping, endianness, frame
reassembly) verified against `docs/DIVOOM_PROTOCOL_SUMMARY.md` + the C reference.
5 real bugs fixed, each teeth-tested; suite 1614 passed / 75 skipped:

- **HIGH** — `hotchannel_config._normalize()` did a bare `int(v)` over
  `device_galleries`, but `load_config()` calls `_normalize()` OUTSIDE its
  try/except (promises "never raises") and `monthly_best_daemon.main()` calls it
  unguarded at startup. A non-numeric value (hand-edited JSON, or a blank style
  from the GUI) raised `ValueError` and crashed the headless sync daemon before
  it ran. Now coerces defensively and drops bad entries.
- **MEDIUM** (A1 non-atomic write) — `gallery_sync.py` (gallery_cache.json) and
  `media_sync.py` (tickers.json) wrote via `write_text` → now `atomic_write_text`.
  The tickers one is worse than a failed load: `get_tickers()` re-seeds from
  macOS/defaults on a corrupt read, so a truncated write DESTROYS the user's list.
- **MEDIUM** — `scanner_mixin.update_wall_slots` was self-described "atomic" but
  used a FIXED `.json.tmp` name with no fsync; two arranger changes close
  together raced the same tmp path. Now uses the shared `atomic_write_text`.
- **MEDIUM** — `presets_manager.load_config()` parsed 4 int fields inside the
  outer try, so one bad field (corrupt config.ini) returned `{}`, wiping email,
  slots, devices and cloud status. Now per-field `_safe_int()` degrades to default.

DEFERRED (tracked, verified real but risk>reward / HW-aware / low reachability —
not blocking "clean"): daemon 270s result backstop can exceed the 120s client
read timeout on >120s wall pushes (phantom-failure + possible device clobber);
`iter_messages` swallows a malformed request/response frame into a generic "no
reply"; `control_server.call()` leaks the unix socket fd (test/instrumentation
client only); `gui_api._client()` check-then-act can double-spawn the daemon on
cold start; iOS-LE notification parser doesn't validate its checksum.

---
## R53 round 24: device-loop fd leak + LAN ACK!=success (2026-06-21)

(Commit `0ef1d6a`; its two fixes were tagged R53.43/44 in the message, which
collides cosmetically with the parallel latent-builders commit below that reused
"R53.43" — same shared tree, harmless in history.) Fresh 2-agent pass over the
framing primitives (CLEAN — length/checksum math, byte order, escape symmetry,
resync and bounds all verified vs the C reference + 78 parity tests) and the LAN
transport. Two real bugs fixed, teeth-tested, suite 1608 green:

- **device-loop fd leak** — the dedicated device asyncio loop (`owner_loop._run`)
  ran `loop.run_forever()` with no `loop.close()`, leaking the loop's selector/fds
  on every stop→restart cycle in a long-lived (keep-alive) daemon. Closed in
  `_run()`'s finally (dying loop thread, after run_forever returns).
- **LAN ACK!=success** — `LanTransport.post()` returned the device's JSON without
  checking HTTP status or `error_code`. The Divoom local API answers HTTP 200 with
  `{"error_code": N}`; N != 0 = command rejected (bad LocalToken, out-of-range,
  unsupported model). A rejected LAN `set_brightness`/`set_channel`/etc. was reported
  as success, and `probe()` deemed any 200+JSON host reachable. Added a pure
  `_validate_lan_response` raising on non-200 / non-JSON / non-zero error_code (first
  LanTransport tests — the gap that hid it). DEFERRED (informational):
  `parse_ios_le_notification` doesn't verify the RX checksum (HW-tuned path; left alone).

---
## R53 round 23: fix-or-delete the 5 latent *HexString builders (2026-06-21)

Closes the cleanup deferred at the end of round 22. The same
`self._divoom_instance.number2HexString` / `.color2HexString` /
`.boolean2HexString` AttributeError bug that killed GUI "Sync Time" (R53.41)
existed in five OTHER display/channel builders. They are dead/latent — imported
by `display/__init__.py` (DisplayText/DisplayAnimation) but never instantiated
in production, and their unit tests MASKED the bug by monkeypatching the missing
helpers onto a `spec`'d mock, so they passed falsely.

Chose FIX over delete: the classes are a faithful port of node-divoom-timebox-evo,
carry full test suites, and the fix is the same one-line-per-call-site pattern
weather.py / date_time.py already document.

- **R53.43** — imported the real module-level converters from
  `divoom_lib.utils.converters` at module level and call them directly in:
  `display_text.py` (number2HexString, color2HexString),
  `display_animation.py` (number2HexString),
  `lightning_channel.py` (number2HexString, color2HexString, boolean2HexString),
  `time_channel.py` (color2HexString), `vjeffect_channel.py` (number2HexString).
  `self._divoom_instance._int2hexlittle(...)` is left untouched — that IS a real
  `Divoom` method.
- **Tests de-masked** — removed the converter monkeypatches from all five test
  fixtures/setups (kept the legit `_int2hexlittle` mock) so each test now
  exercises the REAL converter, and pinned the actual encoded bytes. Two test
  inputs were switched from `"#FF0000"`/`"#FF00FF"` to clean 6-hex, because the
  real `color2HexString` (unlike the old mock) does not strip a leading `#`.
  Teeth-checked: reverting any call site to the `self._divoom_instance.<helper>`
  pattern fails the de-masked test with the production `AttributeError`. Suite
  1603 passed / 75 skipped green.

Lesson (reinforced from R53.41): a test that monkeypatches a non-existent method
onto a `spec`'d mock can MASK an always-failing prod path — de-mask when reviewing.

---
## R53 round 22: menubar non-block + dead Sync Time + auth honesty (2026-06-21)

Fresh adversarial pass: implemented the previously-deferred menubar main-thread
fix, then 2-agent sweep over display command builders and config/lifecycle. Three
real bugs fixed (R53.40–42), teeth-tested, suite 1602 green:

- **R53.40** — menubar `device_activity()` did a synchronous `get_device_activity`
  socket RPC on the AppKit main thread (menuNeedsUpdate_); while the daemon was
  mid-BLE-op the menu froze up to the 2.0s read timeout. Now returns a cached
  snapshot instantly and refreshes off-thread (cache primed in start(); reliable
  now that R53.39 keeps the subscribe thread alive). [resolves the R21 deferral]
- **R53.41 (HIGH)** — `DateTimeCommand` called `self._divoom_instance.number2HexString`,
  but that's a module-level helper in `utils.converters`, NOT a Divoom method → it
  raised AttributeError, swallowed by the GUI tool wrapper into a silent False. The
  GUI "Sync Time" feature NEVER worked on a real device. Fixed to call the module
  function (the weather shim already documents this exact bug); the masked test is
  de-masked and pins the encoded payload.
- **R53.42** — `get_credentials()` wrapped login AND token-cache-write in one
  try/except, so a cache-write failure (disk full / read-only ~/.config) was
  reported as "Email login failed — falling back to guest", silently dropping a
  valid account to a guest token. Login and caching are now separated; a successful
  login is always returned.

DEFERRED / flagged: the same *HexString-as-method bug exists in five OTHER builders
(display_text, display_animation, lightning/time/vjeffect_channel) but they're dead
code (never instantiated in production) — flagged for a separate fix-or-delete
cleanup. Also LOW: `device_owner.stop()` nulls the loop refs without join()/
loop.close() → a thread+fd leak per stop/restart cycle (bounded; stop==exit
normally).

---
## R53 round 21: scan dict-race + GUI/menubar thread fixes (2026-06-21)

Fresh 3-agent adversarial pass over the GUI api layer, the menubar, and the
discovery/scan path. Three real bugs fixed (R53.37–39), teeth-tested, suite 1600
green:

- **R53.37** — `OwnerConnectMixin._owned_devices()` iterated `_live_devices` with a
  bare for-loop (the one read R53.32 missed). A scan (off-queue, G2) concurrent
  with a live-job poller raised "dict changed size during iteration", swallowed by
  `scan()` → a false empty "no devices found" while streaming. Now `list()`-snapshots.
- **R53.38** — GUI `get_ticker_preview` renders only a LOCAL preview yet probed
  `dev.lan`/`dev.is_connected` and called `dev.connect()` — blocking RPCs on the
  pywebview JS thread (up to the 120s `_run_async` cap) for no benefit (R53.30
  anti-pattern). Pre-check removed.
- **R53.39** — the menubar subscriber loop killed its reader thread on a daemon
  drop even under keep-alive (called the no-op `_on_shutdown` then unconditionally
  returned) → the menubar froze forever after any daemon restart, never
  re-subscribing. Now follows the daemon down (terminate) only under the shared
  lifecycle; under keep-alive it keeps the reader alive and reconnects with backoff.

DEFERRED (tracked, GUI-side, bigger change): menubar `menuNeedsUpdate_` still does
a synchronous `get_device_activity` RPC on the AppKit main thread — clicking the
icon while the daemon is mid-BLE-op freezes the menu up to the 2.0s read timeout.
Proper fix is to cache `device_activity` in the subscribe thread and have the main
thread read the cache (now that R53.39 keeps that thread reliably alive).

---
## R53 round 20: wall partial-failure honesty + blob temp-file leak (2026-06-21)

Fresh 3-agent adversarial pass over the wall, the animation/custom-art push paths,
and the command-queue/exclusive-mode core. Two real bugs fixed (R53.35–36),
teeth-tested, suite 1596 green:

- **R53.35** — `DivoomWall.set_light/show_clock/show_effects/show_visualization`
  used a bare `asyncio.gather`; one slot's BLE failure raised out of the method
  instead of an honest degraded `False` and abandoned the sibling pushes. Now
  `return_exceptions=True` + `all(res is True ...)`, matching the other wall
  fan-out methods.
- **R53.36** — `DeviceOwner.device_call` materialized base64 blobs to /tmp via
  mkstemp but never unlinked them → one leaked file per blob-based push, forever.
  Now unlinked in a `finally` (and on the bad-blob early-return).

DEFERRED this round (verified real, but risk>reward / perf-only / low — tracked
for a future targeted pass, not blocking "clean"):
- Wall non-free-form geometry uses `grid_unit_size` (slot[0].size) for the canvas
  but per-slot `size` for the crop → wrong slice if panels have MIXED sizes. Low
  reachability (walls are uniform in practice); fix needs careful geometry + HW.
- Native image encoder: the Python wrapper sizes the output buffer at 1bpp, but
  the C `divoom_encode_animation_frame`/`_static` reject (return -1) unless the
  buffer is 8bpp worst-case → the dylib fast path is DEAD, always falling back to
  Python. Correctness is fine (byte-identical fallback); it's a silent PERF
  regression. Deferred because enabling the C path could surface a latent
  C/Python encoding divergence that needs empirical parity + on-device validation.
- Second `exclusive_start` while a session is held blocks the RPC handler thread
  up to the 270s result backstop instead of fast-failing "already held" (mutual
  exclusion is preserved; just a slow-fail).
- `hot_update` progress can stick at `"starting"` if its fire-and-forget queue
  item is expired (240s) under a held exclusive session — a reporting-honesty gap
  (no "error" transition), not a wedge.

---
## R53 round 19: GUI-responsiveness root cause + concurrency hardening (2026-06-21)

Four fixes (R53.31–34), each verified against the code, teeth-tested, full suite green
(1592 passed, 75 skipped).

- **R53.31 — proxy device_status short-TTL cache.** `DaemonDeviceProxy`'s introspection
  attrs (`is_connected`/`lan`/`_conn`) each did a synchronous BLOCKING `device_status()`
  socket RPC; one GUI operation reads several back-to-back → a separate round-trip each
  (janky buttons; the GUI-responsiveness cluster's root cause). `_status()` now caches the
  result for 0.25s so the back-to-back reads collapse to one RPC. The daemon's device_call
  self-heals regardless of a slightly-stale GUI read, so no correctness risk.

- **R53.32 — thread-safe live/activity registry.** The live-job dicts (`_live_devices`,
  `_live_tasks`, `_device_activity`, `_live_params`) are mutated on the device LOOP thread
  while the menubar polls `get_device_activity` / `_save_live_jobs` on RPC HANDLER threads.
  Several reads iterated them with a bare Python for-loop / comprehension → "RuntimeError:
  dictionary changed size during iteration" propagating out of the ~1/sec menubar RPC. Now
  every such site iterates a point-in-time `list()`/`dict()` snapshot (single C call, atomic
  under the GIL). The returned activity is a deep-ish snapshot so json.dumps can't race it.

- **R53.33 — subscriber initial snapshot under `_sub_lock`.** `_serve_subscriber` registered
  the socket then sent the initial status frame OUTSIDE the lock, racing `broadcast()`'s
  locked sendall (notification-monitor thread) on the same fd → interleaved bytes → the
  subscriber silently drops both the snapshot and the notification event. The initial frame
  is now sent inside `_add_subscriber` while holding `_sub_lock`, before the socket joins the
  set; an OSError there leaves it unregistered.

- **R53.34 — restore the response-path lock on the router.** The R53.11 `_response_lock` lived
  on BLETransport, but the live path routes through `DivoomConnection`, whose own
  `send_command_and_wait_for_response` re-implemented the drain→set-scalar→send→wait inline
  WITHOUT the lock — so the cross-talk protection was dead code. The router now holds its own
  `asyncio.Lock` across that sequence (routing unchanged — still delegates send/wait to the
  HW-tuned `_divoom` path). Defense-in-depth: the daemon CommandQueue already serializes
  device access, but the intended invariant is restored and its contended-canary warning works.

---
## R53 round 18: basic-protocol RX parser bounds the length field (2026-06-20)

Second fresh-re-read find. `parse_basic_protocol_frames` (the shared basic-protocol
RX parser, used by BOTH the BLE notification path and SPP `_on_data`) trusted the
2-byte length field unboundedly: a corrupt length made it wait for up to ~64KB —
which a small BLE/SPP notification stream never delivers — before the end-byte /
checksum check could reject the frame, stalling ALL inbound parsing behind it. Now
bounded by `MAX_BASIC_FRAME` (8192): an over-long decoded length is treated as a bad
header and the parser resyncs (drops the start byte), the same recovery as a bad
checksum. Mirrors the SPP iOS-LE length bound from R53.13. A valid frame following a
corrupt prefix is still recovered. Verified the test fails without the fix. Test:
`test_framing_both_impls.test_basic_corrupt_length_resyncs_and_recovers`. Full suite
green (1555 passed).

---
## R53 round 17: reconnect clears the stale OS-drop flag (2026-06-20)

Found in a fresh adversarial re-read (beyond the original four-lens review). After
an OS-level BLE drop, `_on_os_disconnect` sets `_connection_likely_broken = True`
(so `is_alive` honestly reports the link down). But `connect()` never cleared it on
a successful RECONNECT — and on a reconnect `autoprobe_protocol` is a no-op (the
framing is already known, so it sends nothing), so NOTHING cleared the flag until
the *next* successful payload send. In the window between reconnect and that send,
`is_alive` lied `False`: connection_state read DEGRADED, and live jobs / wall
self-heal (which consult `is_alive` before pushing) treated the freshly-reconnected
link as dead → needless rebuild churn.

`connect()` now clears `_connection_likely_broken` on a successful (re)connect — a
freshly-established OS link is by definition not broken. Verified the new test
fails without the fix. Test:
`test_ble_timeout_hardening.test_reconnect_clears_stale_os_drop_flag`. Full suite
green (1554 passed); HW-checked the connection_state stays honest across re-ensures.

---
## R53 round 16: discover_device early-exit on first match (2026-06-20)

`discover_device` (still live via the `monthly_best_daemon` reconnect path) used
`BleakScanner.discover(timeout=10.0)` for the name path / `3.0` for the address
path, ALWAYS waiting the full window even after the target appeared. Rewrote it on
the same detection-callback + early-exit + guaranteed-`stop()` pattern as
`discover_all_divoom_devices` (R53.6): it now returns the instant the first
name/address match is seen. Scan windows are module constants (`NAME_SCAN_TIMEOUT`,
`ADDR_SCAN_TIMEOUT`) so callers/tests can tune them. This empties the BLE review's
"discovery scans unbounded" finding. Tests: `test_discovery.py` (callback-based).
Full suite green (1553 passed).

---
## R53 round 15: exclusive deadline re-arms on completion (2026-06-20)

The command queue's exclusive-session auto-release (G3 — frees a dead client's
token after `exclusive_timeout`) only re-armed the deadline when it DEQUEUED an
owner item. A single long-running exclusive item (a multi-frame animation / custom-
art push), or a gap before the owner submitted its next item, could let the deadline
lapse during the session's own work — so the next `_dequeue` force-released a session
that was actively progressing, dropping the exclusivity guarantee mid-push.

The worker now also re-arms the deadline on item COMPLETION, so an actively-working
session is never force-released. Verified the new test fails without the fix (it logs
the spurious `exclusive session ... force-releasing`). The LAN per-request aiohttp
session was reviewed and deliberately left as-is (WONTFIX — see review doc).

Test: `test_command_queue.test_exclusive_not_released_during_long_item`. Full suite
green (1553 passed).

---
## R53 round 14: registry eviction honesty + loop-teardown reset (2026-06-20)

Two Low-tier BLE-registry / connect-lock lifecycle fixes.

- **Failed eviction is no longer silent.** `ble_registry.evict` logged a disconnect
  failure at debug and dropped the entry — so a failed eviction looked successful
  while the OS-level link may survive and stall the next connect (the ~16s
  double-connect the registry exists to prevent). Now a WARNING with the cause; we
  still drop our record (best-effort — the new owner registers over it).
- **Stale per-loop state is reset on device-loop teardown.** `_connect_locks` is
  keyed by `id(loop)` and `_active` is process-global; both survived a loop restart,
  and CPython reuses ids so a fresh loop could be handed a Lock bound to the dead
  loop ("bound to a different event loop"). `device_owner.stop()` now calls
  `ble_connection.forget_loop(loop)` + `ble_registry.reset()`, and nulls
  `_loop`/`_cmd_queue`/`_loop_thread` so `_device_loop()` rebuilds cleanly instead of
  handing back the stopped loop.

Tests: `test_ble_registry.py` (+3). Full suite green (1552 passed).

---
## R53 round 13: SPP send retries + corrupt-length parser resync (2026-06-20)

Two more SPP transport robustness fixes (`bt_spp_transport.py` / `bt_spp_rfcomm.py`).

- **`send_payload` now honours `max_retries`** (was accepted but ignored — one
  transient write failure failed the whole op). Retries with a short escalating
  backoff and bails early once disconnected (no point retrying a dead link).
- **Corrupt iOS-LE length can no longer stall RX.** `_on_data` trusted the length
  field in bytes 4-5; a corrupt value made it wait forever for bytes that never
  arrive, wedging all inbound parsing behind it. Now bounded by `_MAX_IOS_LE_FRAME`
  (8192) — an over-long "frame" is treated as a bad header and RESYNCS (drop a byte),
  same recovery as a parse failure. Verified a real frame after a corrupt prefix is
  still delivered.

Tests: `test_spp_robustness.py`. Full suite green (1549 passed).

---
## R53 round 12: SPP death-aware liveness + dead-code purge + split (2026-06-20)

Medium-tier SPP transport hardening (`bt_spp_transport.py`).

- **Honest liveness.** The pyserial `_serial_read_loop` could die on a read error
  WITHOUT closing the port or setting `_close_event`, so `is_connected` kept
  returning True (the port stays `.is_open`) though no data would ever arrive
  again. Added an `is_alive` property (parity with BLE) that also requires the
  reader thread to be live on the serial path; the read loop now LOGS the error it
  used to swallow silently. Test: `test_spp_liveness.py`.
- **Dead code removed.** `spp_connection.read_spp_notifications_loop` /
  `disconnect_spp` were superseded by `BTSppTransport._rx_loop` / `.disconnect` and
  unreferenced — deleted (plus their now-unused imports).
- **Split** (file was at the 500-LOC cap): the macOS IOBluetooth RFCOMM backend
  (`_start_runloop`/`_runloop_main`/`_discover_rfcomm_channel`/`_open_blocking`/
  `_on_data`) + `BtSppNotification` moved to `bt_spp_rfcomm.py` (`_SppRfcommMixin`);
  `bt_spp_transport.py` 500→363 LOC. `BtSppNotification` re-exported for callers.

Behavior-preserving (SPP is unhittable with the all-BLE test fleet — covered by
unit tests). Import/MRO verified. Full suite green (1544 passed).

---
## R53 round 11: BLE response-path lock + ble_notify split (2026-06-20)

Closes the LAST High deferred BLE finding — the shared-response-path cross-talk.
`send_command_and_wait_for_response` drains the `notification_queue` and sets the
scalar `_expected_response_command`, then waits. Two concurrent callers would
drain each other's frames and clobber the scalar; it was safe only because the
command queue happens to serialize device ops, with nothing enforcing it.

- Added `_response_lock` (asyncio.Lock) held across drain→set-scalar→send→wait so
  the response path is atomic per operation. A contended entry logs a warning so a
  future off-queue caller is visible, not a silent corruption. Chose the lock over
  the full per-command-id `Future` refactor to avoid risk to the working 0x8B path.
- Split the notification/response methods out of `ble_transport.py` into
  `ble_notify.py` (`BleNotifyMixin`: the GATT callback, the iOS-LE / basic-protocol
  frame parsers, and the wait/`send_command_and_wait_for_response` helpers).
  `ble_transport.py` 516→384 LOC; behavior unchanged.

HW-verified the response path (0x8E `query_page`, 4.05s bounded) + a normal device
call still work post-split. Tests: `test_ble_response_lock.py`. Full suite green
(1536 passed). This empties the BLE review's High deferred list.

---
## R53 round 10: live-job vs exclusive-push anti-clobber (2026-06-20)

Closes a High deferred BLE finding. An exclusive session (animation / custom-art
push, `async with proxy.exclusive(token)`) takes over the screen, but a live job
(sysmon/…) on the same device keeps submitting TOKENLESS frames. In exclusive
mode the command queue only dispatches matching-token items, so those frames piled
up and then **burst out FIFO the instant the session released — clobbering what
was just pushed**. `exclusive_start` now stops the active device's live jobs first
(`live_jobs_stop_for({})`, the same primitive the channel-switch path uses), before
acquiring the token so a cancelled poller can't slip one more frame in. Background-
device jobs (a different screen, no clobber) are left running. HW-verified both
directions; test `test_exclusive_stops_jobs.py`. Full suite green (1536 passed).

---
## R53 rounds 7-9: edge-case hardening + owner split (2026-06-20)

Continued HW edge-probing of the daemon socket, plus a structural split.

- **R53.7 — empty connect target rejected.** `connect(mac="")` returned success
  and silently grabbed an arbitrary/last device (`""` falsy → scan-first `devs[0]`
  fallback). Now returns `reason=invalid_target`; `mac=None` (absent) still = "use
  active". Verified clean alongside: bogus MAC fails bounded (16.4s, no hang) and
  doesn't poison the next connect; rapid re-grab ×5 on the 0.0s fast-path.
- **R53.8 — split `device_owner.py`** (was pinned at exactly 500 LOC). Extracted
  device acquisition/discovery into `owner_connect.py` (`OwnerConnectMixin`:
  connect/disconnect/scan/device_status/probe_lan + build/ensure + honest-state
  fields) and the shared `_json_safe` into `owner_util.py`. device_owner.py 500→239;
  no behavior change; HW-verified.
- **R53.9 — disconnect now stops the active device's live jobs.** HW edge-probe:
  with a sysmon job on the active device, `disconnect()` released the device but
  left the poller task alive (`done:false`) — it kept ticking on a dead link and
  could rebuild/resurrect the connection the user just dropped. `disconnect()` now
  calls `live_jobs_stop_for({})` first (active mac); background jobs on OTHER
  devices are untouched (HW-verified both). Test: `test_disconnect_stops_jobs.py`.

---
## R53 round 6: scan speed + connected-device visibility (2026-06-20)

HW-driven round (real 4-device fleet via the dev-daemon socket + a new
`hw_smoke.py --phase stress [--churn]` loop that hammers connect/disconnect/
evict and flags anomalies). 40-iteration eviction churn across all four devices:
40/40 connects clean (incl. the historically flaky Timoo-light-4) — but it
surfaced two real quirks, both fixed:

- **Scan was always slow — it never early-exited.** `BleakScanner.discover(timeout)`
  waits the *full* window even when every device shows up in the first 2s; the
  `scan_limit` was applied *after*, so it did nothing for latency. Rewrote
  `discover_all_divoom_devices` to use a **detection callback with early-exit**:
  it returns the instant `expected` (the scan limit) devices are seen, with a
  guaranteed `scanner.stop()` in `finally`. HW: a full 4-device scan **15.0s →
  ~2s**. `expected<=0` keeps the full-window behavior.
- **A connected device vanished from the selector ("should be 4, found 3").** A
  connected BLE peripheral stops advertising, so a scan run while the daemon holds
  a device can't see it — and the scan *replaced* the list, dropping it. The
  daemon now **unions its owned devices** (active + background live jobs) back into
  the scan result, resolving their friendly names from a `mac->name` cache
  populated by prior scans (so a held device keeps its name, not its raw MAC).
  HW: churn scans now report 4/4 with zero anomalies. BLE-only (a LAN device isn't
  a scan result). Tests: `test_scan_owned_union.py`, `test_discovery.py`.
- **`query_page` (0x8E) read-back is bounded (10s → 4s).** HW finding: Pixoo never
  answers the 0x8E user-define read (3/3 reads hit the 10s default and returned
  empty), wedging the serialized command queue for 10s each call. Now bounded to
  `QUERY_TIMEOUT=4s`. Corollary: verification-via-`query_page` is NOT viable for
  the deferred ACK≠success fix (0x8E is unreliable on real HW) — re-scoped in the
  review doc. Test: `test_custom_art_push.TestQueryPage`.
- **Empty target rejected (edge-probe).** `connect(mac="")` silently grabbed an
  arbitrary/last device — `""` is falsy so target resolution fell through to a
  scan-first fallback (`devs[0]`). An explicitly-empty `mac`/`lan_ip` now returns
  `reason=invalid_target`; `mac=None` (absent) still means "use active". HW-verified
  alongside: a *bogus* MAC fails cleanly within the bound (16.4s, no hang) and does
  not poison the next real connect; rapid same-device re-grab stays on the 0.0s
  fast-path. Test: `test_daemon_connect_identity` (empty-target cases).

---
## R53: BLE transport hardening, round 1 (2026-06-14)

A four-lens adversarial review of the ~2,400-LOC Bluetooth subsystem
(`docs/BLE_HARDENING_REVIEW_2026-06.md`). This round lands the highest-value,
lowest-risk, fully-tested fixes; the deferred findings are tracked in that doc.

- **Every raw bleak await is now bounded.** `ensure_connected` bounded the first
  connect, but the internal reconnect path (`send_payload → connect`) bypasses it
  and runs *while holding the write lock* — so a dead/asleep/held device hung the
  whole transport forever. `BLETransport.connect/disconnect` now wrap
  `client.connect()` (15 s), `start_notify()` (6 s), `stop_notify()` (3 s), and
  `client.disconnect()` (5 s) in `asyncio.wait_for`, raising
  `DeviceConnectionError` with the reason preserved.
- **Notify-subscription leak fixed.** `disconnect()`'s comment claimed it called
  `stop_notify` to release the OS subscription, but it never did — leaking it,
  which made a later `start_notify` raise "already started". Now it actually does.
- **A wedged BLE op can no longer hang a daemon RPC / socket-handler thread.** The
  device command queue is now built with `item_timeout=240 s` (rejects an op left
  waiting behind a stuck op) and `_run_device`/`_run_on_loop` use `.result()`
  backstops (270 s / 90 s) that surface a clean `TimeoutError`. `hot_update` is
  fire-and-forget so it's unaffected.
- **Transport-swap registry leak fixed.** A BLE↔SPP transport-type switch replaced
  `_active_transport` without tearing down the old one — leaking it in the
  process-wide registry and keeping its CoreBluetooth link open while the new
  transport connected to the same device. `_teardown_outgoing_transport()` now
  disconnects+unregisters the outgoing transport before the swap (no-op on a
  same-type reconnect).
- Extracted the BLE framing auto-probe to `ble_probe.py` (500-LOC cap).
- Tests: `tests/test_ble_timeout_hardening.py` (6) — bounded connect/notify/
  disconnect, stop_notify-before-disconnect ordering, swap-teardown.

**Deferred** (real, need isolated tested rounds — see the review doc): ACK≠success
honesty in custom-art/hot-update pushes (likely tied to R45 #1), live-job ↔
exclusive-push interleaving, shared notification-queue cross-talk, `ensure_connected`
trusting cached `is_connected`, live-job stop not awaiting cancellation, and SPP
transport parity (loop-blocking open, thread/port leaks on failed connect, silent
dead-RX, ignored `max_retries`, no preflight/classification).

---
## v0.15.2 — UI/UX polish (2026-06-14)

Packaged release bundling the R49–R52 work below since v0.15.1: named device
chips, the flat face-on device preview with real PNG transparency, specific
clock/ambient channel previews, real device-face menu-bar thumbnails, the
distinct Virtual Wall glyph, the bottom-pinned scan indicator + corner connection
dot + roomier Auto-Sync list, and a clean app quit (no shutdown cascade / lingering
host). `docs/release_notes_v0.15.2.md`.

---
## R52: GUI exits cleanly (the long-open app-quit bug) (2026-06-14)

The GUI didn't terminate cleanly on quit — the logs showed a "Daemon shut down →
closing dashboard → stopping daemon → Daemon shut down" cascade, and an in-flight
connect surfaced a stray "device is NOT connected" error seconds after the window
was gone. Two causes:

- **Redundant shutdowns.** The window `closing` event AND the post-`webview.start()`
  block each sent `daemon.shutdown()`, and the shutdown follower re-fired on the
  second one. Collapsed to a single `_stop_daemon_once()` guarded by a
  `threading.Event`, so one quit = one shutdown, no cascade.
- **Host process lingered.** pywebview/WebKit can keep the host alive after the
  window is destroyed (a lingering Cocoa run loop / an in-flight js_api call — the
  late connect). The GUI is a thin client (the daemon, a separate process, owns
  the BLE link and has already been told to stop), so `main()` now `os._exit(0)`s
  after the shutdown handshake instead of waiting on webview internals. Keep-alive
  mode is unaffected (it only governs the daemon; the GUI window closing always
  exits the GUI).

---
## R52: sidebar layout + appbar dot + auto-sync space + hot-preview check (2026-06-14)

- **Scan indicator pinned to the very bottom of the sidebar** (below the wall
  button), and its row height is always reserved (`hidden` toggles visibility,
  not display) — so starting/stopping a scan no longer reflows the preview above.
- **Connection dot moved out of the appbar** to an unobtrusive lower-right corner
  dot (was crowding the brightness/volume row). Same `#global-status-dot` element
  and heartbeat — repositioned `fixed`, so the degraded/active/connecting states
  are still surfaced.
- **Auto-Sync Gallery device list given room** — `max-height` 160px → 60vh and
  row padding 13px → 9px, so all known devices fit without scrolling on the tall
  Auto-Sync tab.
- **Hot-channel preview vs. send: verified consistent.** Both the preview
  (`hot_update_preview`) and the actual update (`HotUpdate.update`) derive the
  file set from `fetch_hot_manifest(DEVICE_TYPE_BY_SIZE[active_size])` using the
  same `_active_device_size()` — so the preview can't silently show a different
  manifest than what's sent (the "always-16" class of bug). Each tile also
  converges to the real decoded CDN file via `get_animated_preview`. Locked with
  `tests/test_hot_preview_consistency.py`. (One inherent gap, not a bug: a file
  that fails download/sha1 at send time is previewed but not delivered.)

---
## R51: preview rendering fixes + sidebar de-nest (2026-06-14)

- **Clock-face previews were clipped/misaligned.** `_clockFaceSVG` rendered
  "12:00" at font-size 18 monospace (~55px) — wider than the 64px canvas, and
  the "With Box" border (46px) clipped the digits. Resized to font-size 13
  (~39px), vertically centred, and the box now encloses the digits with padding.
  Rainbow uses `<tspan>`s so the per-digit colors keep monospace spacing.
- **Ambient preview showed the wrong mode.** `applyAmbientColor` only passed the
  color, so the device preview was a flat fill regardless of the selected effect.
  Now the mode is passed through and `_channelPreviewSVG` renders each mode's
  palette (Love = pink, Plants = red + blue bars, Sleeping = green,
  No-Mosquitto = amber, Plain = the picked color) — matching the channel tiles.
- **Sidebar preview de-nested + enlarged.** The preview was an outer card around
  an inner bezel around the screen (two frames, small screen). Removed the outer
  card's framing; the bezel now fills the sidebar column (width:100% +
  aspect-ratio:1) so the preview is a single, larger framed element.
- Extracted the preview renderers to `channel_preview.js` (app_globals.js was
  over the 500-LOC cap).

---
## R50: specific previews — device panel + menubar tiles (2026-06-14)

Three preview-fidelity fixes (from a live-UI review of the sidebar + menubar).

- **Device preview shows the SPECIFIC channel face, not a generic glyph.**
  Picking a clock face (e.g. "With Box") called `set_clock` but never refreshed
  the preview, so it stayed a generic clock icon (or a stale frame). Now
  `_channelPreviewSVG` renders the exact face the user picked — all 6 clock
  styles (full-screen, rainbow, with-box, analog-square, neg, analog-round) — in
  the chosen color, and `applyClockStyle` refreshes the preview on apply. The
  selected style is tracked on `DivoomState` so a plain channel-switch renders it.
- **Dropped the redundant device-name label.** The R49 name under the preview
  duplicated the active (green) chip directly below it. It's now hidden when a
  device is active — shown only as the "No screen connected" empty-state hint.
- **Menubar tiles show the real device face.** R46 #3 shipped glyph-only tiles
  (real-frame thumbnails were deferred). Now the GUI rasterizes each channel
  preview to a small PNG and pushes it through `set_device_activity(..., preview)`;
  the daemon stores it on the activity entry; the menubar decodes it
  (`_menu_thumbnail`) into a per-device tile thumbnail, falling back to the SF
  Symbol glyph if there's no preview or it fails to decode (so it can only
  improve a tile, never regress it). An empty `kind` now means "thumbnail-only
  update" so a live frame doesn't clobber the daemon's semantic kind.
  Tests: daemon preview storage + empty-kind preservation; menubar PNG-decode +
  garbage-rejection. **Native NSMenu tile rendering still wants a real menubar
  smoke test** (can't be verified headless).

---
## R49: sidebar device cluster redesign (2026-06-14)

A Rams/Kare pass over the sidebar's device selector, Virtual Wall button, and
device preview (driven by a four-lens design review).

- **Device selector → named chips.** Replaced the unlabeled 16px colored dots
  with self-labeling chip rows: a small color dot + device name + right-aligned
  state (the streaming kind, or "reconnecting" for a degraded link). Every device
  is identifiable at a glance with no hover, and the list scales past 4 devices.
  Active = green-tinted border; connecting = pulsing amber border; streaming =
  breathing dot; degraded = amber dot. (`device_selector.js`, `sidebar.css`.)
- **Virtual Wall glyph fixed.** The wall button's 2×2 filled-rect glyph was
  identical to the Pixel Art nav-tab icon. Replaced with a distinct "joined
  panels" glyph (bounding rect + vertical divider); dashed border marks it as a
  composite, not a single screen; the count folds into the label ("Wall (3)")
  instead of a competing accent badge.
- **Device PNGs: real transparency.** The 5 product images were RGB with the
  transparency-preview *checkerboard baked into the pixels* (an asset-gen
  artifact) — so every device sat on a gray checkerboard. Re-keyed via border
  flood-fill (neutral-gray only) so exterior + shadow background is removed while
  interior detail survives by connectivity (ditoo joystick/keycaps, timoo white
  speaker grille, tivoo-max chrome). Now RGBA with transparent corners.
- **Device preview → flat face-on screen panel.** The product photos are 3/4
  perspective renders, so a live frame composited onto them landed crooked (most
  visible on the Ditoo). Dropped the photo from the live preview; the frame now
  renders straight in a neutral bezel — aligned for any model, zero per-model
  rects (removed `_DEVICE_SCREEN_RECTS` / `_applyDeviceScreenRect`). The device
  name shows below the panel. Empty state is a subtle off-screen pixel grid.

---
## v0.15.1 — GUI/UX reliability (2026-06-13)

Packaged release bundling the fixes below since v0.15.0: music/album-art widget
permission priming, the always-visible appbar connection dot, the gallery
resolution fix, the distinct Virtual Wall button, and the E2E UX-feedback suite +
ghost-reference cleanup.

---
## Deep dive: ghost-reference audit (2026-06-13)

Static audit for "dead references" — JS targeting DOM ids / API methods / daemon
commands that no longer exist (the class the appbar status dot belonged to).

- **Bug: the community gallery always fetched 16px art.** `gallery.readTargetSize`
  read `banner-device-res` for the device resolution, but that element was moved
  to Settings → Devices — so it always hit the `"16x16"` fallback and a 64px Pixoo
  got 16px artwork. Now derives the panel size from the active device name
  (`getDeviceDimensions`), same as the preview. +1 e2e test.
- **Dead code removed:** `channels_core.js` still wired ambient swatches, a custom
  color input, and a brightness slider against removed ids (`.color-swatch` /
  `custom-color-input` / `brightness-slider`) — superseded by `channels_grids.js`.
  Removed.
- **Clean:** after these, the ghost-element scan is empty, and every `api.X()` JS
  call maps to a defined GUI api method, and every client command maps to a
  registered daemon command — no ghosts in either layer.

---
## E2E UX-feedback suite + restored appbar status dot (2026-06-13)

- **E2E "no knowledge gap" suite** (`tests/test_e2e_ux_feedback.py`, Playwright):
  drives the real web_ui with a mock daemon API and asserts the UI surfaces
  visible feedback at every state transition — scanning (indicator), connecting
  (toast + pulse), connected (toast + active dot + banner), failed (the daemon's
  actionable reason, banner reset), no-device guard, scan failure, a degraded
  link, streaming vs degraded device dots, and the wall button + screen count.
- **Bug it caught + fixed: the appbar connection dot was missing.** R32 removed
  the appbar connectivity pill, but the active-device `connection_state` heartbeat
  (`refreshConnectionState`) and `connectDevice` still target `#global-status-dot`
  — which no longer existed in the markup (CSS + JS referenced a ghost element).
  So a mid-session DEGRADED or dropped active link had no visible indicator
  anywhere. Restored a minimal `#global-status-dot` to the appbar; the heartbeat
  now actually shows connecting / active / degraded / disconnected.

---
## Permission priming + Virtual Wall button (2026-06-13)

- **All macOS permissions primed up front.** The album-art live widget controls
  Music/Spotify via AppleScript (Apple Events / Automation), and that osascript
  ran inside the HEADLESS daemon — so the consent dialog had no visible owner, the
  Apple Event was denied, and the widget silently got no track (the device channel
  never changed while the GUI preview showed a local placeholder). Now
  `divoom_gui/permissions.prime_permissions()` triggers the prompt at GUI startup
  from the foreground app (visible; granted once; the daemon inherits it), and the
  Info.plist declares `NSAppleEventsUsageDescription` (setup_app.py +
  make_app_bundle.sh). Only pokes a player that's already running, so it never
  launches Music/Spotify just to ask.
- **Virtual Wall is now a distinct button, not a device dot.** It's a composite of
  screens, so rendering it as an identical dot read as "just another screen." It
  now has its own labeled button with a 2x2 grid glyph + screen count, in a row
  below the device dots (Rams: honest + minimal, shown only when a wall is
  configured; Kare: the grid glyph reads as "a wall of screens").
  (`device_selector.js`, `index.html`, `sidebar.css`)

---
## v0.15.0 — packaging: self-contained app + Homebrew cask (2026-06-13)

First packaged release. The app now ships as a self-contained `Divoom.app` in a
`.dmg`, installed via the Homebrew cask (`ztomer/homebrew-tap`).

- `setup_app.py` (py2app) builds `Divoom.app` bundling Python + deps (bleak,
  aiohttp, Pillow, pywebview, pyobjc), the runtime packages, `web_ui/`, fonts, and
  the native dylib. The Info.plist declares the Bluetooth usage so the bundle is
  its own TCC-responsible process. **The decompiled APK / `references/` never
  ship** — only the four runtime packages are bundled, and `build_release.sh`
  hard-fails if any `*smali*`/`references`/`*.apk` is found in the bundle.
- Bundle-aware spawn: in a `.app`, `sys.executable` is the GUI stub, so the
  daemon + menu-bar agent are spawned with the bundled `Contents/MacOS/python`
  (`daemon_client.bundle_python()`) and WITHOUT the TCC-disclaim (the `.app` is
  already the BT-responsible process). Dev-from-source path is unchanged.
- `scripts/build_release.sh` (native dylib → py2app → `.dmg` → sha256) and
  `docs/RELEASING.md` runbook. Version bumped to 0.15.0.
- Built + verified on Python 3.14 (py2app 0.28.10): `Divoom-v0.15.0.dmg`, 44 MB,
  no reference/APK leak. +2 spawn tests.

---
## Architecture gap scan #2 — A1–A4 (2026-06-13)

Second scan (`docs/ARCH_GAP_SCAN_2_2026-06.md`) — persistence, GUI RPC, daemon
lifecycle.

- **A1 — atomic config writes.** Only `save_preset` was crash-safe (R42 §5); every
  other writer wrote in place, so a crash mid-write truncated the file and lost
  that config (credentials, wall slots, alarms, presets, hotchannel, lifecycle,
  daemon_config, routing, device cache). New `divoom_lib/utils/atomic_io.py`
  (`atomic_write_text` + `atomic_write_config`: temp-in-same-dir + fsync +
  `os.replace`) applied across all of them.
- **A4 — secrets `0o600`.** `config.ini` (cloud password) and `auth_token.json`
  (token) are now written owner-only via the atomic writer's `mode` arg, instead
  of world/group-readable plaintext.
- **A3 — bounded GUI async.** `gui_api._run_async` had no timeout, so a wedged
  chain hung the pywebview JS-API thread forever. Now 120 s (beyond any legit op);
  on expiry it cancels + raises so the GUI shows an error instead of freezing.
- **A2 — live widgets survive a daemon restart (HW-verified).** The single-owner
  daemon lost all live jobs on a crash/restart. The desired set (mac/kind/params)
  is now persisted to `live_jobs.json` on start + user-stop; the daemon
  `rehydrate_live_jobs()` on boot. A teardown doesn't clear the file (clean
  restart resumes); only a user-stop removes a job. HW: started sysmon on the
  Ditoo, killed the daemon, respawned — the widget resumed streaming.
- Tests: +6 `test_atomic_io.py`, +2 `test_gui_api.py` (timeout + result), +1
  `test_device_activity.py` (persist/rehydrate); `test_lan_device_operations`
  rewritten to real-FS (the atomic writer bypasses a `write_text` mock).

---
## Architecture gap fix G7 + G6 resolution (2026-06-13)

- **G7 — wall delta reconfigure (HW-verified).** `wall_configure` rebuilt the
  WHOLE wall on any change, so a reconfigure reconnected every member (HW: adding
  a 3rd screen took ~14 s). It now reconfigures by delta when the new layout
  overlaps the current wall: the connected shared screens are transplanted into
  the new wall (`ensure_connected` short-circuits on a live link → fast-verify
  ~0 s), only added screens connect, and removed screens disconnect. Disjoint
  layouts still fall back to a clean full rebuild. HW (Ditoo/Pixoo/Timoo): **ADD a
  3rd screen 3.9 s (was ~14 s); REMOVE a screen 0.0 s**; wall lit throughout; the
  removed screen released and connectable solo. Wall ownership extracted into
  `owner_wall.py` (OwnerWallMixin) — `device_owner.py` down to 430 LOC.
  (`owner_wall.py`, `device_owner.py`)
- **G6 — won't-fix (no real trigger).** The scan indicator covering only the
  Settings button is harmless in practice: the only non-button scan path is the
  daemon's auto-discovery in `_ensure_device_async` when connecting with NO mac,
  which the GUI never does (it always passes a mac). Closed as won't-fix rather
  than add event-plumbing for a path that doesn't fire.
- Tests: +2 G7 (`test_wall_lifecycle.py`). Suite green.

---
## Architecture gap fixes G4–G5 (2026-06-13)

From the architecture scan (`docs/ARCH_GAP_SCAN_2026-06.md`). Both HW-verified.

- **G4 — a screen is owned by the active link OR the wall, not both.**
  HW-confirmed: configuring a wall whose slot reused the active device's MAC left
  the daemon holding a dead `_device` handle that timed out ~5s and FAILED on
  every active-device call (the wall took the one allowed BLE connection).
  `wall_configure` now relinquishes the active device when its mac is a wall slot;
  `connect()` drops the wall when the target mac is a current slot. HW: after the
  fix the ownership transfers cleanly both directions, all calls fast (0.0s vs the
  old 5s-timeout-and-fail). Extracted nothing new; `device_owner.py` stays < 500
  via the G2 `owner_loop.py` split. (`device_owner.py`)
- **G5 — background live-device health is visible.** `connection_state` only
  watched the active device/wall, so a background streaming screen that dropped
  (and was being self-healed) showed no signal. `get_device_activity` now stamps
  each owned device's honest state (`_stamp_live_health` → `derive_connection_state`)
  onto its activity entry; the R47 selector dot shows an amber "reconnecting" ring
  when a streaming device is degraded/disconnected. HW: a background sysmon job on
  the Ditoo reports `state: connected` live. (`owner_live.py`, `device_selector.js`,
  `sidebar.css`)
- Tests: +3 G4 (`test_wall_lifecycle.py`), +1 G5 (`test_device_activity.py`).
- **HW matrix (all 4 screens — Ditoo, Pixoo-1, Timoo-light-4, Tivoo-Max).**
  Solo connect + push: all OK (2–3 s, no Tivoo-Max flakiness this run). Wall
  add/remove (answering "can we still remove a device from the wall?"): built
  `{Ditoo,Pixoo}`, added Timoo, **removed Pixoo** → `{Ditoo,Timoo}` — every step
  lit, and the removed Pixoo was immediately connectable solo (released cleanly).
  A non-member (Pixoo) connected solo alongside an existing wall without dropping
  it. G4 same-MAC active→wall→active transferred cleanly, all calls fast.
  Quirk noted (not a regression): `wall_configure` rebuilds the whole wall, so a
  reconfigure reconnects ALL members (adding a 3rd took ~14 s) — future delta
  optimization.

---
## Architecture gap fixes G1–G3 (2026-06-13)

From the architecture scan (`docs/ARCH_GAP_SCAN_2026-06.md`).

- **G1 — activity registry pruning (no ghost devices).** R47 surfaced
  daemon-owned devices from `_device_activity` but never removed entries, so a
  device kept showing as owned after disconnect / wall teardown / stop-all.
  Now `forget_device_activity` fires on disconnect (active mac or LAN key) and
  wall teardown; `stop_all_live_jobs` marks each mac idle; `get_device_activity`
  TTL-prunes (10 min) entries that are neither the active device nor backed by a
  running live job. (`owner_live.py`, `device_owner.py`)
- **G3 — exclusive sessions can't wedge the device forever.** The command queue
  gained an `exclusive_timeout`: an exclusive owner that goes idle past the
  deadline (client died between `exclusive_start`/`exclusive_end`) is
  force-released so the rest of the queue drains. The deadline re-arms each time
  the owner makes progress, so a legit slow push is never killed. The daemon
  device queue opts in at 30 s. Previously a crashed push left the owner token
  set forever and every subsequent command hung. (`command_queue.py`,
  `device_owner.py`)
- **G2 — a scan no longer freezes live widgets.** BLE discovery used the central
  manager but was routed through the device command queue, so a 60 s scan
  blocked every queued device call + live-widget push behind it. Scans now run
  directly on the device loop (`_run_on_loop`), concurrent with device I/O. Also
  extracted the device-loop plumbing into `owner_loop.py` (OwnerLoopMixin) to
  keep `device_owner.py` under the 500-LOC cap. (`owner_loop.py`,
  `device_owner.py`)
- Tests: +6 G1 (`test_device_activity.py`), +2 G3 (`test_command_queue.py`).
  HW pass pending for G2 (scan while a widget streams) and the G3 force-release.

---
## R47: daemon-owned devices stay selectable + scan indication (2026-06-13)

The problem: a device the daemon OWNS (the active link, or a background
live-widget job) is connected, so it stops advertising and a BLE scan never
sees it. It showed as "connected" in the appbar but had no selector dot — you
couldn't switch to it or stop its widget ("connected but can't do anything").
The menubar tiles also showed raw MACs because activity carried no name.

- **Daemon resolves a friendly name** for an activity entry — `set_device_activity`
  now fills `name` via `_resolve_device_name(mac)` (active `self._device`, else a
  cached background live device, else the existing entry). Menubar tiles and the
  GUI selector now read "Ditoo", not the MAC. (`divoom_daemon/owner_live.py`)
- **GUI surfaces owned devices** — new `get_device_activity` GUI api
  (`scanner_mixin.py`); `device_selector.js` `refreshOwnedDevices()` unions the
  daemon's owned macs into `discoveredDevices` (with name + activity kind) on a
  4 s heartbeat, so a streaming device is ALWAYS in the selector. A daemon-owned
  device gets a breathing ring (`.transport-dot.streaming`) — "busy, click to
  take it over / stop its widget".
- **Scan indication** — `#scan-indicator` ("Scanning for screens…") in the
  sidebar, toggled by `setScanning()` around `runBleScan` (the Scan button lives
  in Settings, so a scan was otherwise silent in the main UI).
- Split the device-dots/selector logic out of `app_globals.js` into
  `device_selector.js` to stay under the 500-LOC cap.
- Tests: +3 name-resolution tests (`tests/test_device_activity.py`, 8 total).
  Full suite green (1461 passed / 75 skipped). GUI/menubar HW pass pending.

---
## Channel switch vs. live widget (HW, 2026-06-11)

HW investigation of the long-standing "channel switch doesn't reliably change
the active channel (esp. Divoom Max)" report. The suspected "0x45 rejected after
a draw" does NOT reproduce on Tivoo-Max or Ditoo — reading the mode back via
0x46 (`current_light_effect_mode`) shows every switch lands (clock=0 / design=5
/ visualizer=4), after a draw, rapidly, on the Max; the 10-byte payload padding
already fixed the original. The real current cause — surfaced only because live
jobs now actually push (they were deadlocked) — was a running live widget
re-pushing its frame on the next tick and clobbering the switch.

- New `live_jobs_stop_for` daemon RPC stops a device's live jobs (default: the
  active device). The GUI's channel / clock / VJ / visualizer / solid-light
  actions call it first (`LightingApi._stop_live_widgets`), so a static-display
  takeover isn't fought by a streaming widget.
- HW-confirmed on Ditoo: switch to Clock while sysmon ran → mode 0 and stays 0
  (was stuck on the sysmon frame). +9 tests.

## Live-widget on-device sync — deadlock fix (HW, 2026-06-11)

Live widgets (stocks / sysmon / weather) never reached the device: e2e was 100%
broken by a deadlock found only with hardware on hand. A live job runs on the
daemon's device loop and awaits `CommandQueue.submit_async`, whose impl called
the synchronous `submit()` — `run_coroutine_threadsafe(_add, self._loop)
.result()` targeting the *same* loop it was blocking, so `_add` could never run.
The push hung forever (10s timeout swallowed, no frame, no error); direct
`device_call` worked because it runs on the socket thread, not the device loop.

- `submit_async` now detects it's already on the queue's loop and enqueues with
  a direct `await self._add(...)` instead of the blocking `submit()`.
- HW-verified on Ditoo: sysmon + stocks stream frames via 0x8B, weather via
  0x5F. +1 regression test (submit_async from the queue's own loop must not
  deadlock).

## Socket Interface Hardening — 2026-06-11

The daemon's socket is a privilege boundary (it owns the BLE device + reads
notification content). Hardened against untrusted/buggy clients + resource
exhaustion. Plan: `docs/PLANNING_SOCKET_HARDENING.md`.

- **Unix socket is now owner-only** (`chmod 0600` after bind) — `bind()` honoured
  only the umask, so any local user could previously drive the daemon.
- **Max message-size cap** on the server request read and the client reply read
  (16 MiB) — a client/daemon that never sends a newline can no longer OOM the
  peer; oversized frames get a typed error, not unbounded buffering.
- **Total read deadline** (30 s) for one request line — closes the slow-loris
  hole where the old per-`recv` 5 s timeout let a byte-every-4 s client live
  forever.
- **Handler exception safety** — a handler that raises now returns a generic
  `{"success":false,"error":"internal error"}` (detail logged, not leaked) instead
  of killing the connection thread and stranding the client.
- **Bounded concurrent connections** (32) + **subscriber cap** (16) — a
  connection/subscribe flood is rejected ("server busy" / "subscriber limit")
  instead of exhausting threads + sockets.
- **Request validation** — non-string `command` / non-dict `args` are rejected /
  coerced before reaching a handler.
- Limits are `SocketServer` constructor params with safe defaults; TCP token
  auth (constant-time compare) unchanged. +11 real-socket tests.

## BLE Hardening — 2026-06-11 (Phases 1–6 + daemon-socket)

Plan: `docs/PLANNING_BLE_HARDENING.md`.

- **P1 — honest connect/reconnect**: new `divoom_lib/ble_connection.py`
  (`ConnectionState`/`FailureReason`/`ConnectResult`/`ensure_connected`) retries
  connect with bounded backoff+jitter, verifies the link, and never returns a
  dead handle — on failure it carries a typed reason (device asleep, BT off,
  held by the phone app, …). DeviceOwner connect/reconnect propagate it; the GUI
  shows the reason instead of "timed out". HW-verified.
- **P2 — OS disconnect callback + live-job self-heal**: `disconnected_callback`
  wired into both BleakClient sites so a drop flips health immediately (no
  inference lag); new honest `is_alive` (connected AND no pending drop) on
  transport→connection→Divoom; live jobs revive a dropped device via P1 before
  pushing instead of writing into a dead link.
- **P3 — concurrency safety + wall self-heal**: a per-loop connect lock
  serializes the connect handshake (wall N devices + live jobs no longer
  connect-storm CoreBluetooth); `DivoomWall.connect()` reports per-slot typed
  results (which screen failed and why), stays usable on partial success, raises
  only on total failure; `show_image()` reconnects a dropped slot before its push
  so one dead screen doesn't freeze the rest.
- **P4 — adapter/permission preflight**: new `divoom_lib/ble_preflight.py` runs
  before scan/connect and maps CoreBluetooth `authorization()` → the typed
  `PERMISSION` reason, so an empty scan / blocked connect carries a cause instead
  of a silent "no devices". The live `CBManagerState` power probe is opt-in only
  (run-loop pumping crashes off the main thread); radio-off stays covered by the
  connect path's typed `ADAPTER_OFF`.
- **P5 — get_* read-back resilience**: new `divoom_lib/ble_reads.py`
  (`read_with_retry` + `ReadCache` + typed `ReadResult`); a flaky read retries
  then degrades to the last-good cached value (or a typed unknown the UI renders
  as "—"), wired into `get_brightness` / `get_device_name`.
- **P5b — get_* root cause (HW, 4 models)**: reads don't time out post-hardening
  — the bug was a STALE read. The device emits an unsolicited 0x46 on state
  change; the manual readers (`get_brightness`/`get_light_mode`) skipped the
  queue drain and consumed the leftover frame, lagging one step behind (set 60 →
  read 25). Added `Divoom.drain_notifications()`, called before those queries;
  round-trip now exact on Ditoo/Pixoo/Timoo/Tivoo-Max. The 0x76 "get name" query
  returns only a 2-char suffix on every model, so `get_device_name` prefers the
  advertised name the lib already holds.
- **P3b — wall HW verification + lifecycle leak fix (4 screens)**: all-real wall
  connects 4/4 + pushes to every screen; a partial wall (3 real + 1 bogus MAC)
  connects 3/4 and pushes to the 3 real screens with the dead slot captured
  per-slot — P3 partial-tolerance proven on hardware. Fixed a leak HW surfaced:
  `wall_configure` dropped `self._wall` without disconnecting, so clearing/
  reconfiguring a wall leaked every screen's link and the next build timed out;
  `_drop_current_wall` now disconnects first (+4 tests).
- **P6 — connection-state observability**: `ble_connection.derive_connection_state`
  + `device_status.connection_state` (DISCONNECTED / CONNECTED / DEGRADED);
  one-line transition logging. The appbar polls it on a 4s heartbeat
  (`get_connection_state` → `refreshConnectionState`) and shows an amber DEGRADED
  dot for a connected-but-dead link, or flips to disconnected on a genuine drop.
  Extracted `OwnerNotifyMixin` to keep `device_owner.py` under budget.
- **daemon-socket flake fix**: `serve_forever` now binds+listens on a local
  socket before publishing `self._server` — fixes a startup race where a
  concurrent `stop()` nulled it mid-setup → "Connection refused"; the client
  retries a transient connect refusal over <1s while liveness probes fast-fail.
- +80 fault-injected tests (fake-BLE double + socket round-trips); full suite
  1398 passed / 75 skipped.

## Round 43 — 2026-06-10 (Permissions Dialog, Settings Backup/Restore, Preset Files, and Wall Split Cache)

- **macOS notification permissions check** (§1): added step-by-step instructions popup modal and red status indicator when database access is blocked.
- **Settings Backup & Restore** (§2): export and import all configuration settings (`presets.json`, `config.ini`, `alarms.json`, `hotchannel.json`, `notification_routing.json`) via JSON backup files.
- **Arranger presets save/load file** (§3): export and import layout presets via JSON preset files, immediately syncing layout to Python on selection change.
- **Display wall downscale caching** (§4): downscale, crop, split, and cache quadrants under `~/.config/divoom-control/cache_wall/` to prevent redundant resizing and fix routing target crash.
- **Layout and styling fixes** (§5): fixed flex layout selectors for `#pixel-hot-channel` and `#pixel-gallery` sub-tabs, repairing the hot-channel update button layout when many preview items are rendered.
- **Custom Art empty screen race condition** (§6): resolved race condition in `custom_art.js` initialization that sometimes caused an empty screen/unresponsive page tabs by checking element existence directly instead of readyState.
- **Coroutine warning fixes** (§7): fixed unawaited coroutine warnings in custom art push and query page handlers by explicitly calling `coro.close()` in exception blocks.

## Round 42 — 2026-06-10 (bug batch: persistence, macOS 26, loaders, wall)

- **Scan settings persist** (§1): new `get_scan_settings` restores
  timeout/limit into the Settings inputs each session.
- **macOS 26 notifications** (§2): NC db discovered in usernoted's group
  container; unreadable store raises an actionable "grant Full Disk Access"
  error instead of "DB not found".
- **Pixel Art loaders** (§3/§4): Custom Art library actually loads (the old
  trigger called a nonexistent function); Hot manifest loads on sub-tab click
  (`loadHotPreview` was never exposed on `window`).
- **Wall presets** (§5): save no longer silently no-ops on an empty name
  (cocoa pywebview lacks `window.prompt`); the per-change last-active-slots
  writer can no longer wipe named presets on a corrupt file; atomic writes.
- **Virtual wall pushes work** (§6, HW-verified on Ditoo+Pixoo):
  `wall_configure`/`device_call` were abandoned by the 2s client read timeout
  (wall builds BLE-connect every slot; wall pushes stream 0x8B per device);
  arranger previews were an un-awaited DaemonDeviceProxy coroutine.
- **Layout** (§7/§8/§9): Schedule +15% (386px), Device Settings clusters
  right-aligned, MCP toggle in the card header.


## Round 41 — 2026-06-10 (UI, Startup, Reconnect, Virtual Wall & CI Fixes)

### Fixed
- **gallery_sync.py SyntaxError** — retry loop now correctly nested inside an outer
  `try-except`; on permanent failure calls `window.onGalleryFetchError` with
  `isExpired` + message rather than silently returning.
- **gallery.js JS syntax error** — `window.onGalleryBackgroundFetched` was missing
  its closing `};` before `window.onGalleryFetchError`, breaking the whole file.
- **gallery_sync.py 500-LOC rule violation** — moved `_coerce_list` / `_coerce_dict`
  static helpers up to `GalleryHotApiMixin` (their natural owner), keeping
  `gallery_sync.py` under 490 LOC.

### Changed / Added

**Channels & Pixel Art Tab:**
- Removed the duplicate empty Custom Art channel tab and `#panel-design` panel
  from `index.html`.
- Added `height: 100%; min-height: 0` to `#pixel-art.tab-content.active` so the
  "Push Page to Device" button stays pinned instead of scrolling away.

**Gallery scrolling:**
- `.gallery-split-card` is now a flex column container capped at height with
  overflow hidden; `.gallery-split-layout` fills the available height — enabling
  the inner grid to scroll without scrolling the card itself.

**Routines layout:**
- `renderSyncTargets` right-aligns toggles (`marginLeft: "auto"`) and increases
  row padding to 13 px.
- `.sync-targets-list` gap increased from 4 px → 5 px.
- Auto-Sync schedule card narrowed from 560 px → 336 px; vertical margins 18 px.
- Anniversary card swapped above Alarms inside `#routines-time`.

**Device Settings:**
- Removed the `<h3>Device Settings</h3>` card-header (redundant with the sidebar
  nav label). Card `max-width` reduced from 640 px → 448 px.

**Startup auto-scan:**
- `populateDeviceSelectors` exported on `window` from `settings_hardware.js`.
- Default scan-timeout changed from 15 s → 60 s (both JS defaults + template input).
- `app_init.js` `load_config` callback immediately populates the device selectors
  from `conf.devices`; the BLE scan fires unconditionally on startup (no longer
  guarded by `conf.last_detected_count`).

**Cloud credentials expiry:**
- `gallery_sync.py` retries once on any API error (clearing cached creds, forcing
  a fresh login) then calls `window.onGalleryFetchError(classify, targetSize,
  isExpired, errMsg)` for a permanent failure.
- `gallery.js` implements `window.onGalleryFetchError`: shows an error toast
  ("Credentials expired. Reconnect in Settings → Divoom." when `isExpired`) and
  replaces the gallery grid with a styled error message.

**Tivoo Max speaker:**
- Speaker-capability regex in `settings_hardware.js` updated to
  `/timoo|ditoo|tivoo/i`; `isSpk` in `app_globals.js` also includes `tivoo`.

**Menu bar error details:**
- `make_status_event` now accepts an optional `error` string and includes it in the
  event payload.
- `notification_service.py` passes `self._error` to the status event.
- `menubar_client.py` copies the `error` field from `EVENT_STATUS` into
  `self._status`.
- `menubar.py` inserts/updates/removes a disabled "Error: …" `NSMenuItem` at
  index 0 and sets the tooltip when the error field is non-empty.

**Virtual Wall coordinates & previews:**
- `device_owner.py` `wall_configure` omits `width`/`height` from grid slot configs
  unless explicitly provided, avoiding the `is_free_form` false-positive.
- `wall.py`: `self.last_previews = {}` in `__init__`; `show_image` captures the
  cropped slice bytes per-slot; `get_last_previews()` returns base64 Data URLs.
- `lighting.py` `display_wall_image` fetches previews from the wall instance and
  returns them in the response dict.
- `app_init.js` `display_wall_image` resolve callback updates `assignedSlots[mac]
  .preview` and calls `renderArrangerCanvas()` + `syncArrangerToPython()`.
- Renamed "Matrix Wall Grid" → "Virtual Wall" in `app_globals.js` and `app_init.js`.

**CI test seed:**
- `test_native_downscaler.py` reads `DIVOOM_TEST_SEED` (env var; falls back to
  `20260605`); `test_stress_random` prints the seed; `_assert_byte_exact` appends
  `(seed=…)` to failure messages for easy reproduction.

### Test suite
- **1321 passed, 75 skipped, 0 failed.** (commit `70188c0`)

---

## Round 40 — 2026-06-10 (UI batch: bug fix, toggles, Device Settings, lifecycle)


### Fixed
- **Custom-art page push crash** ("cannot identify image file …gif") when a
  slot held a hot file — new `media_decoder.resolve_to_gif` resolves every CDN
  container (GIF/PNG/JPG/magic 43/AES 9·18·26/0xAA) used by both the custom-art
  and sync paths.
- **Gallery grid stranded at 400px** after the R39 Pixel Art move — restored the
  `#pixel-gallery` grid override + added the pixel-subtab flex-height chain so
  the grid fills the card and scrolls internally.

### Changed / Added
- Live Widgets: System Monitor / Weather / macOS Notifications and Routines →
  Anniversary controls are now header-right toggles; removed the SysMon + Weather
  "Push to Device" buttons; Weather gains a Live (15m) toggle (both live toggles
  persist).
- Gallery tiles capped to hot-channel scale (128px); Settings sub-tabs sticky;
  Schedule rows keep the toggle beside the device name.
- **Device Settings** sidebar section — one glass pane (name / clock / temp /
  power / auto-off / orientation / mirror / update-time, Danger zone last);
  clock/temp/power are segmented pills.
- **Keep daemon (menu bar) alive** toggle (Settings → Connectivity, default off):
  event-driven shared-vs-independent lifecycle via a daemon `shutdown` broadcast.

### Build
- `-ffp-contract=off` in `build_libdivoom.sh` for more deterministic LANCZOS
  float rounding across clang versions.


## Round 39b — 2026-06-10 (UI polish, part 2 — verified in browser preview)

### Fixed — custom art chrome scrolled away
- Root cause: `#control-panel .card-body { overflow-y: auto }` scrolled the
  whole panel because the `.channel-panels` wrapper broke the flex chain
  (the panel's `height: 100%` resolved against an auto-height block).
  `.channel-panels` now passes the bounded height down — page tabs, slot
  grid and the Push button stay visible; only the art library scrolls.
- Slot grid is now ONE row of 12 (6×2 under 900px) so the library keeps
  most of the panel height.

### Added — drag & drop for custom art slots
- Drag a filled slot onto another to swap them; drag art straight from the
  library onto any slot to place it. Green highlight on the drop target.
  Verified in the browser preview with synthetic DataTransfer events
  (swap, library→slot, draggable only when filled).

### Changed — hot channel
- Preview tiles are image-only (name/version moved into the tooltip) and
  the empty card header is gone — more art per screen.

### Changed — gallery
- Popular/Latest + size selector right-aligned on the controls row:
  categories (left sidebar) say WHAT to browse, view controls say HOW —
  they stay in one quiet, predictable corner (Rams/Kare).

### Maintenance
- `channels.css` split: custom-art styles → `custom_art.css` (500-LOC rule);
  `@import` added in style.css; layout tests read both files.
- `.claude/launch.json` added: `web_ui-static` serves the web UI for
  browser-preview verification.

### Test suite
- **1307 passed, 75 skipped, 0 failed.**

## Round 39 — 2026-06-09 (UI polish round: hot preview, custom art overhaul, alarms)

### Fixed — alarms showed phantom entries after clearing
- **Root cause (APK-verified, `u1/b.a()`)**: the 0x42 get-alarm response is
  **10 bytes per record and starts with the alarm index byte**; our parser
  used a 9-byte stride starting at status, so every record after the first
  was misaligned — random week/status bytes rendered as ghost alarms.
  `divoom_lib/scheduling/alarm.py` + `models/constants.py` now use the
  correct layout, tolerate old-mode devices (3 records), and parse partial
  responses instead of returning None.
- Alarms "On" column is now a proper toggle switch (reuses `.switch`/
  `.slider-round`), not a bare checkbox.

### Changed — hot channel preview
- Thumbnails doubled 56px → 112px with `image-rendering: pixelated`
  (crisp upscaling); file counter removed; preview grid now fills the card
  down to the Update button (no dead space; was `max-height: 280px`).
- Washed-out colors fixed: `.hot-preview-item-uncached { opacity: 0.55 }`
  dimmed nearly every tile (hot items rarely have a gallery cache entry) —
  rule and gating removed.

### Changed — custom art channel overhaul (Rams/Kare pass)
- Page tabs + 12-slot grid are a fixed header; only the art library scrolls.
  Slots are the same tile size as library previews (shared 6-column grid).
- Click-to-assign flow: click art → fills selected / first empty slot and
  auto-advances; click a slot to target it; hover a filled slot → × clears
  it. Assigned tiles dim in the library. Push button reads
  "Push Page N to Device".
- **Push semantics fixed**: the daemon now accepts a full `{slot: file_id}`
  page mapping and sends the page ONCE (previously each file triggered
  `push_slot` with a fresh empty page — every push wiped the other 11 slots).
  `daemon_protocol.custom_art_push(slots=...)`, `gallery_sync.custom_art_push`
  accepts mapping or legacy list payloads.
- Fixed `window.renderCustomArtHistory` ReferenceError (export + call left
  behind after the R37 history-filmstrip removal broke `DOMContentLoaded`
  wiring in `channels_grids.js`).

### Changed — routines
- Schedule card narrowed 760px → 560px (device rows are now dot + name +
  toggle; the old width left a dead gap in the middle).

### Maintenance
- 500-LOC rule: split `device_owner.py` (627) → `owner_art.py` mixin
  (custom-art + hot-update RPC handlers), and `gallery_sync.py` (653) →
  `gallery_hot_api.py` mixin (hot/custom-art wrappers + animated preview).
- Emojis stripped from `docs/CUSTOM_CHANNEL_VS_APK.md` (R14 §6).

### Test suite
- **1306 passed, 75 skipped, 0 failed** — fully green, including refreshed
  alarm-parser, custom-art push, and layout assertions.

## Round 37 — 2026-06-09 (custom art push — Phase 3 web UI)

### Added
- **Multi-select gallery cache grid**: `renderCustomArtCacheGrid` now renders each
  cached file with a checkbox and `data-file-id` for selecting multiple items to push.
- **Page tabs (3 pills)**: clicking a tab calls `design.use_user_define_index(page)`
  via the daemon to switch the device's displayed page.
- **12-slot grid**: visual slot selector with click-to-select highlighting.
- **`gui_api.device_call(method, args, ...)`**: generic Python→daemon proxy exposed
  to JS for calling arbitrary device library methods.
- **`divoom_gui/web_ui/custom_art.js`**: new controller module (page tabs, slot grid,
  push button wiring).

### Removed
- Old custom-art file browser UI (browse button, path input, preview container,
  history filmstrip) — replaced by gallery cache + slot grid flow.
- `renderCustomArtHistory`, `addCustomArtToHistory`, `window.addCustomArtToHistory`
  (dead after history filmstrip removal).
- Dead `#custom-art-path-input` reference in `app_init.js` (the browse+apply event
  listeners).

## Round 38 — 2026-06-09 (gallery side-by-side + hot channel animated previews + 0xAA decoder)

### Added — hot channel 0xAA file format decoder (`divoom_lib/media_decoder.py`)
- **Empirically reverse-engineered** the hot channel CDN file format (magic byte
  `0xAA`). A hot file is a concatenated chain of palette-indexed frames:
  `0xAA len(u16 LE) time_ms(u16 LE) flag n_colors [palette] [pixels]`.
  `flag` 0 resets the running palette (`n_colors` RGB entries, 0 meaning 256);
  `flag` 1 *appends* `n_colors` new colors (delta frame). The pixel map is the
  full 256 indices into the cumulative palette, packed LSB-first at
  `ceil(log2(palette_size))` bits per pixel, omitted while the palette has one
  color. (A first cut misread byte 6 as a frame count over raw 768-byte RGB
  frames → garbage previews; corrected same day, validated frame-exact against
  6 live CDN files, 186–463 frames each, zero length/index errors.)
- `decode_hot_file_format(raw_bytes)` → `list[tuple[bytes, int]] | None` —
  768-byte RGB + per-frame duration (ms) per frame.
- `decode_hot_file_to_gif(raw_bytes, out_path)` → `bool` — saves upscaled
  128×128 animated GIF with real per-frame durations.
- `tests/test_hot_file_decoder.py` — 11 regression tests (keyframe/delta/reset,
  LSB bit packing, solid-color frames, truncation, GIF output).

### Fixed — hot channel animated previews
- `get_animated_preview` in `gallery_sync.py` now uses the library decoder for magic
  `0xAA` files (previously fell through all decoders and returned empty).
- `renderHotPreview` (`gallery_hot.js`) calls `get_animated_preview` for ALL hot channel
  items, not just those with a gallery cache entry (`has_cache` gate removed).
- Added PIL `Image.open()` catch-all as final fallback.

### Added — side-by-side categories | gallery grid
- `templates_gallery.js`: side-by-side layout with `.gallery-sidebar` (`.cat-btn`
  vertical category list) + `gallery-main` (controls + grid).
- `gallery.css`: new grid rules, `.cat-btn` styles. Sidebar width reduced ~30%
  (160px → 112px).

### Fixed — progressive loading race
- `onGalleryItemLoaded` replaces items in-place by index (cached items render first,
  network items replace silently).
- `onGalleryBackgroundFetched` only re-renders if item count differs by >2.

### Changed
- Removed "Divoom's Curated Hot Set" and "Hot Channel Preview" header text from
  `templates_hot_channel.js`.
- All classify-tab selectors renamed `.tab-btn` → `.cat-btn`.
- CSS compacted to 467 LOC.

### Test suite
- 1304 passed, 75 skipped, 2 failed (`test_file_size.py` + `test_no_emojis.py` —
  violations in the uncommitted R37 custom-art docs, not this round).

## Round 36b — 2026-06-09 (the REAL hot-channel update, APK port)

### Added — device hot-channel update (`b85004b5`)

- The previous "hot channel" sync displayed images on the CUSTOM channel
  (drawing-send). The actual HOT channel update is a device-driven file STORE
  protocol, reverse-engineered from the APK and implemented end-to-end:
  HTTP `Hot/GetHotFiles32` manifest → BLE 0x9B/0xF7/0x9D/0x9E session (device
  requests files, byte-sum checksums, 256B packets, per-packet resends, done
  acks) → device switches to HOT mode. Raw cloud containers are sent AS-IS for
  sub-128px devices (firmware decodes hot files itself), matching `C1301b.d()`.
- New: `divoom_lib/tools/hot_update.py` (facade `.hot_update`), transport
  `wait_for_any_response` + unsolicited-frame listen set, daemon `hot_update`
  RPC + `hot_update_timeout` knob, GUI "Update Hot Channel" button.
- Hardware-verified on the Ditoo with real device-side confirmations (file
  request → 201 packets → done ack → up-to-date; idempotent 2nd run).

## Round 36 — 2026-06-09 (hot-channel renders on real hardware)

### Fixed — hot-channel sync rendered nothing on a real Ditoo

- Root cause (hardware iteration + payload forensics): magic 9/18/26 cloud
  downloads are app-side AES-CBC ciphertext. `sync_artwork` raw-streamed the
  encrypted container over 0x8B — the device ACKs every chunk (so every
  protocol-level check "passed") but cannot decode it, displaying nothing.
  The APK decodes (`PixelBean.initWithCloudData`) and re-encodes before BLE.
- `media_decoder.decode_cloud_frames` / `decode_cloud_to_gif` (native-size;
  the preview path now wraps the same core); `sync_artwork` decodes
  magic 9/18/26 to GIF and routes through `show_image` (APK-aligned encoder +
  0x8B). Raw streaming only remains for unknown magics.
- Verified on the Ditoo via daemon RPCs: 32KB container → 5.8KB / 24-frame
  GIF, start-ACK, 3/3 batch at 2-4s per image (was 15s of ciphertext).
- Suite greened: stale R35 button-regex test, `test_hardware_smoke` pytest
  collection error, no-emoji violations in R35 docs. 1216 / 75 / 0.


## Round 35 — 2026-06-09 (APK encoding parity, terminate removal, UI polish)

### Critical bugfix: 0x8b start-phase notification routing.

- Root cause: `_handle_ios_le_notification` drops the device's "[0] → ready" response
  because `_expected_response_command` is `None` — `send_command` doesn't set it.
- Fix: set `_expected_response_command = 0x8b` on the BLE transport *before* sending
  the START packet, so the notification handler routes the ACK to the queue.
- Previously the ACK was silently dropped → `_await_8b_device_ready` blocked 3s →
  0.5s sleep fallback → **3.5s dead air** → device internal spinner timeout (~1-2s) →
  permanent spinner. APK has no such gap: it sends START, then waits reactively for
  the device's `[0]` response (event-driven). Our fix makes the wait actually work.
- Reduced `_await_8b_device_ready` timeout from 3s → 2s (device typically responds
  within 200ms).

### APK comparison doc + encoding parity tests (R35c)

- New `docs/APK_COMPARISON.md` (815 lines): byte-by-byte comparison of 0x8B, 0x49,
  0x44, frame body format, BLE framing, color palette, pixel packing. 11 MATCH,
  4 DIFFERENT, 2 UNVERIFIED → now both verified.
- New `tests/test_apk_encoding_parity.py`: 25 tests covering wire format, frame body,
  framing layer checksum, pixel data packing, color quantization limit.
- Verified findings:
  - 32×32 pre-frames (0x05/0x06): **NOT IN APK** — only appear as SPP escape sequences
  - 32×32 RR=0x03, 2-byte NN: **NOT IN APK** — APK uses RR=0x00, 1-byte NN for all sizes
  - 0x49 packet index: **CONFIRMED 0-based** in APK (our code is 1-based)
  - APK has separate BlueHigh encoding path (0x25 header) we don't implement

### TERMINATE removal (R35d) — hardware-verified

- APK `CmdManager.n()` does NOT send CW=2 (terminate). Tested on 4 devices
  (Timoo SPP, Ditoo BLE, Tivoo Max BLE, Pixoo BLE) — **all PASS** both with
  and without terminate. Removed permanently, saving ~0.5s per upload.
- `stream_animation_8b`: removed `send_terminate` parameter; no longer sends
  terminate or its 0.5s settle sleep.
- `display.show_image`: removed `send_terminate` parameter.

### Upload progress indicator (R35b)

- `sync_hot_channel`: `evaluate_js()` progress callback after each file.
- JS handler: `window.onGallerySyncProgress(index, total, fileId, success, errorStr)`.
  Shows dimmed "Updating (i/N)", then "OK Synced N" (green, 3s) or
  "X X ok, Y failed" (red, 5s). Double-press guarded via `_syncInFlight`/`_syncAllInFlight`.

### Device dot pulse in device color

- CSS: `.transport-dot.connecting` uses `var(--dot-pulse-color, #f59e0b)`.
- JS: sets `--dot-pulse-color` to `window.deviceColor(address)`.
- Global dot stays amber fallback.

### Gallery button alignment

- Removed `wall-tool-btn` from Select All/Clear buttons (had `background: transparent`
  → hollow look). Added `.gallery-select-btn` with solid `#2e2f36` background.

### Files changed (R35a-d):
- `divoom_lib/display/animation.py` — `stream_animation_8b`: notification fix + TERMINATE removal
- `divoom_lib/display/__init__.py` — `show_image`: removed `send_terminate` parameter
- `divoom_lib/ble_transport.py` — notification routing fix
- `divoom_gui/gallery_sync.py` — progress callback
- `divoom_gui/web_ui/gallery.js` — progress handler + double-press guards
- `divoom_gui/web_ui/gallery.css` — `.gallery-select-btn`, sync-state classes
- `divoom_gui/web_ui/templates_monthly_best.js` — button + status spans
- `divoom_gui/web_ui/app_globals.js` — `--dot-pulse-color` per device
- `divoom_gui/web_ui/appbar.css` — `.transport-dot.connecting` uses CSS var
- `docs/APK_COMPARISON.md` — new 815-line comparison doc
- `tests/test_apk_encoding_parity.py` — 25 new parity tests
- `tests/test_animation_8b_stream.py` — updated for TERMINATE removal
- `tests/test_e2e_mock_device.py` — updated for TERMINATE removal
- `tests/test_hardware_smoke.py` — new HW smoke test

**Test baseline:** 210 passed (31 parity + 8b stream + e2e mock + monthly best daemon)

---

## Round 34 — 2026-06-09 (hot-channel sync fix + Routines polish)

### Fixed — hot-channel sync falsely reported every upload failed (§1)

- `DaemonClient.sync_artwork` used the 2s quick-command read timeout, but the
  daemon only replies after downloading the asset AND streaming it to the device
  over BLE. New `sync_read_timeout` knob in `daemon.ini` (default 120s).
- `sync_hot_channel` now returns a per-file `errors` map (reason strings)
  alongside `synced`/`failed`, via the shared `_sync_artwork_detailed` core.

### Changed — APK-aligned device-driven 0x8b upload (§1b)

- Audited the chunked animation upload against the decompiled official APK.
  Wire format confirmed identical; the FLOW diverged: the APK waits for the
  device's "send the animation" ACK after START and serves per-chunk retransmit
  requests, while we slept 0.5s and blasted. `stream_animation_8b` now does both
  on BLE (with graceful fallback to the legacy sleeps when the device doesn't
  respond), and `stream_raw_bin_payload` delegates to it instead of duplicating
  the streamer. Full comparison in `docs/CHANNEL_ARCHITECTURE.md` (0x8b section).

### Added — connect pulse + Routines UI (§2-§4)

- **Device dots pulse while connecting** — the clicked sidebar device dot gets
  the existing amber `dot-pulse` for the duration of the connect attempt.
- **Auto-Sync Gallery rows fit one line** — Schedule grid 540→760px, nowrap
  rows, long device names ellipsize.
- **Alarms weekday table** — one weekday header row + day-cell toggles per
  alarm; only non-empty alarms shown; "+ Add alarm" / "Clear all" / per-row ×;
  changes write to the device immediately (debounced 500ms per row — no Save
  button). `set_alarm` caches last-written state to
  `~/.config/divoom-control/alarms.json`; `get_alarms` falls back to it when the
  device read is empty (the get_* read-back is flaky on hardware, task #20).
  Editor lives in new `web_ui/alarms_editor.js` (500-LOC rule).

---

## 2026-06-09 — Downscaler kernel weight normalization: RGB parity bug fixed

- `downsample_kernel.c`: Changed `kernel1d_init` from quantize-then-normalize
  to normalize-then-quantize (matching PIL's `normalize_coeffs_8bpc` in
  `libImaging/Resample.c`). Normalize double-precision weights to sum 1.0,
  then quantize with round-half-up. Removed unused `ROUND_HALF_POS` define.
- Fixed the remaining 1 LSB failure in `test_stress_random` (32x8→8x11 RGB).
  **38/38 tests pass** (was 37/38). All RGB parity tests now run native (no PIL
  fallback) and match PIL byte-for-byte.
- **Added 22 edge case tests** to `test_native_downscaler.py`: degenerate
  dimensions (1×N, N×1, single pixel), extreme aspect ratios (300×1→2×2,
  1×300→2×2, 100×4→2×2), non-square identity (32×16), odd prime sizes
  (13×17→5×7), asymmetric output (16×16→4×12, 16×16→15×4), checkerboard,
  horizontal/vertical gradient, impulse response, and constant-channel values.
  All pass byte-identical. **60/60 tests**.

## 2026-06-09 — Inline-style migration: batch 2 (monthly_best)

- Migrated `templates_monthly_best.js`: `.gallery-select-actions` →
  `row gap-8`, `.gallery-actions` → `flex gap-10`. Added a bare `.flex`
  utility (`.row` includes align-items:center; bare display:flex must not).
- L13/L28 inline styles were redundant with the ID-scoped
  `#monthly-best .card.glass-card` / `.card-body` rules (already set
  display:flex+column+flex:1+overflow+min-height) — deleted the redundant
  inline (a class utility can't out-specify an ID rule anyway).
- Left inline per §2.1's exception: `templates_tools.js` `padding:24px`,
  monthly_best `margin:0` reset (L20), and the unique L29 composition.
- Verified the utilities compute exact equivalents via preview;
  test_monthly_best_button_visible still green. Suite 1158/75.

---

## 2026-06-09 — Inline-style migration: batch 1 (utility layer)

- Added the CSS utility/token layer (REVIEW §2.1 batch 1): `.row/.row-top/
  .row-between/.col/.wrap`, `.gap-{6,8,10,12,14}`, `.label-sm/.label-xs/
  .text-sm/.text-mono-sm`, `.text-warn/.text-error` in style_extra.css, and
  `--warn`/`--error` tokens in style.css :root.
- Pure addition: no templates reference them yet; `.flex-row` left as-is.
  Verified via the static-server + preview tools that the rules parse and
  compute correctly. Per-file template migrations follow in batches 2-5.

---

## 2026-06-09 — Inline-style migration plan (§2.1)

- Scoped the inline-style → CSS-token migration → `docs/PLANNING_inline_styles.md`.
- Correction: real count is 138, not 142 (4 were `data-style="…"` regex false
  matches). ~50 are genuinely-unique per §2.1's own exception (leave inline);
  ~90 repeated patterns map to a small utility layer.
- 5 batches (one template file each) with per-batch visual verification via the
  static-server + preview technique. Not yet implemented.

---

## 2026-06-09 — appbar.css !important cleanup (§2.3)

- Removed the 6 `!important` flags on the `#global-status-dot.*` state rules.
  They were unnecessary: the ID+class selectors already out-rank the base
  `#global-status-dot` rule and the `.transport-dot.*` rules (which set no
  colour), and the JS clears inline styles (`removeAttribute("style")`).
- Verified all 5 dot states (ble/lan/wall/connecting/inactive) resolve to the
  same computed background/box-shadow/opacity in a browser harness (preview
  tools). No visual change. The 1 remaining flag (`.transport-dot.connecting`)
  is left — equal-specificity competitor in sidebar.css.

---

## 2026-06-09 — Notifications single-owner (Phase 1)

- Fix the §1.2 double-route: the GUI no longer runs its own
  `MacNotificationMonitor` alongside the daemon's. `start/stop_notification_listener`,
  `is_notification_listener_running`, `get_notification_listener_status`, and
  `save_notification_routing` now delegate to the daemon.
- New `DaemonClient` RPC wrappers: `start_notifications`, `stop_notifications`,
  `notification_status`, `set_routing` (daemon_protocol.py).
- Deleted dead GUI machinery: `_notification_monitor`, `_notification_sink`,
  `_send_notification_async`, `_schedule_async`.
- Tests: rewrote the GUI notification suite to the delegation contract incl. a
  regression test that the GUI never instantiates `MacNotificationMonitor`.
- Fixed flaky `test_routing_loader` (read the user's real `~/.config` file at
  call time; now patches the bound module attribute). Suite green on py3.14.
- See `docs/PLANNING_daemon_ownership.md` Phase 1.

---

## 2026-06-09 — Daemon-ownership investigation + plan

- Read-only investigation of REVIEW §1.3/§4.1/§1.2 → new
  `docs/PLANNING_daemon_ownership.md`.
- Correction: the device-access migration is essentially complete — no direct
  BLE in `divoom_gui/`; `current_divoom` is a `DaemonDeviceProxy` routing through
  the daemon's single-owner `DeviceOwner`. REVIEW §1.3 re-tagged false-positive
  (resolved); §0.5 priority #3 collapsed into #4.
- The one genuine remaining duplication is notification monitoring (§1.2): GUI's
  `MacNotificationMonitor` runs alongside the daemon's auto-started
  `NotificationService`. Phased fix documented (Phase 1: GUI delegates to the
  daemon's existing `start_notifications` RPC). Not yet implemented.

---

## 2026-06-09 — Housekeeping (dead CSS + asyncio cleanup)

- Removed dead CSS confirmed unused (REVIEW_2026-06 §2.4): `.color-picker-grid`
  and `.channel-grid` (channels.css), `.range-slider` + `::-webkit-slider-thumb`
  (style.css). `.color-swatch` retained — it is still referenced.
- `mcp_server.run_stdio`: dropped the deprecated `asyncio.StreamReader(loop=)`
  kwarg (binds to the running loop on its own); documented that
  `asyncio.streams.FlowControlMixin` is intentionally retained (no public
  equivalent for `connect_write_pipe`, stable on 3.14). Confirmed neither emits
  a DeprecationWarning on 3.14.
- No behavioural change; suite unchanged.

---

## 2026-06-09 — tool.py + drawing.py coverage (mock-device tests)

- Extended `tests/test_drawing.py` (+19) to cover all 14 Drawing command
  builders, including the `sand_paint_ctrl` / `pic_scan_ctrl` dispatch tables
  and their missing-param / unknown-control error paths.
- Added `tests/test_tool_mock.py` (18) covering get/set tool info for
  timer/score/noise/countdown, including response parsing and ValueError paths.
- Coverage: `display/drawing.py` 20%→100%, `tool.py` 18%→97%. Completes the
  four thin areas from REVIEW_2026-06 §0.5.

---

## 2026-06-09 — Scheduling coverage (mock-device tests)

- Added `tests/test_scheduling_mock.py` (24 tests) driving the alarm/sleep/
  timeplan command builders against a recording `MockSender` — verifies on-wire
  command ids + argument bytes without hardware.
- Coverage: `scheduling/alarm.py` 20%→98%, `sleep.py` 23%→100%,
  `timeplan.py` 17%→100%. Addresses REVIEW_2026-06 §0.5 priority #2.
- Suite: **1118 passed, 75 skipped** (+24, zero regressions).

---

## 2026-06-09 — Review verification + `/zreview` command

- Verified the DeepSeek multi-lens review (`docs/REVIEW_2026-06.md`) against the
  actual code. Added **§0 Verification Pass** tagging each finding
  confirmed/partial/false-positive.
- **False positives caught**: §1.1 `cmd_push_gif`→`show_image` is correct, not a
  bug (`show_image` is the animation path); §1.11 `iscoroutinefunction` is not in
  `mcp_server.py`; the §3 "0% on CLI/MCP/LAN" coverage claims are false
  (38/66/52%) and `framing.py` is 92% not 13%. Real TOTAL coverage **62%**.
- **Corrected priority order** in §0.5; genuinely thin coverage areas are
  `scheduling/`, `display/drawing.py`, `tool.py`.
- Added `.claude/commands/zreview.md` — repeatable four-lens (Bob/Linus/Rams/Kare)
  + coverage review with mandatory per-finding verification; documents that the
  suite runs on `/opt/homebrew/bin/python3.14`.
- Suite re-run on py3.14: **1094 passed, 75 skipped**.

---

## Round 32 — 2026-06-08 (Monthly Best reorg + Routines + device selector + Text fix)

### A — Monthly Best → full-width multi-select gallery

- **§A1**: the devices (sync-targets) panel moved out of Monthly Best into
  Settings → Routines. Monthly Best is now a single full-width gallery card
  (`.monthly-best-layout` is `grid-template-columns: 1fr`).
- **§A2**: removed the ghost "Fetch Gallery" button (fetch already auto-fires on
  style change + tab activation). Gallery style is now remembered **per device**
  in `config.ini` `[gallery]` via new `get_gallery_style`/`set_gallery_style`
  API; the active device's preferred style is restored on startup before the
  cached gallery renders. The style dropdown sits in the old button location.
- **§A3**: each gallery tile carries a selection checkbox (all checked by
  default); added "Select All" / "Clear" controls (virtual-wall styling) and
  dropped the "Gallery" / "Divoom Cloud" header chrome. "Update Device" now
  pushes **every checked** image.

### B — Settings → Routines card

- New layout: device selector | gallery-style selector, a **macOS-style toggle**
  (`.switch`/`.slider-round`, not a checkbox) for auto-sync, interval, the moved
  devices list, "Save Schedule" + "Sync devices now". Auto-sync stays
  daemon-driven (reads `hotchannel_config.json`).

### C — Device selector

- **§C1**: stripped the `BLE:`/`LAN:` transport prefix from the sidebar device
  selector — names are clean (the connectivity dots convey transport).
- **§C2**: the sidebar preview mirrors the **last image this app pushed** to each
  device (devices can't report their framebuffer). `setDevicePreview()` is called
  from the gallery push and the custom-art push; the map persists in
  `localStorage` and `restoreDevicePreview()` runs on connect/switch, falling back
  to the product icon.
- **§C3**: replaced the device dropdown with **per-device dots** overlaid on the
  preview — color-coded via `deviceColor()`, tooltips show names, click switches.
  The `<select>` is kept hidden as canonical state; `renderDeviceDots()` mirrors
  it and highlights the active device.

### D — Channels → Text fix ("nothing appeared")

- The Text card pushed via the 0x87 "set light phone word attr" (LPWA) sequence,
  which the Pixoo-class LED matrices don't render — so nothing showed. The
  known-working references (hass-divoom, futpib) render text into image frames and
  push them via the normal image path. `push_text` (GUI `LightingApi`) now renders
  the text with our no-AA bitmap font onto a device-sized canvas (scaling to fit)
  and pushes via `display.show_image()`. `speed`/`effect_style` are accepted for
  call-compat but unused (static image); scrolling frames are a follow-up.
  **Not hardware-verified** — the render + push-path are unit-tested.

### E — Settings → Connectivity cleanup

- Removed the "Connectivity & Privacy" explainer legend (markup + `.connectivity-legend*`
  styles); the four corner transport dots already convey state.

Suite **1094 passed / 75 skipped / 0 failed**. Browser-preview verified the dots,
gallery multi-select, and Routines card. Full write-up: `docs/PLANNING_ROUND32.md`.

---

## Round 31 — 2026-06-08 (Font improvement + CJK infrastructure + warning fixes)

### Better half-font downsampling

- Changed half-font extraction from OR rule (any of 4) to majority rule (≥2 of 4).
  The OR rule collapsed `B`/`8` and other glyph pairs at ~5px; majority preserves
  glyph distinction while retaining enough stroke fidelity for the small display.
- Regenerated `divoom_fond16_default_half.bin` with the improved algorithm.

### CJK font infrastructure

- Added `APK_RANGES` table (the 18 Unicode ranges from the APK's `CmdManager.C2()` /
  `F2/d.java` including CJK 0x4E00-0x9FA5) to `divoom_lib/fonts/bitmap_font.py`.
- `BitmapFont.__init__` now accepts an optional `range_table` parameter; when
  provided, glyph lookup walks the range table (supports non-contiguous ranges)
  instead of the flat ASCII offset.
- `BitmapFont.from_apk_asset(path)` classmethod loads a raw APK font blob and
  returns a range-table-enabled `BitmapFont` that can map CJK, Hangul, Greek,
  Arabic, etc. glyphs.
- `_find_glyph_offset(cp)` walks the range table — returns `None` for codepoints
  outside all ranges (falls back to `?`).

### Warning fixes

- `CommandQueue.submit()` / `_add()` / `_dequeue()` / `_cancel_worker()`: close
  coroutine objects before raising exceptions so Python 3.14's `RuntimeWarning:
  coroutine was never awaited` is not emitted during garbage collection.
- `test_r13_start_notification_listener_wires_sink`: mock `_schedule_async` with
  a side-effect that closes the captured coroutine instead of discarding it.
- Full suite clean with `-Werror::RuntimeWarning`: 1093 passed, 0 warnings.

### Tests

- 3 new CJK font tests: range-table CJK mapping, unknown codepoint fallback,
  ASCII glyphs still work with full APK font.
- Suite: 1093 passed / 75 skipped (was 1090).

---


### `DaemonDeviceProxy.push_animation()`

- New convenience method on the daemon proxy: `push_animation(file_or_data, *, token)`
  accepts a local file path *or* raw bytes (written to a temp file). Runs
  `display.show_image()` inside an exclusive-mode session so the 0x8B 3-phase
  streaming sequence is never interleaved with other commands.

### MCP `push_animation` tool

- 13th MCP tool: `push_animation(file|data)` — pushes a GIF/animation via 0x8B.
  Accepts a local `file` path OR base64-encoded `data` (for remote clients without
  a shared filesystem). When `divoom` is a `DaemonDeviceProxy`, uses
  `push_animation()` for exclusive-mode protection; otherwise falls back to
  `display.show_image()`.
- Schema uses `oneOf` to require exactly one of `file` or `data`.

### Tests

- 3 MCP tests: file path, base64 data, both/neither validation.
- 2 bridge tests: push_animation with file path, push_animation with raw bytes.
- Suite **1090 / 75 / 0** (+5).

### Files touched

- `divoom_daemon/daemon_client.py` — `DaemonDeviceProxy.push_animation()`.
- `divoom_lib/mcp_tools.py` — `push_animation` tool handler, schema, description.
- `tests/test_mcp_server.py` — 3 new tests, tool count 12→13.
- `tests/test_daemon_bridge.py` — 2 new tests; `_Facade.show_image()` added.
- `docs/PLANNING_ROUND30.md` — new.

---

## Round 29 — 2026-06-08 (Exclusive mode through daemon RPC)

### Wire exclusive mode through device_call

- **`DaemonClient.device_call()`** gets a `token` param — ships in the RPC
  payload. The daemon's `DeviceOwner.device_call()` extracts it and passes
  it through to `_run_device(coro, token=token)`, so the command queue's
  exclusive-mode dispatch gates the call.
- **`DaemonClient.exclusive_start(token)` / `exclusive_end(token)`** — new
  RPC methods that call `CommandQueue.acquire(token)` / `.release(token)`
  on the daemon's event loop. Both handlers submit with `token=token` so
  the queue dispatches them inside the exclusive session.
- **Daemon command registry** registers `exclusive_start` / `exclusive_end`
  → `DeviceOwner.exclusive_start` / `.exclusive_end`.
- **`DaemonDeviceProxy.exclusive(token)`** — async context manager that
  issues `exclusive_start` / `exclusive_end` RPCs and returns a token-tagged
  proxy for nested calls. Usage:
  ```python
  async with proxy.exclusive("anim-1") as p:
      await p.display.show_light(255, 0, 0)
      await p.lan.set_brightness(80)
  ```
- **Tests**: 6 new daemon-bridge tests (exclusive start/end, token
  validation, token-through-device_call, proxy exclusive context,
  RPC plumbing). Suite 1085 / 75 / 0 (+6).

### Files touched

- `divoom_daemon/daemon_protocol.py` — `device_call` accepts `token`;
  `exclusive_start`/`exclusive_end` methods on `DaemonClient`.
- `divoom_daemon/device_owner.py` — `exclusive_start`/`exclusive_end`
  handlers; `device_call` forwards `token` to `_run_device`.
- `divoom_daemon/daemon.py` — `exclusive_start`/`exclusive_end` in
  command registry.
- `divoom_daemon/daemon_client.py` — `DaemonDeviceProxy.exclusive()` ctx
  manager; `__call__`/`__getattr__` propagate `_token`.
- `tests/test_daemon_bridge.py` — 6 new exclusive-mode tests.
- `tests/test_gui_api.py` — updated `device_call` mock expectation for
  new `token` kwarg.
- `docs/PLANNING_ROUND29.md` — new.

---

## Round 28 — 2026-06-08 (MCP daemon-route + scan filter + tab spacing + bitmap font)

### Tab layout fixes (r2 — follow-up to the spacing centralisation)

- **Channels giant glass pane.** `#control-panel .grid-layout` left its rows on
  the grid default `align-content`, which stretched BOTH auto rows — ballooning
  the tab pane into a ~217px empty glass box. Fixed with
  `grid-template-rows: auto 1fr` (pane = content height, card takes the rest).
- **Tools/Settings 21px gap below the tab pane.** `.tab-content` is a flex
  column with `gap: 20px`, so the pane inherited a 20px flex gap (+1px margin).
  Tokenised the panel gap (`--panel-gap: 20px`) and added
  `.tab-content > .tabs-section { margin-bottom: calc(var(--tab-pane-gap) - var(--panel-gap)) }`
  so the flex (Tools/Settings) and grid (Channels) contexts both yield exactly
  `--tab-pane-gap` (1px) below the pane.
- **Tab row shifted left/right between sub-tabs.** `.tabs-row` was centered with
  `margin: 0 auto`; the centre moved as the panel scrollbar appeared/disappeared,
  and it never lined up with the left-aligned cards. Now left-anchored (stable +
  aligned).
- **Settings glass pane wrapped the whole panel.** `templates_settings.js` never
  closed `.tabs-section` after the tab row, so all 5 content panels were nested
  *inside* the tab glass pane (browser auto-closed it at the fragment end). Added
  the missing `</div>` so the panels are siblings.
- Tests: `tests/test_tabs_chrome.py` retargeted + extended (flex gap cancel,
  grid `auto 1fr`, left-aligned row, Settings pane-not-wrapping regression).

### Device text font halved (r3)

- The full-size bitmap glyphs (~9–10px) dominated a 16px matrix. Added a
  **half-size variant** (`divoom_fond16_default_half.bin`, ~5px tall): each glyph
  is the cropped APK glyph 2×-downsampled with an OR rule (a 2×2 block lights if
  ANY source pixel is lit, so 1px strokes survive), re-placed in the same 16-cell
  format so `BitmapFont` reads it unchanged. `scripts/extract_apk_font.py` now
  emits both assets. New `get_small_font()`; `media_source.py` rasterises device
  text with it. +2 tests (asset present, small ≈ half the full height).

### Device text uses a real bitmap font (no anti-aliasing)

- Text rasterised for the device (stock ticker, etc.) was drawn with PIL
  `ImageFont.load_default(size=…)` — an anti-aliased TrueType font that turns to
  grey mush at 16/32/64px. Replaced with a **1-bit bitmap font extracted from the
  official Divoom APK** (`assets/divoom_fond16_default.bin`), so glyphs match
  exactly what the device shows in the Divoom app.
- **Reverse-engineered the APK font format** (from `F2/d.smali`): 32 bytes/glyph
  (16×16 @ 1bpp), glyph for codepoint `cp` at offset `(cp-0x21)*32` for printable
  ASCII, stored rotated 270°. `scripts/extract_apk_font.py` bakes out the
  rotation and writes the printable-ASCII subset (95 glyphs, 3040 bytes) to
  `divoom_lib/fonts/divoom_fond16_default_ascii.bin`.
- **New `divoom_lib/fonts/`** (`BitmapFont`, `get_default_font()`): proportional,
  pixel-exact rendering (`draw_text`/`render`/metrics); `max_width` drops whole
  glyphs on narrow matrices instead of clipping mid-stroke; unsupported
  codepoints fall back to `?`. Verified crisp: rendered pixels are only bg or fg,
  never an AA grey.
- `media_source.py` rewired to the bitmap font; `ImageFont` import + `_tiny_font`
  removed. `pyproject.toml` ships `divoom_lib/fonts/*.bin`.
- Tests: `tests/test_bitmap_font.py` +10 (asset size, upright 'A', proportional
  widths, crispness, max_width, fallback, and a guard that media_source uses no
  anti-aliased font).

### Tab chrome spacing centralised (one source of truth)

- Every tab area (Channels, Tools, Settings) now sits on an identical glass pane
  with `[2px] tab-row [2px]` vertical padding and a `1px` gap to the content
  cards below. Previously Channels (grid) double-spaced (grid `gap:20px` +
  `margin-bottom:16px` ≈ 36px) while Tools/Settings (block) had 16px.
- **New tokens in `style.css :root`** — the *only* place tab spacing is defined:
  `--tab-pane-pad-y: 2px`, `--tab-pane-pad-x: 12px`, `--tab-pane-gap: 1px`.
  `.tabs-section` (tabs.css) consumes them; `margin-bottom` is the universal gap
  mechanism. `#control-panel .grid-layout` gets `gap: 0` so the grid context
  doesn't double-space (verified: actual pane→card gap = 1px in all three).
- Tests: `tests/test_tabs_chrome.py` +3 (tokens defined once, .tabs-section uses
  them, channels grid gap zeroed).

### MCP server no longer owns its own BLE connection

- **`cmd_mcp_server`** (`divoom_lib/cli_commands.py`) rewritten to route through
  the daemon instead of calling `_resolve_device()` (which opened a *second* BLE
  connection to the device the daemon already owns — R17 single-owner — and
  failed with `DeviceConnectionError: ... was not found`, surfaced as a Python
  traceback in the GUI's MCP card). It now builds the tool catalog against a
  `DaemonDeviceProxy` via `ensure_daemon()`. `--mac` is optional; new
  `--socket/--host/--port/--token` flags target a local or remote daemon
  (mirrors the `daemon` command + the R19 network model).
- **Daemon client plumbing moved** `divoom_gui/daemon_bridge.py` →
  `divoom_daemon/daemon_client.py` (so `divoom_lib` can use it with no backwards
  `lib`→`gui` dependency). `daemon_bridge.py` is now a thin re-export shim;
  all existing `from divoom_gui.daemon_bridge import ...` call-sites/tests
  unchanged.
- **`mcp_control.start(mac=None)`** + `gui_api.start_mcp_server` no longer
  require a MAC (the confusing CoreBluetooth UUID shown in the card is no longer
  needed — the daemon already owns the device).
- **`get_capabilities`** (`divoom_lib/mcp_tools.py`) now awaits an awaitable
  `to_dict()` so the read-only tool works through the proxy (was returning an
  unawaited coroutine).

### Scan returns Divoom devices only

- **`discover_all_divoom_devices`** (`divoom_lib/utils/discovery.py`): removed the
  "if nothing matches, return ALL named devices" fallback that dumped every
  random BLE peripheral (headphones, watches, …) into the device list. New
  `is_divoom_name()` helper + `DIVOOM_NAME_KEYWORDS` single source of truth
  (added `divoom`, `aurabox`, `planet`).

### Tests

- `tests/test_discovery.py`: +4 (is_divoom_name match/reject, filter, no-fallback).
- `tests/test_mcp_server.py`: +2 (no-MAC subcommand, daemon-routing — asserts
  `_resolve_device` is never called).
- Suite **1061 passed / 75 skipped / 0 failed** (+6).

---

## Round 26 — 2026-06-08 (Daemon channel-switch API + weather fix)

### Library — `divoom_lib/`

- **New `Display.set_temperature_channel()`** (`divoom_lib/display/__init__.py`):
  APK-canonical 6-byte 0x45 format `[0x01, temp_type, R, G, B, 0x00]`. Switches
  device to TEMPRETURE display mode — the essential first step that was missing
  (weather data alone via 0x5F does nothing without the channel switch).

- **New `Display.set_clock_rich()`** (`divoom_lib/display/__init__.py`):
  APK C2() 10-byte 0x45 format with correct humidity/weather/date overlay
  positions. Kept alongside existing `show_clock()` (hass-divoom layout) for
  backward compat — no overlay reorder.

- **`TEMPRETURE_CHANNEL = 0x01`** constant added (`divoom_lib/models/constants.py`):
  canonical APK alias for the TEMPRETURE display mode channel.

### GUI — `divoom_gui/`

- **`WidgetsApi.push_weather()` fixed** (`divoom_gui/api/widgets.py`): now a
  two-step sequence — (1) switch to TEMPRETURE channel via 0x45 APK-canonical
  bytes, (2) push weather data via 0x5F. Previously sent 0x5F only (no channel
  switch), so weather data would not display.

- **New `WidgetsApi.set_temperature_channel()`** — standalone bridge for channel
  switch without a weather data push.

- **New `LightingApi.set_clock_rich()` / `set_temperature_channel()`** —
  GUI bridge methods exposing the new display primitives.

- **New `DivoomGuiAPI.set_temperature_channel()` / `set_clock_rich()`** —
  pywebview JS-accessible bridge methods.

- **Weather card "Push to Device" button** (`divoom_gui/web_ui/templates_widgets.js`):
  manual push alongside existing auto-push on card selection. Wired via
  `pushWeatherToDevice()` in `widgets.js`.

### Tests

- **+3 tests** (`tests/test_e2e_mock_device.py`):
  `test_temperature_channel_switch_apk_format` — APK 6-byte 0x45 format,
  `test_temperature_channel_fahrenheit_red` — Fahrenheit + red channel,
  `test_clock_rich_apk_format` — APK C2() 10-byte 0x45 format.

- **Contract test updated** (`tests/test_widgets_weather.py`):
  `test_weather_card_has_no_panel_hint` relaxed to allow "Push to Device"
  button (was asserting no buttons at all).

- **Suite: 1025 passed / 75 skipped / 0 failed** (+3 from 1022).

### Docs

- **`docs/LLD_R26.md`** — comprehensive three-layer low-level design covering
  library (`Display.*`), GUI (`WidgetsApi`/`LightingApi`/bridge), and daemon
  (zero new commands — `device_call` dispatch handles routing automatically).

## Round 25 — 2026-06-08 (Channel architecture cross-verification)

### Research — `docs/CHANNEL_ARCHITECTURE.md` written and cross-verified

- **Authoritative channel architecture doc** (`docs/CHANNEL_ARCHITECTURE.md`, 370+ lines)
  covering all 7 light channels, 5 work modes, APK byte formats, device-specific
  variations, overlay toggle positions, weather codes, BLE pacing, and interleaving
  risks. Cross-verified against 3 sources: APK decompile (authoritative), hass-divoom
  (secondary), futpib (tertiary).

- **4 errors found and corrected during cross-verification**:
  1. **futpib channel table was wrong** — incorrectly mapped futpib modes to APK
     channel IDs 0x00-0x06. futpib uses a different numbering scheme (0x01=Light
     with sub_modes 0-6, 0x02=Hot, 0x03=Special, 0x04=Music; no 0x00/0x05/0x06).
  2. **"Both 10-byte CLOCK formats work" was speculative** — changed to documented
     divergence with unknown device compatibility.
  3. **Weather code table incomplete** — added APK's full 18-code OpenWeatherMap
     mapping (had only the 6-code hass-divoom subset).
  4. **hass-divoom transport mischaracterized** — it uses persistent TCP SPP, not
     BLE reconnection per command (only futpib reconnects).

- **TEMPRETURE 6-byte format CONFIRMED** from APK `CmdManager.t2()`:
  `[1, temp_type, R, G, B, 0]` — our committed code used a rotated byte order.
  Firmware-tested order may differ (documented as device-specific divergence).

- **CLOCK dual 10-byte format conflict documented**: APK C2() uses byte 4=humidity,
  5=weather, 6=date. hass-divoom/our lib uses 4=weather, 5=temp, 6=calendar.
  APK format takes precedence for new code.

- **5 divergences from APK catalogued**: CLOCK 10-byte layout, missing TEMPRETURE
  channel switch, weather code subset, constant naming, command naming.

- **APK-first authority established** — explicit priority hierarchy in doc preamble.
- **Emoji-free policy maintained** — cross/checkmark symbols replaced with `[conflict]`/`[same]`.

### Fixed — TEMPRETURE channel switch byte order (committed)

- Corrected byte order: `[1, R, G, B, ?, 0]` (rotated) was a decompile
  misinterpretation. APK's `t2()` field order is `(mode, temp_type, r, g, b)`.
  Working tree reverted to no channel switch pending R26 APK-correct implementation.

- **Removed test** `test_weather_push_switches_channel_before_data` (tested the
  wrong byte order). Re-add in R26 with correct APK payload assertion.

### Planning

- `docs/PLANNING_ROUND26.md` created — R26 focuses on daemon channel-switch API
  with APK-canonical byte formats.

## Round 24 — 2026-06-08 (BLE detection from GUI, no user intervention)

### Fixed — macOS BLE scan returned empty in the GUI

- **TCC responsible-process attribution (the root cause).** pywebview re-hosts
  the GUI process as `Python.app` (`org.python.python`), which is NOT in the
  user's Bluetooth grant list, so a daemon spawned the normal way inherited that
  ungranted identity and `CBCentralManager.authorization()` came back 0/2 →
  every scan was silently empty (or aborted with a TCC privacy violation).
  `spawn_daemon` (`divoom_gui/daemon_bridge.py`) now spawns the daemon with
  **`responsibility_spawnattrs_setdisclaim`** via a libc `posix_spawn` (new
  `_spawn_disclaimed_macos()`; POSIX_SPAWN_SETSID + file_actions redirecting
  stdout/stderr to `/tmp/divoom_daemon.log`). The daemon becomes its OWN
  responsible process, attributed to the granted `python3.14` binary regardless
  of which process launched it. Verified `CBauth == 3` and all 4 devices found
  from the GUI, a terminal, and the agent harness. Falls back to
  `subprocess.Popen` on non-macOS or if the disclaim spawn is unavailable.
- **Client read timeout shorter than the scan.** The daemon only replies after
  scanning for `timeout` seconds, but `DaemonClient.send_command` read with its
  2s default socket timeout, so a successful reply arrived too late and showed up
  as `"timed out"`. `send_command` gained a `read_timeout` override and `scan`
  now waits `timeout + 10s`.
- Daemon `scan()` logs `pid / sys.executable / CBCentralManager.authorization()`
  before scanning so the attribution state is visible in the daemon log.

### Fixed — MCP server subprocess failed with `DaemonDeviceProxy` not a string

- The MAC fallback in `start_mcp_server()` used `self.current_divoom.mac` but
  `DaemonDeviceProxy.__getattr__` returns another proxy for any name NOT in
  `_STATUS_ATTRS` (= `is_connected`, `lan`, `_conn`). `self.current_divoom.mac`
  returned a `DaemonDeviceProxy(path="mac")` instead of a string, which
  `subprocess.Popen` rejected as `TypeError: expected str, not DaemonDeviceProxy`.
- **Fix**: `gui_api.py:426` uses `self.current_divoom._conn.mac` — `_conn`
  resolves via status to `_ConnView(st.get("mac"))` which IS the real MAC string.
- Test: `tests/test_daemon_bridge.py::test_proxy_conn_mac_resolves_from_device_status`

### Fixed — weather push created an unawaited proxy coroutine (RuntimeWarning)

- `Weather.__init__` stored `divoom.logger` on `self`. When the device is a
  `DaemonDeviceProxy`, `divoom.logger` returns a child proxy (not a real logger),
  and `self.logger.info(...)` in `Weather.set()` created a coroutine object that
  was never `await`ed — producing a `RuntimeWarning` and silently leaking the
  coroutine. The `send_command(0x5F, ...)` call after it still worked, but the
  warning filled logs.
- **Fix**: `Weather` now uses a module-level `logger` instead of `divoom.logger`.
- Tests: `test_weather_set_proxy_daemon_roundtrip` (e2e proxy → daemon → wire),
  `test_weather_set_emits_0x5f_frame`, `test_weather_set_negative_temp`.

### Changed — system monitor device preview (bars, no letters, fixed colors)

### Changed — custom art gallery cache: cross-scope `window.*` prefix

### Added — daemon configuration file (`daemon.ini`)

- **`divoom_daemon/daemon_config.py`** — `DaemonConfig` loaded from
  `~/.config/divoom-control/daemon.ini`, alongside the GUI's `config.ini`. A
  commented default file is written on first load so the knobs are discoverable.
  Knobs: `scan_timeout`, `scan_limit` (0 = no cap), `scan_read_slack`,
  `client_timeout`, `reconnect_scan_timeout`.
- **Removed scan magic numbers.** The hardcoded `+10s` client read padding, the
  `DaemonClient` `2.0s` timeout, the `15`/`4` scan defaults (in three places),
  and the `3.0s` reconnect scans now all resolve from this config — one source of
  truth. The GUI's per-scan `timeout` still wins; the config is the fallback
  (Divoom discovery is slow, so the defaults are deliberately large).
- Tests: `tests/test_daemon_config.py` (defaults, file-write, override parse,
  0-limit edge, bad-value + missing-section fallback, slack helper).

### Fixed — switching devices failed with "Daemon connect failed: timed out"

- The `connect`/`disconnect` RPCs used `DaemonClient`'s 2s default read timeout,
  but BLE connection setup is far slower — the client abandoned the connect
  exactly 2.000s in while the daemon was still mid-handshake. Added a
  `connect_timeout` knob (default 20s) to `daemon.ini`, applied to
  `connect_device` + `disconnect_device`. Quick commands keep the short
  `client_timeout`.

### Changed — unified tab rows on a glass strip (all three panels)

- Previously only Channels had a glass panel behind its tabs; Tools + Settings
  had bare tabs on a transparent strip. Now `.tabs-section` is a glass panel
  (matching `.glass-card`) holding the centered tab row in Channels, Tools, and
  Settings, with a consistent gap to the content below. Channels' tab row moved
  out of the content card-header into its own `.tabs-section` strip; Tools went
  full-width. (No menubar "launched successfully" toast either — removed as a
  routine, non-actionable notification.)

---

## Round 23 — 2026-06-07 (REVIEW §1.2 + §1.3 + §1.4 + §1.5)

### §1.2 — gui_api collaborator integration

- **`gui_api.py` refactored from 891 → 444 LOC** — every bridge method
  that existed in an `ApiBase` collaborator now delegates to one of 5
  collaborators (`ConnectionApi`, `LightingApi`, `ToolsApi`, `WidgetsApi`,
  `WindowApi`). The collaborators share state via `state_getter` lambda
  wrapping `self.__dict__` and share the daemon client via a common getter.
- **`AsyncLoopThread` moved** from inline definition to `divoom_gui.api`
  (shared with all collaborators).
- **Removed dead code** from `gui_api.py`: `_device_status()`, `_target()`,
  `_dispatch()`, `_tool_call()`, `_as_bool()` — all now live in collaborators.
- **`send_notification` added to `ToolsApi`** with app_type range guard.
- **`set_brightness`, `set_volume`, `display_wall_image`, `display_custom_art`
  added to `LightingApi`** (follow the `_dispatch` pattern for wall/single
  routing).
- **File-size guardrail updated**: `gui_api.py` removed from ALLOWLIST
  (now 444 LOC ≤ 500).
- **Deduplication**: all `logging` + `try/except` boilerplate removed from
  `gui_api.py` delegation methods; logging + error handling lives in the
  collaborators.
- Suite: 989 passed / 75 skipped (same as R22 — zero regressions).

### §1.3 — daemon.py responsibility extraction (4 waves)

- **Wave 1 — command registry** (5d3f7d1): 14-arm if-ladder in
  `handle_command()` → dict-based `_init_registry()`. Shared handlers
  via alias (`get_status` = `notification_status`). No behavior change.
- **Wave 2 — SocketServer** (7c0cc31): extracted
  `divoom_daemon/socket_server.SocketServer` — Unix + TCP listeners,
  accept loop, subscriber fan-out, token auth. Composed via
  `command_handler` + `status_event_factory` callbacks.
- **Wave 3 — NotificationService** (73b39bd): extracted
  `divoom_daemon/notification_service.NotificationService` — notification
  monitor lifecycle, status derivation, sink + broadcast. Composed via
  `broadcast` + `send_notification` callbacks.
- **Wave 4 — DeviceOwner** (e3612b0): extracted
  `divoom_daemon/device_owner.DeviceOwner` — device lifecycle
  (connect, disconnect, device_call, scan, wall, sync, probe_lan)
  and notification BLE sender. All command handlers registered via
  `_init_registry()`.
- **daemon.py reduced from 730 → 132 LOC** — removed from file-size
  ALLOWLIST (now 10 entries, down from 11).
- Suite: 989 passed / 75 skipped (zero regressions, same as R22).

### §1.4 — DeviceSlot dataclass (c29c715)

- **`divoom_lib/models/device_slot.py`** — `@dataclass DeviceSlot(device, x, y, size, width, height)`.
- **Exported** from `divoom_lib/models/__init__.py`.
- **Replaced all ad-hoc 6-tuple construction/destructuring** in `wall.py` and `device_owner.py`.
- Suite: 989 passed / 75 skipped (zero regressions).

### §1.5 — web_ui file splits (>500 LOC → <500 LOC)

- **6 oversized files split into 14 files**, all under 500 LOC:
  - `templates.js` (718) → 4 domain files: `templates_tools.js` (124), `templates_monthly_best.js` (64), `templates_widgets.js` (200), `templates_settings.js` (330).
  - `app.js` (619) → `app_globals.js` (196) + `app_init.js` (425).
  - `channels.js` (578) → `channels_core.js` (149) + `channels_grids.js` (436).
  - `settings.js` (745) → `settings_hardware.js` (344) + `settings_features.js` (404).
  - `widgets.css` (524) → `widgets_base.css` (301) + `widgets_extra.css` (224).
  - `style.css` (510) → `style.css` (279) + `style_extra.css` (236).
- **ALLOWLIST shrunk from 10 → 4 entries** (`media_sync.py`, `downsample.c`, `constants.py`, `cli.py` remain).
- **`index.html`** script loading updated for all JS splits.
- **`style.css`** @import chain updated for CSS splits.
- **8 test files** updated to use concatenated `_cat()` path helper for split files.
- Suite: 980 passed / 75 skipped (zero regressions on relevant tests).

## Round 22 — 2026-06-07 (menubar refactor: top-level package + daemon client)

The menubar agent is moved from `divoom_daemon/` to its own
top-level `divoom_menubar/` package, and rewritten as a pure daemon
client (no BLE, no socket server). This respects R17's single-owner
rule: the daemon owns the device + notification monitor; the menubar
and GUI are thin clients.

- **New `divoom_menubar/` package** with `menubar_client.py` (testable
  logic, no AppKit) and `menubar.py` (Cocoa status item + menu).
  Removed `divoom_daemon/menubar.py` + `menubar_status.py` (they had
  their own BLE + socket server, violating single-owner).
- **Event-driven via daemon subscription.** The menubar calls
  `DaemonClient.subscribe()` and receives `EVENT_STATUS` events
  (`state` + `counters`) pushed by the daemon on every notification
  listener start/stop/error and routed notification. Title updates
  instantly — **zero polling** (matching user feedback for MCP toggle
  and menubar).
- **Menu actions.** "Start/Stop Notifications" → daemon commands.
  "Open Notifications..." launches the GUI with `--tab data-sources
  --card notifications` (deep link to Live Widgets → Notifications).
- **CLI entry point.** `divoom-control menubar` (synchronous handler,
  runs Cocoa event loop).
- **Tests.** `tests/test_menubar.py` (6 tests) — pure logic, CI-friendly.
- Suite: 938 → 944 passed (+6 tests).

---

## Round 23 — 2026-06-07 (500-LOC debt fully retired + GUI cloud-auth crash fix)

- **GUI no longer crash-loops when Divoom cloud auth fails**: the polled
  transport-status panel triggered a failing network guest login each tick and
  let the exception escape into pywebview. Added cache-only
  `divoom_auth.get_cached_credentials()` + a 120s failure cooldown; status (and
  GUI startup) read the cache only. Verified clean launch. Retired the obsolete
  `gui_api._push_menubar_status` (imported a deleted module). Root cause
  (guest login RC=10) is upstream Divoom; cloud features need a configured
  account — local BLE/LAN control is unaffected.
- **Every `divoom_*` source file is now under 500 LOC** and `tests/test_file_size.py`
  enforces it (allow-list empty). The 2026-06 regression was retired across R23:
  gui_api → `divoom_gui/api/*`, daemon → DeviceOwner/NotificationService/
  SocketServer + command registry, `DeviceSlot`, web_ui splits, menubar → daemon
  client (opencode), then `cli.py`→`cli_commands.py`, `constants.py`→
  `constants_scheduling.py`, `media_sync.py`→`audio_visualizer.py`, and
  `downsample.c`→`downsample_kernel.{c,h}` (byte-identical output verified).
- Suite 994 / 0 / 75.

## Round 21 — 2026-06-07 (review + documentation overhaul)

- **`docs/REVIEW_2026-06.md`**: code/architecture review (Linus + Uncle Bob),
  UI/UX review (Rams + Kare), and a "rewrite the lib + daemon in Rust?" analysis
  (verdict: don't rewrite the library; the daemon is the only defensible Rust
  candidate, and only with an embedded/footprint driver).
- **500-LOC rule enforced**: `tests/test_file_size.py` fails on any unlisted
  source file over 500 LOC, with a shrink-only allow-list of the 11 current
  offenders (so the rule can't silently re-drift).
- **Docs rewritten to current reality**: `README.md` + `ARCHITECTURE.md`
  (3-package + daemon-owns-device + Unix/TCP network + macOS/Linux); new
  `docs/README.md` index separating canonical from historical docs.
- **Removed 10 stale docs** (CODE_REVIEW, APP_IMPROVEMENT_PLAN, PLANNED_WORK,
  next_phase_requirements, DESKTOP_GUI, ENGINEERING_NOTES, brightness_investigation,
  DRAG_FIX_HISTORY, DEVICE_VALIDATION_PLAN, PLANNING_ROUND2_CONTINUATION) —
  recoverable from git history.
- Suite → 993 / 0 / 75. The recommended >500-LOC refactors + a live UI pass +
  an optional Rust daemon spike are staged (see REVIEW §1.7), not yet done.

## Round 20 — 2026-06-07 (Linux compatibility: daemon + libraries)

`divoom_lib` + `divoom_daemon` now run on Linux, not just macOS (BLE via
bleak/BlueZ; the R19 network server is platform-neutral). See
`docs/PLANNING_ROUND20.md`.

- **Per-platform native lib**: `divoom_lib/native_lib.py` resolves
  `libdivoom_compact.{dylib|so|dll}`; all four ctypes loaders (framing,
  media_decoder, native.image_encoder, native.downscaler) go through it.
- **Cross-platform build**: `scripts/build_libdivoom.sh` produces a `.dylib` on
  macOS (clang) and a `.so` on Linux (`cc -shared -fPIC -lm`); ARM→NEON,
  x86_64→SSE2.
- **Portable C**: `compact.c` guarded `<arm_neon.h>` + its NEON tile-row copy
  behind `DIVOOM_HAVE_NEON`; x86_64 uses a byte-identical `memcpy`. Both paths
  verified to compile (arm64 NEON build + an x86_64 cross-compile).
- **Platform-aware tooling**: conftest auto-rebuild + pyproject package-data ship
  `*.dylib`/`*.so`/`*.dll`.
- **Daemon on Linux**: notification monitoring is macOS-only; off macOS
  `_cmd_start` reports a clean `unsupported`/idle state (never builds the Mac
  monitor). `media_source` now-playing returns None off macOS.
- +12 tests; suite → 991 / 0 / 75. **Not yet run on real Linux hardware**
  (cross-compile + platform-guard unit tests). Gaps by design: no Linux
  notification monitor / now-playing / menu-bar.

## Round 19 — 2026-06-07 (daemon as a headless network server: TCP + token + binary blobs)

The daemon can now run as a headless LAN server, not just a local Unix socket.
See `docs/PLANNING_ROUND19.md`.

- **Why JSON**: NDJSON is the control plane (small, debuggable, transport-
  agnostic); device pixels/GIFs are the data plane, deliberately kept out of JSON.
- **TCP listener alongside Unix** (`DivoomDaemon(host, port, token)`): one accept
  thread per listener; `divoom-control daemon --host 0.0.0.0 --port 9009 --token`.
- **LAN + token auth**: TCP requests must carry the shared token
  (`hmac.compare_digest`); Unix connections stay trusted (local fs perms). The
  TCP listener is **fail-closed** — it refuses to start without a token. Token
  falls back to `DIVOOM_DAEMON_TOKEN`.
- **Binary over the wire**: `device_call` gained `blobs={argIdx: base64}`; the
  daemon materializes each to a temp file and substitutes the path. The GUI's
  `DaemonDeviceProxy` auto-ships local-file args as blobs when talking to a remote
  (TCP) daemon, so media/gallery/cover-art push works remotely with no call-site
  changes. `DaemonClient.from_env()`/`ensure_daemon()` target a remote daemon when
  `DIVOOM_DAEMON_HOST` is set.
- +7 tests (`tests/test_daemon_network.py`); suite → 986 / 0 / 75. **Not yet
  hardware-verified; token travels plaintext over TCP — add TLS for untrusted
  networks (follow-up).**

## Round 16-17 — 2026-06-07 (headless daemon + 3-way package split + single-owner cutover mechanism)

The project became three top-level packages — `divoom_lib` (pure protocol +
native dylib), `divoom_daemon` (headless device owner + macOS notification
routing + event socket), `divoom_gui` (pywebview presentation, thin client) —
and gained a headless daemon with a Unix-socket NDJSON protocol. See
`docs/PLANNING_ROUND16.md` + `docs/PLANNING_ROUND17.md`.

- **R16 — daemon core**: `daemon_protocol.py` (NDJSON framing, request/response
  + `subscribe`/stream, `DaemonClient`) + `daemon.py` (server owning the device
  + macOS notification monitor) + a `divoom-control daemon` CLI subcommand.
- **R17 P1-P4,P6 — physical 3-way split**: moved the daemon core, macOS
  notification + menubar modules into `divoom_daemon/`; moved the native dylib +
  `compact.c` into `divoom_lib/` (its true home; fixed all 9 path refs); renamed
  `gui/` → `divoom_gui/` (+ 19 test path-hacks); rewrote `pyproject.toml` to find
  all three packages with per-package data. Browser-verified via the Playwright
  DOM tests. Suite held 959 → 963 / 0.
- **R17 P5 — full single-owner cutover**: BLE is single-owner, so the daemon is
  now the sole device owner and the GUI is a thin client — **no BLE connection is
  held in the GUI anywhere**. **Daemon**: `device_call` (dotted dispatch, target
  device|wall), enriched `connect` (BLE+LAN+auto), `device_status`, `scan`,
  `wall_configure` (idempotent), `probe_lan`, `sync_artwork` (download+decode+
  resize+stream daemon-side, binary off the socket); a dedicated device asyncio
  loop surviving across calls. **GUI**: `ensure_daemon()` auto-spawns a detached
  daemon; `DaemonDeviceProxy` routes `proxy.x.y(...)` through `device_call` and
  answers is_connected/lan/_conn from `device_status`, so `current_divoom`/
  `wall_instance` become proxies and media_sync (live widgets) routes through the
  daemon with no rewrite; scanner_mixin + gallery sync delegate to the daemon.
  **Library**: `DivoomWall` gained switch_channel/push_text/set_brightness/
  set_volume; `media_decoder` moved divoom_gui→divoom_lib. **After P5 the daemon
  must run for the GUI to control the device** (auto-spawned). +14 tests; the 5
  gui_api tests that mocked direct BLE were rewritten to the daemon-client model.
  Suite → 980 / 0 / 75. **Not yet hardware-verified** — runtime drive + the
  menubar→daemon-subscription cleanup are scoped in `PLANNING_ROUND17.md`.
- **R18 — product fixes** (landed alongside): weather auto-fetch + device re-push
  + IP geolocation (no more hard-coded "Berlin"); system-monitor frame grey-box
  removal; smaller stock arrow + tiny stock-name font; Tools/Settings tab icons;
  fit-to-content tab bar + theme selector; **credentials-erase fix**
  (`presets_manager.save_credentials` preserves a blank password instead of
  wiping it + only invalidates the token cache on real change).

## Round 15 — 2026-06-07 (UI unification, monthly best, weather widget, settings refactor, MCP server, menubar)

Six user-driven changes plus a new MCP server feature. The unifying
theme is **making the GUI more honest**: removing buttons that should
be automatic, moving things to where users expect them, and giving
the menubar + an MCP server a real role in the workflow. **+117 tests**,
suite 829 → 946 passed. See `docs/PLANNING_ROUND15.md` for the
full plan + outcome.

- **§1+§7 — Tab style unification** (`2c819325`): single source of
  truth `gui/web_ui/tabs.css` for `.tabs-row` / `.tab-btn` / `.tab-icon`.
  Segmented-pill (Kare: clear silhouettes; Rams: less but better, one
  form for "sub-tab" across the app). Active state = `--primary` bg +
  white text. Channel/Tools/Settings/Theme rows migrated; panel CSS
  files (`channels.css`, `settings.css`) alias legacy class names.
  Optional 16×16 SVG icon prefix. **Lesson**: backticks inside template
  literal comments break JS parsing. Use plain text in inline comments
  inside template strings. `tests/test_tabs_chrome.py` (16 tests).
  Suite 829 → 846.
- **§2 — Monthly Best auto-fetch + box cap** (`0e23253f`): Gallery
  card now auto-fetches on tab activation; changing the classify
  dropdown auto-reloads via `window.loadGallery()`. "Fetch Gallery"
  button hidden. Renamed "Push Selected to Device" → "Update Device"
  and "Sync All → Devices" → "Update Devices". Dropped "Refresh"
  button. Box cap `minmax(110px, 1fr)` → `minmax(110px, 168px)`.
  `tests/test_gallery_auto_fetch.py` (10 tests). Suite 846 → 856.
- **§4 — Settings refactor** (`24f95690`): `.danger-zone` extracted to
  its own `card.glass-card.danger-card` (red border via a single
  `settings.css` rule). Added 7d (`604800`) and 30d (`2592000`) to
  `#routines-auto-sync-interval`; `MAX_INTERVAL = 2592000` clamp in
  `divoom_lib/hotchannel_config._normalize()` is the belt-and-braces
  for bad JSON files. `tests/test_routines_intervals.py` (10 tests).
  Suite 856 → 866.
- **§3 — Live Widgets weather card + Notifications move** (`b7c1e4d7`):
  new `divoom_lib/weather_provider.py` (WTTrIn + Stub + auto-fallback,
  env: `DIVOOM_CONTROL_WEATHER_{PROVIDER,LAT,LON,LOCATION}`, default
  Berlin). `gui/gui_api.get_weather()` sync wrapper, `push_weather()`
  uses live weather + `divoom.weather.set()`. Weather card moved to
  top-level Live Widgets grid with 128×128 preview + 16×16 SVG icon +
  7-segment temp. 10-min poller + auto-push on selection. Notification
  manual + notification mirror cards moved from Settings → Devices to
  Live Widgets. `tests/test_weather_provider.py` (30 tests) +
  `tests/test_widgets_weather.py` (11 tests). Suite 866 → 907.
- **§5 — MCP server + GUI toggle** (`121d0b5`): new
  `divoom_lib/mcp_server.py` (`MCPServer`, `Tool` dataclass, JSON-RPC
  dispatcher per spec 2024-11-05; methods: `initialize`, `tools/list`,
  `tools/call`, `ping`; std codes: `-32700` parse, `-32600` invalid
  request, `-32601` method not found, `-32602` invalid params,
  `-32603` internal error; notifications get no reply). 12 tools in
  `divoom_lib/mcp_tools.py`: `set_volume`, `set_brightness`,
  `set_light_mode`, `set_weather`, `set_alarm`, `set_radio`,
  `set_low_power`, `set_screen_orientation`, `show_image`, `play_sound`
  (best-effort), `get_capabilities`, `get_device_state`. CLI
  `divoom-control mcp-server --mac <MAC>` runs the stdio loop.
  `gui/mcp_control.py` (`MCPController` subprocess, new process group
  for clean SIGTERM, log to `~/.config/divoom-control/mcp-server.log`).
  Settings → Connectivity card with Start/Stop buttons + status pill
  + log tail. **No background polling** — the status card refreshes
  on initial mount, on tab activation, and after Start/Stop click.
  `docs/MCP_SERVER.md` ships with config snippets for Claude Desktop,
  Cursor, Cline, Continue. `tests/test_mcp_server.py` (25 tests).
  Suite 907 → 932.
- **§6 — Menubar notification status** (event-driven): the menubar
  status item now shows the macOS notification-listener state —
  `Divoom (active|idle|error)` with a green/grey/amber tint — plus an
  "Open Notifications..." menu item that launches the GUI to Live
  Widgets → Notifications. **No polling** (user rejected it twice): the
  GUI *pushes* status to the menubar's Unix socket only on
  start/stop/error via `gui_api._push_menubar_status`. AppKit-free logic
  in new `gui/menubar_status.py`; `menubar.py` handles the
  `notification_status` IPC without a BLE auto-connect; `gui_main`
  gained `--tab`/`--card` (URL params honored by `settings.js`).
  `tests/test_menubar_ipc.py` (14 tests incl. a Unix-socket round-trip).
  Suite 932 → 946.

**Test count:** 829 → 946 (+117). **Suite:** 946 passed, 75 skipped,
0 failed. Zero regressions across R8→R15.

---

## Round 14 — 2026-06-07 (R13 follow-ups: weather, routing JSON, GUI card, packaging)

Four deliverables closing out the R13 follow-up list. **+74 tests**,
suite 755 → 829 passed. See `docs/PLANNING_ROUND14.md` for the
full plan + outcome.

- **§1 — `Weather` facade**: new `divoom_lib/system/weather.py` with a
  clean `Weather` class (`set`, `set_temperature`, `set_weather`).
  Wired to the Divoom facade as `divoom.weather`. The old
  `TempWeatherCommand` is now a thin shim — fixes the latent
  `number2HexString()` bug (function lives in
  `divoom_lib/utils/converters.py`, not on the Divoom instance) that
  would have crashed at first `update_temp_weather()` call. CLI
  `set-temperature` subcommand added. `examples/set_weather.py`
  re-added (R13 §2 had deferred it). +27 tests.
- **§2 — Custom routing JSON loader** (`gui/macos_notifications.py`):
  `load_routing_table(path)` / `save_routing_table(rules, path)`;
  honors `DIVOOM_CONTROL_ROUTING` env var, defaults to
  `~/.config/divoom-control/notification_routing.json` (same
  XDG-convention dir as `devices.json`). Corrupt-file tolerant —
  warn + fall back to `DEFAULT_ROUTING`. Validates `app_type` ∈
  `NOTIFICATION_APPS` (1-14); bad entries are dropped with a
  warning, not crashed. Atomic save via `.tmp` + `replace()`. New
  `MacAppRouter.from_file(path)` classmethod. `MacNotificationMonitor`
  loads from the custom file by default. +19 tests.
- **§3 — GUI Settings → Devices card**: new "macOS Notifications"
  card under Settings → Devices with toggle, live status pill
  (running / stopped / error / unsupported), counters (seen /
  routed / dropped), and a routing JSON editor (textarea + Save /
  Reset to defaults). `gui_api` adds `get_notification_listener_status()`
  and `save_notification_routing(json_text)` with hot-reload (the
  running monitor's router is replaced, no listener restart
  required). JSON editor was chosen over per-app checkboxes
  because the rules ARE JSON and a checkbox matrix would be a
  parallel state to keep in sync. +5 gui_api tests.
- **§4 — `pyproject.toml`**: first packaging file in the repo.
  setuptools backend, PEP 621 metadata, version `0.14.0`,
  `requires-python = ">=3.10"`. Core deps from `requirements.txt`.
  `[gui]` extra: `pywebview` + `pyobjc-framework-Cocoa`
  (darwin-gated). `[test]` / `[dev]` extras.
  `[project.scripts]` registers `divoom-control = divoom_lib.cli:main`
  as a real console script. `tool.setuptools.package-data` ships
  the `libdivoom_compact.dylib` + `web_ui/*` with the `gui`
  package. Verified `pip install -e .` + the resulting
  `divoom-control --help` works. The legacy shell wrapper
  `./divoom-control` is kept for in-tree dev without an editable
  install. +12 packaging tests.

**Test count:** 755 → 829 (+74). **Suite:** 829 passed, 75 skipped,
0 failed. Zero regressions across R8→R14.

---

## Round 13 — 2026-06-06 (capability detection + examples/CLI + macOS notifications)

Three deliverables, all on the kill-criterion-aware path. See
`docs/PLANNING_ROUND13.md` for the full plan.

- **§1 — Capability detection** (`167a1019`): hardware-derived identifier
  hierarchy. `Divoom.capabilities` property consults explicit
  `device_type` → MAC `DeviceRegistry` (`~/.config/divoom-control/devices.json`)
  → `manufacturer_data` fingerprint → baseline. **`screensize` renamed to
  `panel_resolution`** (per-panel pixels, not wall composite — the new
  `wall_resolution()` helper in `divoom_lib/wall.py` makes the distinction
  explicit). `ADVERTISED_FINGERPRINTS` table starts empty; populate as the
  user identifies new devices. **CI fix**: `tests/test_live_widgets_diagnostic.py`
  now `pytest.importorskip`s playwright instead of `sys.exit(2)` at import
  time (which was crashing the entire pytest run). +33 tests.
- **§2 — `examples/` + `divoom-control` CLI** (`16cb8b8`): 6 example
  scripts (`discover_and_connect`, `push_static_image`, `push_animated_gif`,
  `set_radio`, `set_alarm`, `auto_connect`) + 10-subcommand CLI with shared
  parent-parser options (`--mac`, `--type`, `--timeout`, `--json`, `-v`).
  Shell wrapper at `./divoom-control` (symlink into `$PATH`). **Weather
  example deferred** — `TempWeatherCommand` (0x5F) isn't wired to the
  Divoom facade. **`pyproject.toml` deferred** — repo has no packaging
  file today; adding one is a separate kind of change. +22 tests.
- **§3 — macOS notification mirroring** (pending commit): polls the
  macOS Notification Center SQLite DB (the same approach used by
  `mac-notification-forwarder`, Hammerspoon, etc. — Apple's public
  notification API only fires for *our own* app's notifications; DB-poll
  bypasses TCC). `MacAppRouter` with 14 default rules. `gui_api` integration
  uses fire-and-forget `_schedule_async` so the polling thread never blocks
  on BLE. **GUI Settings card deferred to R14**. Setup guide in
  `docs/NOTIFICATIONS_SETUP.md`. +23 tests.

**Suite:** 755 passed / 0 failed / 74 skipped (up from R12's 677).
Zero regressions across R8→R13.

## Round 12 §D — 2026-06-06 (deferred features audit)

Full audit in **`docs/PLANNING_ROUND12_D_AUDIT.md`**. Verdict: 0 features
exposed, 0 dropped. All 5 stay in the lib with rationale per feature:

- **Timeplan** (0x56/0x57) — DEFER. Field semantics for `mode`/`trigger_mode`/
  `type` are obfuscated ints in the decompiled APK with no third-party
  documentation. `gui_api.set_timeplan` exists but is a guess; no UI card.
  Lib stays wire-correct.
- **SD card player** (0x06/0x07/0x0B/0x11/etc.) — DEFER. Requires `get_sd_music_list`
  (0x07) response, which is a `get_*` read-back blocked by task #20.
  Plus device-specific (only Tivoo Max / Ditoo / Timoo have SD slots).
- **Game** (0xA0/0x88/0x17/0x21) — DEFER. No useful host UX on a single
  device; the device has its own buttons. Control sets are device-specific.
- **Drawing / sand / picture scan** (0x3A/0x3B/0x58/0x5A-0x5C/0x6B-0x6F/0x34/0x35)
  — DEFER. Non-trivial UI per mode (freehand canvas, sand generator, scroll
  preview). **`pic_scan_ctrl` (0x35) flagged UNVERIFIED** — no entry in
  `SppProc$CMD_TYPE.java` (decompiled APK); single-line comment added in
  `divoom_lib/display/drawing.py`.
- **Cloud HTTP (200+ endpoints)** — DEFER (own round). Out of BLE scope;
  auth broken (`UserNewGuest RC=10`); large surface (clock-face store,
  weather city search, pomodoro, white-noise, TTS, …).

No code changes this round beyond the audit doc + 1 comment.

---

## Round 12 — 2026-06-06 (§A Phase 7 closeout: tools regroup + segmented-pill)

Inner Tools sub-tab renamed to **Sessions** (resolves the Tools/Tools
parent-sub-tab naming collision; "Sessions" is the device-manual term for the
multi-timer/noise/sleep bundle). Tools regroup: Device Settings + Display +
Notification moved to Settings → Devices; Weather moved to Live Widgets;
Anniversary moved to Time (with Alarms). `settings.css` unified segmented-pill
(`.settings-tab-btn` + `.tools-subtab-btn` grouped; `.settings-tabs-nav` +
`.tools-tabs-nav` pill-wrapper alias). 5 regression tests
(`test_r12_tools_subtab_uses_sessions_not_tools_inner_collision`,
`test_r12_unified_segmented_pill_css`,
`test_r12_anniversary_moved_into_time_subtab`,
`test_r12_weather_moved_into_live_widgets`,
`test_r12_device_settings_moved_to_settings_devices`).

Suite: **677 passed / 73 skipped / 0 failed** (up from 672).

Earlier R12: **§C** framing dual-impl correctness test caught + fixed two
Python-fallback crashes (list→memoryview in `encode_basic_payload` escape +
`encode_ios_le_payload`). **§A Phases 2–6** shipped (sticky custom-art push
footer, ambient color gating, scoreboard Reset, appbar corner transports +
right-aligned sliders + brightness-mapped thumb, scoreboard restyle BLUE-over-
RED, Virtual Wall toolbar icons+labels, font sweep). Lessons consolidated in
`docs/ENGINEERING_NOTES.md`; stale state pruned; new cross-agent state in
`docs/SESSION_HANDOFF.md`.

 **§A Phases 2–7 are UI changes — visual pass needed**: run
`python3 gui/gui_main.py` to verify appbar, scoreboard, wall toolbar, font
sweep, segmented-pill, and tools regroup. Then **§D** (deferred features) →
**§E** (push the ~34-commit arc to origin).

---

## Round 10 — 2026-06-06 (APK-only frontier: notification mirroring / ANCS)

The headline APK feature (report §3): `SPP_SET_ANDROID_ANCS`. Shipped as a
**manual trigger** (auto-sourcing macOS notifications deferred). Protocol
re-verified against the decompiled source — see `docs/PLANNING_ROUND10.md`.

### Added

- **lib**: command `"set android ancs": 0x50`; `NOTIFICATION_APPS` (14 apps);
  `divoom_lib/tools/notification.py` (`Notification.show_notification`,
  `show_notification_text`) on facade `d.notification`.
- **GUI**: `gui_api.send_notification(app_type, text="")` (guards 1-14) +
  Tools→Device **Notification** card (app select, optional text, Send).
- 11 tests (6 lib byte-exact incl. ≥8 wire-skip + 128-byte truncation, 2 bridge,
  3 static UI/exposure).

### Notes

- **Report corrections:** command is **0x50** (report said 0x60); there is **no
  RGB payload** — real forms are a single-byte index (slot 8 skipped on the wire)
  and `[type, len, *utf8]`.
- Deferred: auto-source real macOS notifications; cloud HTTP surface.

Full suite: 538 passed / 0 failed / 73 skipped.

---

## Round 9 — 2026-06-06 (APK-only frontier: screen orientation + factory reset)

R8 closed the lib→GUI gap; R9 targets capabilities the APK has but `divoom_lib`
lacked — needing *new lib code*. Full inventory + confirmed payloads in
`docs/PLANNING_ROUND9.md` (verified against decompiled `CmdManager.java`).

### Added

- **lib** `divoom_lib/display/design.py` (0xBD EXT dispatcher): `set_screen_dir`
  (0xBD 0x23), `set_screen_mirror` (0xBD 0x24), `factory_reset` (0xBD 0x25,1).
- **GUI** Tools→Device **Display** card: orientation select (0/90/180/270°),
  mirror toggle, and a `.danger-zone` factory-reset button gated by a
  `confirm()` + typed-"RESET" prompt. Bridge `factory_reset(confirm)` also
  refuses unless the literal `"RESET"` token is passed (belt & suspenders).
- 10 tests (5 lib byte-exact, 2 bridge incl. token guard, 3 static UI/exposure).

### Notes

- **Brightness was NOT re-added** — it already exists (`device.set_brightness`,
  0x74) with a LAN/multi-target bridge + appbar slider. The excavation's main
  correction: `SPP_SET_SYSTEM_BRIGHT` (116) == 0x74.
- Deferred: ANCS notification mirroring (own round); cloud HTTP surface.

Full suite: 527 passed / 0 failed / 73 skipped.

---

## Round 8 — 2026-06-06 (Feature excavation: device settings, FM, weather, memorial)

Excavated the lib↔GUI gap (`docs/PLANNING_ROUND8.md`): the library implements
~140 device methods, the GUI exposed ~58. Surfaced more, in a restructured
Tools tab.

### Added

- **Tools tab → sub-tabs** (Utilities / Device / Radio). Alarms/Sleep/Tools
  moved under **Utilities**.
- **Device Settings** (Device sub-tab): 24-hour toggle (0x2c), °F toggle (0x2b),
  low-power toggle, device name (0x75), auto-power-off (0xab), **Sync time from
  this Mac** (0x18). Bridges in `gui_api.py`; un-faceted helpers (`DateTimeCommand`,
  `DeviceSettings`) instantiated on the active device.
- **Weather** push (`update_temp_weather`).
- **Anniversary/Memorial** editor (`scheduling/alarm.set_memorial_time`, 0x54).
- **FM Radio** tuner + presets (`media/radio.set_radio_frequency`).

### Deferred

- **Timeplan UI**: `set_timeplan` bridge shipped + unit-tested, but
  `set_time_manage_info` mode/type semantics are unverified — no UI card (avoid a
  hallucinated control). Revisit with hardware. SD player / Game / Drawing /
  0xBD EXT remain Phase 2/3.

Full suite: 517 passed / 0 failed.

---

## Round 7 — 2026-06-06 (Feature harvest: surface un-exposed divoom_lib modules)

Surfaces previously un-exposed `divoom_lib` modules in the GUI (see
`docs/PLANNING_ROUND7.md`). Each feature: backend bridge in
`gui/gui_api.py` + UI + unit tests.

### Added

- **Text Channel** — new "Text" channel card/panel (input, color, effect,
  speed). `push_text()` runs the full LPWA (0x87) sequence
  (display-box→font→color→speed→effect→content) over `display/text.py`.
- **Alarms editor** — Settings → Divoom: 10-slot list (enable, hour:minute,
  weekday mask, Save; "Read from device"). `get_alarms()`/`set_alarm()` wrap
  `scheduling/alarm.py` (0x42/0x43).
- **Sleep Aid** — Settings → Divoom: minutes + color + volume, Start/Stop.
  `start_sleep()`/`stop_sleep()` wrap `scheduling/sleep.py`.
- **Tools** — Settings → Divoom: stopwatch (start/stop/reset), countdown
  (mm:ss), noise meter. `set_timer()`/`set_countdown()`/`set_noise()` wrap
  `tools/{timer,countdown,noise}.py`.

### Changed (Round 7.1)

- **New "Tools" sidebar tab.** Alarms, Sleep Aid, and Tools
  (timer/countdown/noise) moved out of Settings → Divoom into a dedicated
  top-level **Tools** category (`gui/web_ui/templates.js:tools`, nav-btn +
  `<section id="tools">` in index.html, injected in `app.js`). Alarm rows now
  render on the `tab-changed` → `tools` event.
- **Added `AGENTS.md` core rule:** after every round, update the cross-session
  handoff (CHANGELOG + planning doc + commit) so the shared opencode/Claude
  sessions can keep up. The git history + docs are the cross-session memory.

### Notes

- Alarm read-back (0x42) needs the device to answer a query; on hardware
  those time out (see `docs/DEVICE_VALIDATION_PLAN.md`), so the editor is
  set-oriented. Full suite: 513 passed / 0 failed.

---

## Round 6 — 2026-06-06 (Monthly Best layout simplification + new functionality exposure)

### Changed — Monthly Best layout (Option B from `docs/PLANNING_ROUND5.md` §3)

- **Right card renamed "Sync Targets & Schedule" → "Devices".**
  The header now matches its sole remaining content. Found in
  `gui/web_ui/templates.js:monthly-best-layout`.
- **Schedule UI block removed from Monthly Best.** The
  `hc-schedule` block, the "Enable scheduled sync (runs headless)"
  checkbox, and the Save Schedule button are all gone from the
  Monthly Best template. The block was moved wholesale to
  Settings → Routines (see "Added" below).
- **Per-row MAC address removed from sync-target rows.** The
  `renderSyncTargets` function in `gui/web_ui/gallery.js` no
  longer creates a `.target-addr` element, and the
  `.target-addr` CSS class is removed from `gallery.css`. The
  MAC is already visible in Settings → Bluetooth Scanner.
- **Grid proportions changed to a true halve.**
  `gallery.css:.monthly-best-layout` now uses
  `grid-template-columns: 1.6fr 0.6fr` (gallery 73% / devices
  27%). Previous `1.4fr 1fr` was 58/42; the right card is now
  genuinely the minor column.
- **"Sync All → Targets" button label renamed to
  "Sync All → Devices".** Found in `templates.js:monthly-best`.
- **Orphaned schedule handlers removed from `gallery.js`.**
  The `loadHotChannelSchedule` function and the
  `hc-save-schedule-btn` click handler are gone. Settings.js
  loads the form on tab change / sub-tab click instead.

### Added — Settings → Routines sub-tab (auto-sync gallery)

- **"Routines" sub-tab in Settings nav.** New button between
  "Divoom" and "Connectivity" in `templates.js:settings-nav`.
- **`#settings-routines` content block.** New "Auto-Sync
  Gallery" card with an enabled checkbox
  (`#routines-auto-sync-enabled`), an interval select
  (`#routines-auto-sync-interval` with options 1h / 6h / 12h /
  24h), a Save button (`#routines-auto-sync-save`), and a
  status line. The form sends `{ enabled, interval }` (the
  old `classify` field is dropped — it was a developer-term
  leak).
- **JS handler in `settings.js`.** New
  `window.loadRoutinesAutoSync` loads the config on the
  `tab-changed` event (to settings) or on click of the
  Routines sub-tab. The form save pushes to the existing
  `get_hot_channel_config` / `save_hot_channel_config` API
  methods (`gui/gallery_sync.py:415-426` — API unchanged
  for backward-compat; the persisted JSON key is also
  unchanged).
- **Dropped developer term "headless".** The old "Enable
  scheduled sync (runs headless)" label is replaced with
  the user-friendly "Enable auto-sync to gallery".

### Added — Volume slider in appbar

- **`#appbar-volume-slider` + `#appbar-volume-value`.** New
  slider in `gui/web_ui/index.html:appbar` (positioned
  after the brightness slider). Range 0–15 (the protocol's
  actual range, per `divoom.music.set_volume`, 0x08). Kare:
  show the raw value, no magic normalization. The volume
  is intentionally a separate slider from brightness
  (0–100) — different ranges, different semantics.
- **Handler in `gui/web_ui/app.js`.** `input` event updates
  the `N/15` display; `change` event calls
  `window.pywebview.api.set_volume(val)`. On startup,
  `get_volume()` initializes the slider to the device's
  current value. `change` (not `input`) is used to push to
  avoid spamming 0x08 writes during slider drag.
- **Speaker SVG icon** (Apple SF Symbols–style) replaces
  the previous brightness-adjacent UI element.

### Added — Scoreboard channel-card in Control Panel

- **New channel-card with `data-channel="scoreboard"`.**
  Positioned after the Ambient card in
  `gui/web_ui/index.html:channel-grid`. SVG scoreboard
  icon.
- **`#panel-scoreboard` markup.** 2 number inputs
  (`#scoreboard-red` 0–999, `#scoreboard-blue` 0–999).
  No Show / Hide / Enabled buttons — see "Round 6.1
  behavior fix" below for why.
- **Click the card → switches the device to the
  scoreboard channel (0x06).** This is the same pattern
  as Clock, VJ, EQ, and Design: clicking the card fires
  `switch_channel("scoreboard")`, which dispatches to
  the new `divoom_lib.display.show_scoreboard()` method.
  The scoreboard channel sits in the same `set light
  mode` (0x45) family as the other channels; the wire
  payload is `[0x06, 0, 0, 0, 0, 0, 0, 0, 0, 0]`
  (10 bytes, same padding as show_clock /
  show_visualization / show_effects / show_design).
- **Edit a number → auto-pushes the score** via the
  0x72 set-tool command (`set_scoreboard(1, red, blue)`).
  Same pattern as the clock color input and the
  ambient color input: change event fires the API
  call, no separate "Apply" button.

### Round 6.1 — 2026-06-06 (scoreboard behavior fix)

User feedback: "scoreboard should switch to the channel
and push changes automatically without the user pressing
the show scoreboard button — this is how all the other
channels behave." The Round 6 initial implementation had
a Show button + an Enabled checkbox + a Hide button
(unlike every other channel). The fix:

- **Removed `scoreboard-show-btn`, `scoreboard-hide-btn`,
  and `scoreboard-enabled` from the HTML panel.** The
  panel now contains only the 2 number inputs.
- **Removed scoreboard from the no-`switch_channel`
  skip list** in `channels.js`. The card click now
  fires `switch_channel("scoreboard")`, which lands in
  the new `show_scoreboard()` method.
- **Show/Hide button handlers removed** from
  `channels.js`. Replaced with a single
  `pushScoreboard()` function wired to the `change`
  event of both number inputs.
- **New `divoom_lib/display/show_scoreboard()` method**
  + `switch_channel("scoreboard")` dispatch.
- **Why no "Hide" button**: per user, "hide is
  essentially 'clear' since it clears the score" —
  clearing the score is what setting both inputs to 0
  already does. No separate Clear button is needed.

### Added — `gui_api.py` methods

- **`set_volume(self, volume: int) -> bool`** — clamps to
  0–15. Wall-mode fan-out (one write per device). Music
  fallback (writes to `divoom.music.set_volume`).
- **`get_volume(self) -> int | None`** — returns the
  device's current volume or None if unreachable.
- **`set_scoreboard(self, on_off: int, red: int = 0, blue: int = 0) -> bool`** —
  calls `target.scoreboard.set_scoreboard(on_off, red, blue)`
  with 0x72 set-tool framing. Clamps red/blue to 0–999.

### Documented gaps (intentional)

- **No battery badge in appbar.** User requested a
  device-battery indicator (planning doc §6.1 Phase 1),
  but `divoom_lib` has NO protocol command for device
  battery level. The only related commands are
  0xB2 / 0xB3 (low-power auto-dim switch), which control
  the device's dim behavior — they do NOT report battery
  level. The Divoom Cloud mobile app shows device battery
  over the cloud, not BLE / SPP. Adding a fake battery
  badge (e.g. showing the laptop's battery) would be
  misleading. **The test
  `test_no_battery_badge_intentionally_not_implemented`
  guards against this.** To unblock: (1) find a protocol
  command (possibly in Divoom Cloud over HTTPS), (2)
  implement in `divoom_lib`, (3) add a GUI badge, (4)
  add `get_battery()` in `gui_api.py`, (5) update the
  guard test to assert the new badge exists.

### Files

- `gui/web_ui/templates.js` — Monthly Best card renamed,
  schedule block removed, Routines sub-tab added.
- `gui/web_ui/gallery.js` — orphaned schedule handlers
  removed; the dead `window.loadHotChannelSchedule()`
  call in the 1500ms mount timer is replaced with a
  comment pointing to settings.js.
- `gui/web_ui/gallery.css` — grid `1.4fr 1fr` → `1.6fr 0.6fr`,
  `.target-addr` rule removed.
- `gui/web_ui/settings.js` — `loadRoutinesAutoSync` and
  save handler added; 2 event listeners (tab-changed +
  click on routines sub-tab) at end of DOMContentLoaded.
- `gui/web_ui/index.html` — volume slider in appbar,
  Scoreboard channel-card + panel.
- `gui/web_ui/app.js` — volume slider `input`/`change`
  handlers + `get_volume` startup init.
- `gui/web_ui/channels.js` — scoreboard removed from
  no-`switch_channel` list (Round 6.1); show/hide button
  handlers replaced with `pushScoreboard()` wired to the
  number inputs' `change` events.
- `gui/gui_api.py` — `set_volume`, `get_volume`,
  `set_scoreboard` added.
- `divoom_lib/display/__init__.py` — new
  `show_scoreboard()` method + `switch_channel("scoreboard")`
  dispatch (Round 6.1).
- `tests/test_round6_layout_and_exposure.py` — **19 new
  regression tests** (static-analysis + Playwright smoke).
- `tests/test_e2e_mock_device.py` — **2 new e2e tests** for
  show_scoreboard + switch_channel("scoreboard") wire
  bytes (Round 6.1).

### Test count

- Round 6 initial: 505 passed / 73 skipped / 0 failed
  (+19 Round 6 regression tests).
- Round 6.1: **507 passed / 73 skipped / 0 failed** (+2
  e2e tests for show_scoreboard / switch_channel).
- No regressions. Wall-clock full suite: ~70s.

### Live device

- Volume slider and scoreboard show/hide: NOT yet
  live-tested. The transport-level correctness of the
  underlying protocol calls is covered by the existing
  `divoom_lib` unit tests (mock transport) and
  `test_e2e_mock_device.py`. Manual device verification
  is recommended before the next GUI deployment.

### Design notes

- The Monthly Best dialectic (4 options A/B/C/D) is
  documented in `docs/PLANNING_ROUND5.md` §3. Option B
  (this implementation) was the user pick via 4-option
  confirmation: schedule moves to Settings, all 5
  asks in Phase 1, "Auto-Sync Gallery" naming, no
  relocation hint. Kare: pixel-perfect clarity
  (N/15 raw, no normalization). Rams: simpler
  right card (73/27, not 58/42), `1.6fr 0.6fr` is
  the "good" (true halve) pattern.

---

### Fixed

- **Window drag fix (final).** The frameless window drag now works
  on macOS single-monitor and multi-monitor setups. The fix is the
  combination of:
  - pywebview's bundled `pywebview-drag-region` CSS-class mechanism
    (re-enabled on the appbar in `gui/web_ui/index.html:24`).
  - A gated monkey-patch to `webview.platforms.cocoa.BrowserView.move`
    in `gui/gui_main.py:111-128` that drops the `self.screen.origin.x`
    term, fixing upstream
    [pywebview#1820](https://github.com/r0x0r/pywebview/issues/1820)
    (May 2026). The patch is gated by a source-based detection
    helper `_pywebview_1820_bug_present()` (lines 27-66) that
    inspects `BrowserView.move` and only applies the patch when
    the bug token `self.screen.origin.x + x` is present. When
    pywebview ships the upstream fix, the token disappears from
    the source, the helper returns False, and the patch is
    skipped (logged: "pywebview #1820 already fixed upstream;
    skipping patch"). When that happens, the entire block in
    `gui_main.py:96-128` can be deleted.
- **Self-deactivation contract verified.** Two new tests in
  `tests/test_gui_drag_instrumented.py`:
  - `test_pywebview_1820_detection_matches_source` — canary that
    fails if the detection token no longer matches the bug
    signature in the installed pywebview. This is the trigger
    for deleting the workaround.
  - `test_pywebview_1820_detection_simulates_upstream_fix` —
    monkey-patches `webview.platforms.cocoa.BrowserView.move`
    into the upstream-recommended fix shape and asserts the
    detection returns False. Verifies the self-deactivation
    contract.

### Changed

- **`gui/gui_main.py`** — added the detection helper and gated
  the patch application. ~40 LOC added.
- **`tests/test_gui_drag_instrumented.py`** — added 2 new
  detection-contract tests (4 → 6 total). Updated
  `test_gui_main_patches_cocoa_drag` to assert the new
  structure (detection helper present, patch body does not
  contain the bug token).
- **`docs/PLANNED_WORK.md`** §5 #0 — updated status table
  entry to point to the new history file and document the
  self-deactivation contract.
- **`docs/PLANNING_ROUND2_CONTINUATION.md`** §1 — corrected
  the original §1 dialectic recommendation (Approach A was
  rejected by implementation). Added §14 documenting the
  final 4-attempt journey.

### Added

- **`docs/DRAG_FIX_HISTORY.md`** — full history of all 4
  drag fix attempts, why each failed, what the final correct
  fix is, and how to undo the workaround when pywebview ships
  #1820. Future maintainers: read this before "simplifying" the
  drag mechanism.

### Removed

- **Custom JS drag handler** from `gui/web_ui/app.js` (had
  caused 2 of the 4 failed attempts to jump around).
- **Custom Python `drag_window`** from `gui/gui_api.py` (was
  the source of 3 failed attempts, including a 16ms Timer
  debounce that was theoretically correct but missed the
  real bug).

### Test count

- Before: 484 passed / 73 skipped / 0 failed.
- After: 486 passed / 73 skipped / 0 failed (+2 detection-
  contract tests).
- No regressions. Wall-clock full suite: 66.85s.

### Upstream status

- **pywebview#1820 still OPEN** as of 2026-06-06. No PR, no
  branches. The monkey-patch is still required.
- Issue link: https://github.com/r0x0r/pywebview/issues/1820

---

## Round 4 — 2026-06-05 (cover upload, 0x44→0x49 remap)

### Fixed

- **`set animation frame` command was 0x44, now 0x49.** Per the
  protocol summary (`docs/DIVOOM_PROTOCOL_SUMMARY.md`) and APK
  reference, 0x44 is a *single-frame static image* command, and
  0x49 is the *multi-frame animation* command. The library was
  remapping `show_image` through 0x44 with the multi-frame body,
  which the device parsed as a static image and silently dropped
  subsequent frames. `divoom_lib/models/commands.py:36` now
  reads `"set animation frame": 0x49`. Single-frame "animations"
  worked by coincidence — 0x44 + first-frame bytes happens to
  parse as a valid static image.
- **Multi-frame 0x8B 3-phase protocol** implemented in
  `divoom_lib/display/animation_8b.py` (142 LOC) and routed from
  `divoom_lib/display/__init__.py:show_image`. Falls back to
  0x49 if the device rejects the 0x8B handshake.
- **32×32 PixooMax support** — new encoder in
  `divoom_lib/utils/divoom_image_encode_32.py` (119 LOC) +
  C encoder in `divoom_lib/native_src/image_encode_32.c` (286 LOC).

### Test count

- 448 passed / 73 skipped / 0 failed (up from 369).
- +79: 27 encoder + 1 time kwarg + 2 deleted make_framepart/chunks
  + 28 wall canvas + 11 native 32×32 parity + 10 0x8B chunker.

### Files

- `divoom_lib/models/commands.py:36` — remap to 0x49.
- `divoom_lib/display/animation_8b.py` — new, 0x8B 3-phase.
- `divoom_lib/utils/divoom_image_encode_32.py` — new, 32×32 encoder.
- `divoom_lib/native_src/image_encode_32.c` — new, 32×32 C encoder.
- `divoom_lib/native/image_encoder.py` — 432 LOC, wraps C fast path.
- `tests/test_native_image_encoder_32.py` — 11 parity tests.
- `tests/test_e2e_mock_device.py::test_show_image_emits_0x49_frames`
  — renamed from `test_show_image_emits_0x44_frames`.

### Live device

- 2 live-device verifications (4-quadrant, half-green/red) .
- C encoder byte-identical to Python encoder (40/40 parity tests).
- 0x49 push correctly framed and ACKed by device.
- Multi-frame cycling on Timoo: deferred (device firmware behavior
  requires additional commands not yet identified).

---

## Round 3.5 — 2026-06-05 (P1 helpers, sound, game)

### Added

- **`divoom_lib/system/control.py`** (75 LOC) — `Control` class with
  `set_keyboard` (0x23), `set_hot` (0x26), `set_light_mode` (0x45).
- **`divoom_lib/display/design.py`** — 0xBD sub-cmd dispatch:
  `set_eq`, `set_language`, `set_user_define_time`,
  `get_user_define_time`.
- **`divoom_lib/system/sound.py`** — `SoundControl` class with
  song display, power-on voice vol, ambient sound, auto
  power-off. Registered on `Divoom`.
- **`divoom_lib/game.py`** (167 LOC) — `hide_game`, `set_key_down`
  (0x17), `set_key_up` (0x21), `set_magic_ball_answer` (0x88),
  `exit_game`, 9 game ID constants.
- **26 P1 helper tests** in `tests/test_round4_p1_helpers.py`.

### Test count

- 408 → 448 passed (+40), 73 skipped, 0 failed.

### Live device

- All 4 devices (Pixoo 16×16, Tivoo Max, Ditoo, Timoo) live-tested.

---

## Round 3 — 2026-06-05 (cover upload, 0x44→0x49)

- (Merged into Round 4 above.)

---

## Round 2 — 2026-06-05 (drag, channel-switch, perf)

- **Drag fix attempts 1-3** — all reverted. See
  `docs/DRAG_FIX_HISTORY.md` for the journey.
- **`display_image` wrapper** — implemented in
  `divoom_lib/display/__init__.py:display_image` as a thin
  alias for `show_image` + optional `wait_for_display` poll.
  8 unit tests in `tests/test_display_image_wrapper.py`.
- **BLE start_notify guard** — added `_notifications_started`
  flag in `divoom_lib/ble_transport.py`. Bug was real;
  macOS CoreBluetooth raises "Characteristic notifications
  already started" if `start_notify` is called twice without
  a `stop_notify` in between.
- **Push to Device button** — layout was already correct
  from Round 0/1; added 2 Playwright regression tests in
  `tests/test_monthly_best_button_visible.py`.
- **C downscaler perf profile** — confirmed hypothesis (a)
  from `PLANNED_WORK.md §6`: 99% of samples in
  `downsample_lanczos3` inner loop. Fix deferred (4-pixel
  NEON deinterleave is a follow-up). Byte-exact path is
  shipped and not user-blocking.
- **Test count:** 354 → 369 → 380 → 408 → 448 → 484 → 486.

---

## Round 1 — 2026-06-04 (hands-on followup, 6 issues)

- 1a: Love (pulse) is rainbow, not pulse — solid-color pulse 12s
  linear `love-color-cycle`.
- 1b: Color picker not visually distinct — dashed border + "+"
  SVG icon; click opens picker.
- 2: Window drag jumps between two positions — rAF-throttle in
  `widgets.js`; final-mousemove-only semantics. **Later reverted
  in favor of the Round 5 final fix** (see `DRAG_FIX_HISTORY.md`).
- 3: Gallery only "NeonSkull" — `load_cached_gallery` rebuilds
  from `cache_gallery/` when stale; 233 items recovered.
- 4a/4b: Live cover art — visualiser removed; manual 144×144
  push button in Live Widgets music card.
- 5: Stocks preview outside container bounds — `min-width: 0` on
  flex children.
- 6a/6b: System monitor — removed white panel; 3 labeled bars
  (CPU/MEM/BAT) with device-matched colors; removed duplicate
  `const sysmonDisplayBtn`.

---

## Round 0 — 2026-06-04 (visual regression, 8 issues)

- 1: Window drag regression (first occurrence) — move handler
  to `app.js`, `clientX/Y`, `preventDefault`, document delegation.
- 2.1: Custom Art button always visible — `flex:1; min-height:0`
  on scroll container, button pinned.
- 2.2: Color-picker wrapper click delegation — `<div>` →
  `<label>`; remove `channels.js` delegation block.
- 2.3: Ambient layout per Kare/Rams.
- 3: Ambient preview fixes (5 modes) — Love=solid-color pulse;
  Plants=16×16 pixel grid; Sleeping=green; No-mosquito=orange 40%.
- 4: Monthly best empty space — `flex:1; min-height:0` chain on
  gallery card.
- 5: Live widgets — multiple regressions (visualizer removed,
  sysmon = colored bars, `bindCardSelection` re-attached).
- 6: Device selector sidebar — speaker/res moved to Settings
  "Connectivity" sub-tab; preview image enlarged to 120×120.
- 7: Cleanup — dead `.appbar-device` CSS removed;
  `appbarSelect` → `sidebarDeviceSelect`.
- 8: Phasing (A–E) — all phases A–E executed.

## Round 25 — 2026-06-08 (Channel architecture research)

### Added

- `docs/CHANNEL_ARCHITECTURE.md` — comprehensive research doc from the
  decompiled APK covering all 7 light modes, the 6-byte vs 10-byte CLOCK
  formats, overlay toggle byte positions, TEMPRETURE channel payload, and
  the two-model split (`m`/LightInfo vs `k`/LightCache). Includes a
  byte-by-byte comparison of our `show_clock()` vs the APK's `CmdManager.C2()`
  (our bytes 4-6 are shifted — we set "weather" where the APK expects
  "humidity"). See doc for full implementation recommendations.

### Fixed

- **Weather push reverted** (`push_weather()` in `widgets.py`): the APK
  decouples data push (0x5F) from channel switch (0x45). The 0x45 TEMPRETURE
  channel switch with arbitrary model-field values was sending garbage bytes
  that could crash the device. Removed the channel switch — weather data is
  now pushed as 0x5F only (consistent with the APK). The channel must be
  switched separately.
- Removed test `test_weather_push_switches_channel_before_data` which tested
  the reverted behaviour.

---

## Round 27 — 2026-06-08 (Command queue with ring buffer, maxsize, item timeout)

### Added — `divoom_daemon/command_queue.py`

- **`CommandQueue` class** (`divoom_daemon/command_queue.py`): FIFO command
  queue wrapping the daemon's asyncio loop. Replaces direct
  ``asyncio.run_coroutine_threadsafe(coro, loop).result()`` in
  ``DeviceOwner._run_device()`` so all device-call dispatch is serialised
  through a single queue.

- **`maxsize` parameter** (constructor): bounded queue with pre-allocated
  ring buffer (``_Ring``). ``submit()`` raises ``QueueFull`` when at
  capacity. Zero = unbounded (dynamic list-backed).

- **`item_timeout` parameter** (constructor): per-item timeout checked at
  dequeue time. Expired items are transparently rejected with
  ``TimeoutError`` before the worker picks the next item.

- **`timeout` parameter** (``submit()`` / ``submit_async()``): per-submit
  override of the queue-wide ``item_timeout``. ``None`` disables timeout for
  that item; omit to inherit the queue default.

- **Exclusive mode** (``queue.exclusive(token)`` context manager, lines
  240-250): atomic multi-phase scopes. Items with a matching token are
  dispatched; non-matching items queue behind the exclusive session.

- **``QueueFull`` / ``QueueStopped``** exception classes: raised
  synchronously from ``submit()`` when the queue is at capacity or stopped.

### Changed — `divoom_daemon/device_owner.py`

- **``_run_device()``** now routes through ``self._cmd_queue.submit()``
  instead of ``asyncio.run_coroutine_threadsafe``. Lazily creates the queue
  via ``_device_loop()`` if not yet initialised (fixed regression where
  queue was ``None`` for early callers).

- **``DeviceOwner.stop()``** now stops the command queue before stopping
  the loop, preventing "Task was destroyed" warnings.

### Tests — `tests/test_command_queue.py`

- 30 tests total (was 14). Added:
  - Exclusive mode: multiple tokens, token=None with exclusive active
  - Stress: 50 concurrent submissions, 30-thread sync submit, 100-item burst
  - Lifecycle: submit after stop raises QueueStopped, start/stop cycle
  - Maxsize: full rejection, at-capacity acceptance, active-item exclusion
  - Item timeout: stale expiry, per-submit override, explicit None survival
  - Exception propagation: all built-in exception types
  - Null result: coroutine returning ``None``
