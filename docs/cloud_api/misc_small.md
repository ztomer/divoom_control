# Misc small domains: AI, BlueDevice, Dialog, FillGame, Mall, NoDevice, PowerOn, QingTing, Radio, Weather, Google/Outlook calendar

Source: decompiled Divoom Android APK (JADX), `references/apk/decompiled_src/sources/com/divoom/Divoom/`
(master catalog `http/HttpCommand.java`; shapes from `http/request/**` and `http/response/**`;
callers grepped across `view/fragment/**` and `bean/**`).

This is the 16th and final research batch — everything below plus the other 15 batch files
covers all 533 `HttpCommand.java` command constants.

## The one real finding: `BlueDevice/NewDevice`

Not originally flagged as a candidate feature, but turned out to be the fix for the
`AidSleep/GetAllList` RC=3 mystery documented in `tomato_sleep_alarm.md` and
`docs/ROADMAP.md`: every device-scoped cloud call needs a `BluetoothDeviceId` the server
actually issued via `BlueDevice/NewDevice`, not a client-side placeholder. This project's
`_load_virtual_device()`/`load_virtual_device()` never got a real one because nothing called
this registration endpoint — see `divoom_auth.ensure_virtual_device` /
`divoomd::cloud::ensure_virtual_device` (implemented 2026-07-14) for the fix. Everything
else in this batch is Divoom's own app/account/social/e-commerce layer or a different
product family (WiFi speakers, not the BLE Pixoo/Tivoo/Ditoo/Timoo pixel displays this
project targets) — no other new device-control leads.

| Command | Purpose | Request fields | Response fields | Relevance | Confidence |
|---|---|---|---|---|---|
| `AI/UploadPicV2` | Upload a generated AI pixel-art image (multipart file + the original prompt request) to the user's personal AI-image library, returning a storable `AIFileId`. Fired automatically after a ComfyUI-backed text/image-to-pixel-art generation completes (`ai.divoom-gz.com/ai/text2image/generate` or `/ai/image2image/generate` — a SEPARATE, non-`HttpCommand`-catalog AI backend host; not decompilable from this catalog alone). | `AiPromptRequest` fields (`Text`, `Size`, `Weight`, `Seed`, `Fast`, `AiEncryption`, `JetBraking`) + the uploaded PNG bytes | `AIFileId` (`AiUploadResponse`) | account/social | decompiled |
| `AI/GetPicListV2` | Paginated list of the user's saved AI-generated pixel-art images (`AiPixelItem`: `AiId`/`AIFileId` + the original prompt fields). | `BaseLoadMoreRequest` paging only | `AiPixelItem[]`: `AiId`, `AIFileId`, `Text`, `Size`, `Weight`, `Seed`, `Fast` | account/social | decompiled |
| `AI/DeletePicture` | Delete one saved AI-generated image by id. | `AiId` | `BaseResponseJson` | account/social | decompiled |
| `BlueDevice/NewDevice` | **Register a new virtual Bluetooth device identity with the server** — `APP/GetServerUTC` for a signed timestamp, then this call with `UTC`/`UTCEncrypt` (HMAC-MD5, same scheme as guest login) + `Type`/`SubType`, returns a real `BluetoothDeviceId`/`DevicePassword`. Confirmed live 2026-07-14: this is the missing precondition for `AidSleep/GetAllList`'s RC=3 (see above). | `UTC`, `UTCEncrypt`, `Type`, `SubType` (`BlueDeviceNewDeviceRequest`) | `BluetoothDeviceId`, `DevicePassword` (`BlueDeviceNewDeviceResponse`) | **device-control — flag: this project's fix for AidSleep** | decompiled |
| `BlueDevice/PasswordError` | Fire-and-forget notification (no response handling) that a device's Bluetooth password was rejected — a diagnostic/telemetry ping, not a real request/response round-trip. | (bare `BaseRequestJson`, no extra fields) | n/a | internal/moderation | decompiled |
| `Dialog/GetInfo` | Login-flow batch fetch of app-startup popups: announcement image/link, app-update version/description, discount banner image, lottery count, and newly-earned medals. 100% app-marketing, fired once per login (`AnnounceChain`/`AppUpdateChain`/`MedalGetNewChain`/`DiscountChain` in `view/fragment/eventChain/loginChain/`). | `AnnLastIndex`, `isAndroid`, `Language`, `RegionId` | `AnnImageId`, `AnnLinkUrl`, `AnnLastIndex`, `AppDescribe`, `AppVersion`, `DiscountImageId`, `LotteryCnt`, `LotteryImageFileId`, `MedalList[]` | account/social | decompiled |
| `Dialog/GetMatchInfo` | Fetch one promo/matched-content image by index (paired with `GetInfo`'s dialog chain). | `CountryISOCode`, `Index`, `Language` | `ImageFileId`, `Index` | account/social | decompiled |
| `FillGame/FinishGameV2` | Report a completed "fill the pixel puzzle" mini-game score against a gallery image id. Distinct from `Manager/SetFillGameScore` (already documented in `manager.md`) — this is the player-facing finish call, that one is an admin/moderation score-set. | `FillGameScore`, `GalleryId` | `BaseResponseJson` | internal/moderation (in-app gamification) | decompiled |
| `Mall/GetListV2` | Fetch the points-redemption shop catalog (Divoom's own merchandise/e-commerce mall). | `Langue` | `GetMallResponse` (item list; not walked further — pure e-commerce) | account/social | decompiled |
| `Mall/Buy` | Redeem a mall item with a shipping address (name/phone/address/country/province/email/remark). | `MallId`, `Name`, `Phone`, `Address1`, `Address2`, `Country`, `Province`, `Email`, `Remark` | `BaseResponseJson` | account/social | decompiled |
| `NoDevice/GetDialogInfo` | Ad content shown to users with no Divoom device paired yet (onboarding upsell). | (no request class found beyond bare command) | `AdList[]`: `AdvertName`, `ImageId`, `LinkUrl` | account/social | decompiled |
| `NoDevice/GetGalleryAdvert` | Similar no-device-paired advertisement fetch, gallery-flavored variant; no distinct request/response class found beyond the shared `ad` package infrastructure `NoDeviceGetDialogInfo` uses. | unknown | unknown | account/social (inferred from sibling) | name-only |
| `PowerOn/GetList` | Fetch the cloud-synced scheduled power-on/off timer list for **WiFi speaker products** (`WifiPowerModel`/`WifiPowerMainFragment` — a different Divoom product line from the BLE Pixoo/Tivoo/Ditoo/Timoo displays this project targets, same caveat as `Sleep/*`). | (paginated, `BaseLoadMoreRequest`-style) | `PowerOnList[]`: `PowerOnId`, `Time`, `RepeatArray`, `EnableFlag`, `PowerOnFlag` | device-control (wrong product family) | decompiled |
| `PowerOn/Set` | Create/update a scheduled power-on/off timer for a WiFi speaker. | Same shape as `PowerOnListItem` (see `GetList`) | `BaseResponseJson` | device-control (wrong product family) | decompiled |
| `QingTing/GetFavorites` | Favorited internet-radio stations from QingTing FM (a Chinese streaming-radio service), for **WiFi speaker products** with internet radio — not the BLE pixel displays' built-in FM tuner (that's the existing `set_radio_frequency` BLE feature, frequency-based, unrelated). | unknown (no dedicated request class found; likely bare) | `QtRadio`/`QtChannel`/`QtRadioCategoriesBean` shapes (station/category metadata) | device-control (wrong product family) | name-only |
| `QingTing/SetFavorite` | Add/remove a QingTing station favorite. | unknown (no dedicated request class found) | `BaseResponseJson` (inferred) | device-control (wrong product family) | name-only |
| `Radio/GetFavorites` | Favorited **internet** radio stations (Shoutcast-style `StationId`/`StationName`/`StationLogo` — WiFi speaker streaming, not the BLE devices' frequency-tuned FM). | (bare `BaseRequestJson`) | `FavoriteList[]` (`Favorite`: station id/name/logo) | device-control (wrong product family) | decompiled |
| `Radio/GetHistories` | Recently-played internet radio station history. | (bare `BaseRequestJson`) | `HistoryList[]` (`Favorite` shape) | device-control (wrong product family) | decompiled |
| `Radio/SetFavorite` | Add/remove an internet radio station favorite. | `StationId`, `StationName`, `StationLogo`, `IsFavorite` | `BaseResponseJson` | device-control (wrong product family) | decompiled |
| `Radio/SetHistory` | Record/remove a station in play history. | `StationId`, `StationName`, `StationLogo`, `IsAdd` | `BaseResponseJson` | device-control (wrong product family) | decompiled |
| `Weather/SearchCity` | **Already shipped** in this project (`divoom_lib/cloud.py`'s `search_weather_city`) — search for a city by name to get its `CityId`/`Lat`/`Lon` for weather display. | `CityName` + `StartNum`/`EndNum` paging | `CityList[]`: `CityId`, `CityName`, `Country`, `Lat`, `Lon` | device-control (shipped) | decompiled |
| `Weather/Send5Days` | Declared in `HttpCommand.java` only — no request/response class, no caller found anywhere in `view/fragment/**`. Purpose inferred purely from the name (a 5-day forecast push, likely server→device MQTT rather than a real client-initiated HTTP call, similar to other `Send*` tag-only commands documented in `device.md`). | unknown | unknown | device-control (guess) | name-only |
| `Weather/SendCurrent` | Same situation as `Send5Days` — constant-only, no decompiled shape, no caller. | unknown | unknown | device-control (guess) | name-only |
| `Google/GetCalendarConfig` | Fetch whether the user's Google account is linked (`Logined`) and their event/popup notification toggles. | (bare `BaseRequestJson`) | `Logined`, `EventNotice`, `PopUpNotice` | account/social | decompiled |
| `Google/SetCalendarConfig` | Update the event/popup notification toggles for the linked Google Calendar. | `EventNotice`, `PopUpNotice` | `BaseResponseJson` | account/social | decompiled |
| `Google/EnterCalendar` | **In `HttpCommand.DeviceAndServerCmd`** — routes to the connected device's local LAN HTTP API instead of cloud when on the same network (`BaseParams.postSync`'s routing, same mechanism `Playlist/SendDevice` uses). Posts a bare `BaseRequestJson` (no extra fields) — likely a "push the calendar view to the currently-connected device now" trigger, but with zero decompiled payload beyond auth the exact on-device effect isn't confirmable from source alone. | (bare `BaseRequestJson`) | `BaseResponseJson` | **device-control — thin signal**: real caller confirmed, but no fields to build against; not enough to implement blind | decompiled |
| `Google/CalendarLogOut` | Unlink the Google Calendar OAuth connection. | (bare `BaseRequestJson`) | `BaseResponseJson` | account/social | decompiled |
| `Outlook/GetCalendarConfig` | Outlook mirror of `Google/GetCalendarConfig` — same three fields. | (bare `BaseRequestJson`) | `Logined`, `EventNotice`, `PopUpNotice` (`OutlookGetCalendarConfigResponse`) | account/social | decompiled |
| `Outlook/SetCalendarConfig` | Outlook mirror of `Google/SetCalendarConfig`. | `EventNotice`, `PopUpNotice` | `BaseResponseJson` | account/social | decompiled |
| `Outlook/EnterCalendar` | **In `HttpCommand.DeviceAndServerCmd`**, same LAN-routing + thin-payload situation as `Google/EnterCalendar`. | (bare `BaseRequestJson`) | `BaseResponseJson` | **device-control — thin signal** | decompiled |
| `Outlook/CalendarLogOut` | Outlook mirror of `Google/CalendarLogOut`. | (bare `BaseRequestJson`) | `BaseResponseJson` | account/social | decompiled |

## Unknown / no signal

- `NoDevice/GetGalleryAdvert` — inferred from its sibling `NoDevice/GetDialogInfo`'s shared
  `ad` package, but no distinct request/response class or caller found.
- `QingTing/GetFavorites` / `QingTing/SetFavorite` — the `bean/qingting/*` data shapes exist
  (`QtRadio`, `QtChannel`, `QtRadioCategoriesBean`) but no `HttpCommand`-catalog request class
  or caller specifically for these two command strings was found; purpose inferred from the
  sibling `Radio/*` favorites API and the QingTing bean package's existence.
- `Weather/Send5Days` / `Weather/SendCurrent` — constant-only in `HttpCommand.java`, zero
  decompiled shape or caller.
