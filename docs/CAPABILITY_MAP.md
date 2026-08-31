# Capability map — who owns what (R72 P0.3)

**The invariant.** `divoomd` owns every RESOURCE: device I/O (BLE/SPP/LAN),
cloud HTTP and credentials, host data (the notification database, now-playing,
system stats, the wall clock), rendering to device frames, and the persistence
of device-facing state. Clients own presentation, user intent, and their own
local preferences. **Each capability has exactly one implementation, and it
lives where its resource lives.**

**How this file is produced.** The rows come from `tools/capability_census.py`,
which joins two machine-generated halves — every match arm in the daemon's
socket dispatch and `device_call` modules (443 command names, read out of the
Rust), against an AST walk of the whole shipped Python surface
(`divoom_gui` + `divoom_client` + `scripts`). Regenerate with:

    python3 tools/capability_census.py

Do not hand-edit the SITE column. Two previous passes at this class used
hand-written lists and both missed things; the point of the census is that it
finds rows nobody thought of, and it did — see "What the census found that the
audit did not" below.

## Verdict vocabulary

| Verdict | Meaning |
|---------|---------|
| `duplicate` | Python does a job the daemon owns. Move it; delete the Python. |
| `presentation` | Client-side rendering of data the daemon produced. Correct as-is. |
| `client-local` | Genuinely the client's own state (a user preference it alone reads). |
| `shared-state` | One file, two independent parsers. Drift risk, not a straight duplicate. |
| `stale-instrument` | A dev tool that verifies a path the product no longer takes. |
| `unknown` | Not yet decided. **Must be zero before R72 closes.** |

`unreviewed` is not in this vocabulary, deliberately. R71 spent a phase
retiring that word from `check_gui_api_reachable.py`'s allowlist after 20
entries sat behind it for a round; re-borrowing it here would recreate exactly
what that phase removed.

## DIRECT — Python calling a daemon capability through `divoom_lib`

| Capability | Site | Verdict | Closed by |
|---|---|---|---|
| ~~`get_cached_credentials`~~ | `divoom_gui/gui_api.py:59` | **CLOSED** — read moved to `load_config`, via the daemon | P1.1 |
| ~~`get_credentials`~~ | `presets_manager.py:59` | **CLOSED** — absorbed into the daemon's `save_credentials` | P1.1 |
| ~~`get_credentials`~~ | `presets_manager.py:61` | **CLOSED** — same | P1.1 |
| ~~`get_credentials`~~ | `scripts/verify_gallery_render.py` | **CLOSED** — rewritten against the daemon (P3.1) | P3.1 |

**F1 in full.** The daemon has complete auth in `cloud.rs` — `login_email`,
`login_guest`, md5 + hmac-md5, a credential cache with cooldown — and answers
`get_credentials`, `get_cached_credentials` and `save_credentials` over the
socket. `divoom_client/daemon_cloud.py:172` ALREADY wraps the cached read. The
GUI sites take the Python path anyway, which is R70's defect in its exact
original shape: seam present, panel bypasses it.

**Careful in P1.1 — and it is worse than the first draft of this note said.**
`gui_api.py:59` is deliberately CACHE-ONLY so a status poll never blocks on a
cloud login, and the daemon wrapper preserves that (`get_cached_credentials` is
the read that cannot go to the network). But the routing has a SECOND hazard the
verdict alone does not show: `self._client()` calls `ensure_daemon()`, which
**spawns the daemon**, and nothing spawns it during `DivoomGuiAPI()`
construction today. Routing the startup read through it would put a daemon spawn
inside GUI construction — the same startup path that produced v0.28.1's
daemon-killing crash.

So this site is not a straight substitution. Either the read becomes LAZY (first
use, not `__init__`), or it uses an accessor that returns an already-running
client and `None` otherwise. Attempted and reverted once already; do not
re-attempt it as a one-line swap. (R71 P1.5 removed one of these sites for free
by deleting the dead `get_transport_status`.)

## WRAPPED — a daemon capability reimplemented over `divoom_lib`

| Capability | Site | Verdict | Closed by |
|---|---|---|---|
| ~~`sync_time`~~ | `api/tools.py:156` | **CLOSED** — daemon `system.set_date_time`, calendar values passed explicitly | P1.2 |
| ~~`set_auto_power_off`~~ | `api/tools.py:174` | **CLOSED** — daemon `device.set_auto_power_off` | P1.3 |
| ~~`set_low_power`~~ | `api/tools.py:178` | **CLOSED** — daemon `device.set_low_power` | P1.3 |
| ~~`save_credentials`~~ | `presets_manager.py:28` | **CLOSED** — one call to the daemon; both hard-won rules moved into `cloud_store::save_config` | P1.1 |

**F2 is a duplicate that is also a defect.** `divoom_lib/system/date_time.py:36`
records it in its own comment: the Python path raised `AttributeError`,
"swallowed by the GUI tool wrapper into a silent False, so Sync Time never
worked". The daemon implements `sync_time` correctly. **Verify on hardware
before and after** (R71's P2 packet): a feature that returned `False` for months
while its caller reported success is exactly the case where "it now returns
True" proves nothing.

**`save_credentials` also writes the account password in PLAINTEXT** to
`config.ini`. That is out of R72's scope and tracked separately, but P1.1 should
not move this site without noticing it — the daemon-side store is the natural
place to fix it.

## REACHES — a call into an owned module, name not a command

Lower confidence by construction, and listed separately for that reason: a call
into an owned module might be a pure helper. It is a read-and-decide list, not
an accusation. It exists because the two categories above match on NAME, and the
invariant is about the WORK.

| What | Sites | Verdict | Closed by |
|---|---|---|---|
| ~~`DateTimeCommand(...)`~~ | `api/tools.py:158` | **CLOSED** with P1.2 | P1.2 |
| ~~`DeviceSettings(...)`~~ | `api/tools.py:176`, `:180` | **CLOSED** with P1.3 | P1.3 |
| `resolve_location(...)` | `api/widgets.py:42`, `media_sync.py:299` | **`client-local`** (verdict CORRECTED) | P2.1 |
| `saved_location()` | `weather_city.py:82` | `client-local` | — |
| `hotchannel_config.*` | `gallery_hot_api.py:74`, `gallery_sync.py` ×7 | `shared-state` | P2.4 |
| ~~`media_decoder.*`~~ | `scripts/verify_gallery_render.py` ×4 | **CLOSED** with P3.1 | P3.1 |

**F4's verdict was WRONG, and the correction matters more than the row.**

This file said `duplicate`, and cited `api/widgets.py:24` as documenting a
double-fetch. Reading that docstring instead of trusting the citation: it
documents the double-fetch being **FIXED**, by R67/C2, which moved the weather
fetch to the daemon. I cited a fix as evidence of the defect it repaired.

And `resolve_location` is not a duplicate of anything. It is PURE -- env vars
and a saved preference, no network. The IP geolocation people assume is here
happens on wttr.in's side, inside the DAEMON's request, when it returns "".
Deciding which city the user means is client-local, the same verdict
`saved_location` already has one row down.

What WAS real: both GUI sites imported it while it was underscore-prefixed,
reaching into the private surface of a module the docs call reference-only.
Made public in P2.1. The row stays in REACHES because the census flags any call
into an owned module and `weather_provider` still contains the (reference-only)
fetch path -- which is honest: the row is a read-and-decide entry that has now
been read and decided.

**`saved_location` is client-local and stays.** Which city the user picked is
the client's own preference; the daemon is told the answer, it does not need to
own the question.

**`hotchannel.json` has TWO parsers — GATED (P2.4), not removed.**
`divoomd/src/monthly_best.rs:36` reads it in Rust; the GUI reads and WRITES it
through `divoom_lib` in Python. Unlike every other row here, this one cannot be
fixed by deleting a duplicate: **both readers are load-bearing.** The GUI owns
the settings UI and the daemon needs the values to run auto-sync.

They AGREE today — diffed 2026-08-31, identical fields, defaults (interval 3600,
classify 18) and clamping (60s to 30 days). So it gets the treatment R67/C2 gave
weather: `tools/check_hotchannel_parity.py`, added while the two still match,
which is the only time a parity gate is cheap to add.

What drift would cost is concrete. `hotchannel_config.py`'s comment on
MIN_INTERVAL says "the daemon will read-back the clamped value" — true only
while the clamps agree. Hand-edit the file to `interval: 1` with divergent
clamps and the GUI displays a safe 60 while the daemon hammers the cloud once a
second: a disagreement whose only symptom is invisible on the screen that is
supposed to report it.

## What the census found that the audit did not

The round's hand-written findings table had seven entries. The census reproduces
them and adds rows nobody had listed, which is the whole reason both halves are
machine-generated:

* **`scripts/` was never scanned before.** R70's gate is scoped to
  `divoom_gui/`, so `verify_gallery_render.py` had never been looked at by any
  gate in this repo.
* **`verify_gallery_render.py` is a STALE INSTRUMENT, which is worse than a
  duplicate.** Its docstring says it "mirrors the exact decode chain the GUI
  uses" and that "media_decoder is the single source of truth that feeds the
  UI". Both were true when it was written and neither is now: **R70 P2.2 moved
  gallery decode into the daemon**, precisely because the daemon could decode
  magic 9/18/26/0xAA containers the GUI could not. So this harness verifies a
  path the product no longer takes, and a green run from it says nothing about
  what a user sees. Re-point it at the daemon's decoder or retire it — but do
  not leave a harness whose passing result is meaningless.
* **`hotchannel.json`'s second parser**, above.
* **`save_credentials`**, which the audit missed while listing the three read
  sites.

## The Rust menubar (P3.3) — clean, and structurally so

Audited against the same invariant. `divoom-menubar/src/daemon.rs` is a lean
NDJSON socket client, and the audit's strongest result is not a reading of the
code but of the **dependency list**: `tray-icon`, `tao`, `serde_json` and one
CFRunLoop binding. No transport, device, HTTP, database or image crate. It
*cannot* duplicate a daemon job, whatever anyone writes in it later.

One thing it reads for itself: `[gui] keep_daemon_alive` from `config.ini`,
hand-parsed. That makes **three** independent parsers of that file — the GUI's
`configparser`, the daemon's hand-rolled `[divoom]` reader, and this. They read
different sections so they do not fight over values, but they could disagree
about what counts as TRUE, and the consequence is concrete: the GUI decides
whether to leave the daemon running on exit and the menubar decides whether to
kill it. `tests/test_keep_daemon_alive_parity.py` pins the agreement, written
while the two still match.

## Known blind spots — what this census does NOT see

Stated so that a clean run is never mistaken for a closed class. These are the
audit's F5, F6 and F7, and none of them has the shape the census detects:

* **F5 — `control_server.py`. RESOLVED (P3.2): a test harness, and it now says
  so and authenticates.**

  The audit called it "a third control surface". It is not always-on: it starts
  only when `DIVOOM_CONTROL_SERVER=1` or `DIVOOM_CONTROL_SOCKET` is set, and
  `gui_main.py:166` already labels it "Optional headless control server surface
  (E2E testing)". Nothing in production enables it; the only non-test caller is
  `scripts/validate_devices.py`, which already handles a token. **Verdict: it
  stays, as declared test tooling.**

  **What was actually wrong was the auth.** `_authorized()` returned True when
  no token was set, so a tokenless TCP surface reflection-dispatched the whole
  GUI API — device control, credential reads, file dialogs — to any local
  process under any user on the machine. Loopback is not an authorisation
  boundary. `serve()` now REFUSES to start without a token.

  The Unix-socket variant stays tokenless and that exemption is EARNED, not
  assumed: it chmods the socket to 0600 explicitly rather than relying on the
  caller's umask. Filesystem permissions are a real boundary where "it is only
  localhost" is not.
* **F6 — the notification stack. INVESTIGATED (P2.3); the split is now
  evidence-backed, and the deletion is the remaining work.**

  `divoom_client/macos_notifications.py` divides cleanly in two, and only one
  half is a duplicate:

  | Half | What | Verdict |
  |---|---|---|
  | `find_notification_db_path`, `load_routing_table`, `ROUTING_PATH` | the GUI shows the user which DB was found and which rules apply | `presentation` — keep |
  | `MacNotificationMonitor` (~250 lines) + `parse_notification_record` | polls the Notification Center SQLite DB on a thread | `duplicate` — delete |

  **The polling half has NO production caller.** `MacNotificationMonitor` is
  instantiated only in tests; the GUI asks the daemon
  (`client.stop_notifications()`, `gui_api.py:289`), and
  `test_gui_api_notifications.py:76` asserts outright that the GUI must not
  start one because "that is the daemon's job". So this is not a live second
  implementation — it is ~250 lines of dead polling machinery shipped inside
  the client package, against a working `macos_notifications.rs`.

  **DELETED (P2.3).** `macos_notifications.py` went 404 -> 112 lines. The
  polling half, the record parser, the CLI and the orphaned test-support module
  are gone; the presentation helpers stayed. The GUI's guard test changed from
  "this code path did not build a monitor" to "there is nothing to build",
  which no future code path can violate.

  It also stays outside the census's reach by construction: it is
  `divoom_client`, not `divoom_lib`, so no rule here matches it. That is the
  blind spot, not an oversight.
* **F7 — the doctrine.** "`divoom_lib` is reference-only" is false: 35 runtime
  import statements across 13 files. That is a claim in prose, which no AST scan
  can check.

**P5.1 turns this file into a gate**, once every row has a verdict that is not
`unknown` and the `duplicate` rows are gone. Until then the census exits 0: it
is an inventory, and reporting it as a gate before the map is complete would
make the first honest run a red build.
