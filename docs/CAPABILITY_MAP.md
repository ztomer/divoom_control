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
| `get_credentials` | `scripts/verify_gallery_render.py:39` | `stale-instrument` | P3.1 |

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
| `_resolve_location(...)` | `api/widgets.py:42`, `media_sync.py:299` | `duplicate` | P2.1 |
| `saved_location()` | `weather_city.py:82` | `client-local` | — |
| `hotchannel_config.*` | `gallery_hot_api.py:74`, `gallery_sync.py` ×7 | `shared-state` | P2.4 |
| `media_decoder.*` | `scripts/verify_gallery_render.py` ×4 | `stale-instrument` | P3.1 |

**`_resolve_location` is F4, and it is PRIVATE.** Two GUI sites call an
underscore-prefixed function of the module the docs call reference-only, and
`api/widgets.py:24` documents the resulting double-fetch: the GUI resolves the
location, then the daemon fetches it again.

**`saved_location` is client-local and stays.** Which city the user picked is
the client's own preference; the daemon is told the answer, it does not need to
own the question.

**`hotchannel.json` has TWO parsers, and that is the finding.**
`divoomd/src/monthly_best.rs:36` reads it in Rust; the GUI reads and WRITES it
through `divoom_lib` in Python. Neither is wrong on its own — this is shared
state with two independent implementations, which is the drift shape. It is not
a straight "move it" like the rows above, so it gets its own verdict and its own
step.

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

## Known blind spots — what this census does NOT see

Stated so that a clean run is never mistaken for a closed class. These are the
audit's F5, F6 and F7, and none of them has the shape the census detects:

* **F5 — `control_server.py`.** A reflection-dispatch HTTP server inside the GUI
  process (`socket` + `socketserver` + `http.server`), exposing every public
  bridge method alongside the daemon socket and `divoomd mcp`. That is an
  ownership question about a whole surface, not a call into `divoom_lib`.
* **F6 — the notification stack.** `divoom_client/macos_notifications.py` (404
  lines) + `notification_router.py` (177) against `macos_notifications.rs` (361).
  Host-data access through `divoom_client`, not `divoom_lib`, so no rule here
  matches it.
* **F7 — the doctrine.** "`divoom_lib` is reference-only" is false: 35 runtime
  import statements across 13 files. That is a claim in prose, which no AST scan
  can check.

**P5.1 turns this file into a gate**, once every row has a verdict that is not
`unknown` and the `duplicate` rows are gone. Until then the census exits 0: it
is an inventory, and reporting it as a gate before the map is complete would
make the first honest run a red build.
