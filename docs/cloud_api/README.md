# Divoom Cloud HTTP API — reference catalog

Full research sweep of `com.divoom.Divoom.http.HttpCommand` (533 command
constants total, `app.divoom-gz.com` / `appin.divoom-gz.com`), built
2026-07-14 after the user provided the decompiled APK
(`references/apk/decompiled_src/` — gitignored, absolute path only, see
`docs/ROADMAP.md`'s "Divoom Cloud HTTP" section for the unblocking story).

**Why this exists**: `docs/ROADMAP.md` flagged ~225+ endpoints as "we don't
know the shapes" — the APK removed that blocker. This catalog documents every
command's purpose, request/response field shape (from the decompiled
`http/request/**`/`http/response/**` classes), relevance to this project, and
source confidence, so future feature work doesn't need to re-derive any of
this from scratch. It does **not** mean all 533 should be implemented —
most are Divoom's own account/social/moderation layer, irrelevant to a
third-party BLE device controller. Treat this as a lookup table, not a to-do
list.

## How to read a batch file

Each file has one table (Command | Purpose | Request fields | Response
fields | Relevance | Confidence) plus an `## Unknown / no signal` section.

- **Relevance**: `device-control` (a real third-party device-integration
  feature — this project's actual candidate list), `account/social` (Divoom's
  own login/profile/social layer), `internal/moderation` (admin/test-only).
- **Confidence**: `decompiled` (request/response class with real field names
  found, and/or a live caller), `name-only` (command declared, purpose
  inferable from naming/siblings, but no confirmed class/caller), `unknown`
  (no signal beyond the bare string — see `UNKNOWN_COMMANDS.md`).

## Batch files (by domain)

| File | Domain(s) | Commands | Notes |
|---|---|---|---|
| [channel_a.md](channel_a.md) | `Channel/*` (A–G) | 50 | `Channel/DeviceGetMyClock` is a BLE push, not HTTP; `Channel/GetAll` has classes but no live caller (dead) |
| [channel_b.md](channel_b.md) | `Channel/*` (G–U) | 50 | Includes `StoreClockGetClassify`/`StoreClockGetList` — documented per the known RC=12 issue, superseded by the shipped `Channel/GetDialType`+`GetDialList` |
| [device.md](device.md) | `Device/*` | 40 | Several (`Connect`, `Disconnect`, `Hearbeat`, …) are server→app MQTT push *tags*, not client-sent requests |
| [user.md](user.md) | `User/*`, `App/*`, `HuaWei/Token` | 35 | `User/NewGuest` + `APP/GetServerUTC` already shipped (`divoom_lib/divoom_auth.py`) |
| [draw.md](draw.md) | `Draw/*`, `Led/*`, `Lyric/*`, `Mixer/*` | 32 | `NeedEqData`/`NeedLocalData` are a device-side packet-loss retransmit protocol — useful context for the WiFi pixel-sync reliability layer |
| [manager.md](manager.md) | `Manager/*`, `Discount/*`, `Medal/*`, `Shop/*` | 28 | 100% internal moderation / e-commerce / gamification — zero device-control relevance |
| [cloud.md](cloud.md) | `Cloud/*`, `CloudPhoto/*`, `Community/*`, `Ali/*` | 25 | **`Cloud/ToDevice` flagged**: real request class (`Classify`/`GalleryId`/`Type`) but no confirmed live caller in this APK build — semantics unconfirmed, worth a closer look if "push gallery art via cloud" is ever wanted |
| [photo_discover.md](photo_discover.md) | `Photo/*`, `PhotoFrame/*`, `Discover/*` | 26 | `Photo/*` (photo-frame album CRUD + slideshow) is a real, mostly-untapped `device-control` feature; `Photo/Enter` is actually sent over BLE SPP, not HTTP |
| [sys_tools_tag.md](sys_tools_tag.md) | `Sys/*`, `Tools/*`, `Tag/*`, `Test/SetUrl`, `Log/SendLog`, `Hot/GetHotFiles32` | 32 | `Sys/TimeZoneSearch` does server-side geocoding BLE can't do; most `Sys/Set*`/`Tools/*` duplicate existing BLE features |
| [tomato_sleep_alarm.md](tomato_sleep_alarm.md) | `Tomato/*`, `Sleep/*`, `AidSleep/*`, `WhiteNoise/*`, `Alarm/*` | 37 | **`AidSleep/GetAllList` + `AidSleep/Play` flagged as a viable new feature** — browse a cloud-hosted sleep-sound/white-noise/music library (HTTP, auth-gated) then play by `SleepId` over BLE (no cloud auth needed for playback itself) — same shape as the shipped clock-face browser |
| [playlist_voice_timeplan.md](playlist_voice_timeplan.md) | `Playlist/*`, `Voice/*`, `Lottery/*`, `Memorial/*`, `TimePlan/*` | 38 | **`Playlist/SendDevice` + browse commands flagged as a viable new feature** — browse a cloud-hosted image/animation playlist and push it to the device (confirmed live caller, `PlayListModel.b()`) |
| [message_forum.md](message_forum.md) | `Message/*`, `MessageGroup/*`, `Forum/*`, `Comment/GetCommentListV3` | 25 | 100% Divoom's own social messaging/forum layer (RongCloud-backed) — zero device-control relevance |
| [vision_danmaku_game.md](vision_danmaku_game.md) | `Vision/*`, `Danmaku/*`, `Game/*` | 21 | `Danmaku/*` is a real scrolling bullet-chat/face overlay feature, distinct from the `Voice`/`Led` text-push commands; `Vision/*` is a per-device clock-gallery photo slot manager, not AI/computer-vision |
| [misc_small.md](misc_small.md) | `Google/Outlook` calendar, `Weather/*`, `Radio/*`, `QingTing/*`, `BlueDevice/*`, `Dialog/*`, `NoDevice/*`, `PowerOn/*`, `Mall/*`, `AI/*`, `FillGame/FinishGameV2` | 31 | **`BlueDevice/NewDevice` turned out to be the fix for `AidSleep/GetAllList`'s RC=3 mystery** (see `tomato_sleep_alarm.md` + `docs/ROADMAP.md`) — registers a real server-side `BluetoothDeviceId`, the missing precondition for device-scoped cloud calls. Everything else is Divoom's own account/social/e-commerce layer, or a different product family (WiFi speakers' internet radio/scheduled power-on — not the BLE Pixoo/Tivoo/Ditoo/Timoo displays this project targets) |
| [toplevel_a.md](toplevel_a.md) | top-level (no domain prefix), A–G | 32 | `GetCategoryFileListV2` already shipped (`divoom_lib/cloud.py`); `GetCategoryFileList`/`GalleryUpload`/`GalleryUploadV2` are legacy/dead duplicates |
| [toplevel_b.md](toplevel_b.md) | top-level (no domain prefix), G–U | 31 | `UserLogin` already shipped (`divoom_lib/divoom_auth.py`) |

**Total documented: 533 of 533 commands.** All 16 research batches complete.

## The real findings: candidate new features

Three leads came out of this sweep that look like genuinely viable,
bounded, well-shaped features — analogous in shape to the clock-face browser
already shipped in v0.22.13 (public/simple list → pick an id → apply):

1. **AidSleep browse + play** (`tomato_sleep_alarm.md`) — browse Divoom's
   cloud-hosted sleep-sound/white-noise/music library, then play a track by
   `SleepId` over BLE. **Shipped 2026-07-14** (Schedule panel's "Sleep
   Sounds" sub-tab) — the RC=3 blocker was `AidSleep/GetAllList` needing a
   real server-registered device (fixed via `BlueDevice/NewDevice`, found
   in `misc_small.md`).
2. **Playlist browse + push** (`playlist_voice_timeplan.md`) — browse a
   user's cloud-hosted image/animation playlists and push one to the device
   via `Playlist/SendDevice` (confirmed live in the decompiled app).
   **Shipped 2026-07-14** (Pixel Art panel's "Playlists" sub-tab).
3. **`Cloud/ToDevice`** (`cloud.md`) — possibly "push a gallery item to a
   device via the cloud", but unconfirmed (no live caller found) — needs
   more investigation before treating it as real. Not implemented.

See `docs/ROADMAP.md`'s "Divoom Cloud HTTP" section for the full status and
history of each lead.

## Unknown commands

See [UNKNOWN_COMMANDS.md](UNKNOWN_COMMANDS.md) — 8 of 502 documented
commands (so far) have zero signal beyond the bare `HttpCommand.java`
string constant (no request/response class, no live caller, no public
documentation). That's a small fraction — the decompiled APK resolved the
overwhelming majority of Divoom's cloud API even where no public
documentation exists at all.
