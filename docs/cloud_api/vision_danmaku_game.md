# Vision/Danmaku/Game API

Source: JADX-decompiled Divoom Android app, `references/apk/decompiled_src/sources/com/divoom/Divoom/`
(gitignored). Master list `http/HttpCommand.java`; shapes in `http/request/**`, `http/response/**`;
callers grepped from `view/fragment/**/model/*.java`.

**Vision** turns out to be genuinely device-linked: `Vision/*` manages a per-device "photo → live
photo/video vision" gallery attached to a specific clock (`ClockId`) — browsing a store of vision
items (`Vision/GetList`), the user's own added items (`Vision/MyList`), adding/removing an item to a
device's slot (`Vision/Add` / `Vision/Remove`), picking its cover image, per-item display duration,
and a scheduled display-time window (start/end/weekday/voice-enable), shared with the generic
`ChannelSet*Time`-style time-window plumbing (`WifiChannelCustomTimeItem`/`WifiChannelTimeItemResponse`)
used elsewhere for subscribe/EQ/custom galleries. `Vision/GetClassify` reuses the **My Clock** store's
classify-category response class verbatim, confirming Vision items are just another
"clock/gallery classify browsing" surface, not a separate AI subsystem.

**Danmaku** ("bullet chat") is a real device text/face-overlay feature — a scrolling-text or emoji-face
banner shown on the pixel screen. The plain (`Danmaku/SendText`, `Danmaku/GetConfig`, `Danmaku/SetConfig`)
commands are posted over the WiFi/cloud HTTP path, while the `Blue`-suffixed siblings
(`Danmaku/SendBlueText`, `Danmaku/SetBlueConfig`, `Danmaku/GetBlueConfig`) are the same feature routed
over direct Bluetooth (`q.s().B(request)` — the app's BLE command queue) for BLE-only devices. This
overlaps in spirit but not in wire shape with the `Voice/SendText`/LED-marquee text-push features
documented in `draw.md` — Danmaku is its own scrolling-overlay mode (`DisplayArea`, `Speed`,
`Background`, `Color`, `TextSize` config knobs) rather than the same command reused. `HttpCommand.java`'s
`DeviceAndServerCmd` array explicitly lists `Danmaku/SendText` and `Danmaku/RandomFace` as
device-and-server dual-path commands, corroborating that Danmaku is device control, not a social feature.

**Game** (`Game/Enter`, `Game/Exit`, `Game/Play`) is a remote-control channel for the device's
built-in arcade/game mode: on WiFi-architecture devices the app posts these over **MQTT**
(`BaseParams.postMqtt(...)`), on BLE-architecture devices it sends the BLE equivalent directly
(`CmdManager.o2(...)`/`CmdManager.v1()`). It is a live remote-control signal (enter/exit game mode,
send a "play" input tick) rather than session/score tracking — score tracking for the *fill-in*
minigame variant lives in the separate `FillGame/*` namespace (`FillGameSetScoreRequest`,
`FillGameFinishRequest`), which is out of scope for this batch.

Two web searches (`divoom Vision API AI pixel art`, `divoom Danmaku bullet chat API`) turned up no
public documentation for either namespace — only the generic Divoom pixel-art app/community pages
and the unrelated W3C Danmaku web-API proposal. `doc.divoom-gz.com` (the public Pixoo LAN API docs)
does not cover this cloud namespace either, confirming this batch is reverse-engineering-only.

| Command | Purpose | Request fields | Response fields | Relevance | Confidence |
|---|---|---|---|---|---|
| `Vision/Add` | Add a vision-store item to a device's vision slot; on BLE-linked devices also pushes the item (video/small-image file ids) directly to the device over Bluetooth. | `VisionId` (int), `ImageSmallFileId` (string), `VideoFileId` (string) (`VisionAddRequest`) | Base result only (`BaseResponseJson`) | device-control | decompiled |
| `Vision/GetClassify` | Fetch the vision store's browsable category list (reuses the My-Clock-store classify response shape). | Paging only (`BaseLoadMoreRequest`) | `ClassifyList[]` (`MyClockStoreClockGetClassifyListItem`) (`MyClockStoreClockGetClassifyResponse`) | device-control | decompiled |
| `Vision/GetDisplayTime` | Fetch the scheduled display-time window (start/end/weekday/voice-enable) configured for a device's vision slot. | `ClockId` (int) (`BaseChannelRequest`) | `StartTime`, `EndTime`, `IsEnable`, `VoiceEnable` (int), `WeekArray` (List\<Integer\>) (`WifiChannelTimeItemResponse`, shared with `ChannelGetSubscribeTime`/`ChannelGetEqTime`/`ChannelGetAlbumTime`) | device-control | decompiled |
| `Vision/GetList` | Browse the vision item store (paginated), each item flagged whether it's already added to the current device. | Paging only (`BaseLoadMoreRequest`) | `VisionList[]`: `VisionId` (int), `ImageFileId`, `ImageSmallFileId`, `VideoFileId` (string), `AddFlag` (int) (`VisionMyListResponse`/`VisionItem`) | device-control | decompiled |
| `Vision/GetOneDuration` | Fetch the per-item display duration (seconds) configured for a device's vision slot. | `ClockId` (int) (`BaseChannelRequest`) | `OneDuration` (int) (`VisionGetOneDurationResponse`) | device-control | decompiled |
| `Vision/MyList` | List the vision items the user has already added (paginated) — same response shape/adapter as `GetList`, distinguished by command string at the UI layer. | Paging only (`BaseLoadMoreRequest`) | Same as `Vision/GetList` (`VisionMyListResponse`/`VisionItem`) | device-control | decompiled |
| `Vision/Remove` | Remove a vision item from the user's added list / device slot. | `VisionId` (int) (`VisionRemoveRequest`) | Base result only (`BaseResponseJson`, response class reused loosely as `MyClockStoreClockGetClassifyResponse` at the call site, but no fields read) | device-control | decompiled |
| `Vision/SetCover` | Set the cover/thumbnail image for a device's vision clock face. | `ClockId` (int), `CoverFileId` (string) (`VisionSetCoverRequest`) | Base result only (`BaseResponseJson`) | device-control | decompiled |
| `Vision/SetDisplayTime` | Set the scheduled display-time window for a device's vision slot (start/end/weekday/voice-enable), via the shared `WifiChannelModel` time-window UI (same widget used for subscribe/EQ/custom-gallery time windows). | `StartTime`, `EndTime`, `IsEnable`, `VoiceEnable` (int), `WeekArray` (List\<Integer\>), plus `ClockId` (int, carried by the shared model call) (`WifiChannelCustomTimeItem`) | Base result only (inferred) | device-control | decompiled |
| `Vision/SetOneDuration` | Set the per-item display duration (seconds) for a device's vision slot. | `OneDuration` (int), `ClockId` (int, inherited from `BaseChannelRequest`) (`VisionSetOneDurationRequest`) | Base result only (`MyClockStoreClockGetClassifyResponse` reused loosely, no fields read) | device-control | decompiled |
| `Danmaku/GetBlueConfig` | Fetch the current bullet-chat overlay config for a BLE-linked device. | Empty (`new BaseRequestJson()`) | `Background` (int), `Color` (string, default `#FFFFFF`), `Speed` (int), `TextSize` (int) (`DanmakuGetBlueConfigResponse`) | device-control | decompiled |
| `Danmaku/GetConfig` | Fetch the current bullet-chat overlay config for a WiFi-linked device. | Empty (`new BaseRequestJson()`) | `DisplayArea` (int), `Speed` (int) (`DanmakuGetConfigResponse`) | device-control | decompiled |
| `Danmaku/RandomFace` | Request/display a random emoji "face" in the bullet-chat overlay. Request class exists (`DanmakuRandomFaceRequest`, no fields beyond base) and the command is declared as a device-and-server dual-path command in `HttpCommand.DeviceAndServerCmd`, but no instantiation/call site was found anywhere in the decompiled sources — appears unused/dead in this app build. | Empty (`DanmakuRandomFaceRequest`, no extra fields) | unknown (no call site to confirm response class) | device-control | decompiled |
| `Danmaku/SendBlueText` | Push scrolling bullet-chat text directly to a BLE-linked device over Bluetooth (`q.s().B(request)`), bypassing the normal HTTP POST path. | `Text` (string) (`DanmakuSendTextRequest`, `TextColor` left unset on this path) | n/a (BLE push, no HTTP reply) | device-control | decompiled |
| `Danmaku/SendFace` | Send a specific emoji "face" (by index) to the bullet-chat overlay. | `Index` (int) (`DanmakuSendFaceRequest`) | Base result only (`DanmakuGetConfigResponse` reused loosely, no fields read) | device-control | decompiled |
| `Danmaku/SendText` | Push scrolling bullet-chat text to a WiFi-linked device via the normal HTTP/cloud path. | `Text`, `TextColor` (string) (`DanmakuSendTextRequest`) | Base result only (`DanmakuGetConfigResponse` reused loosely, no fields read) | device-control | decompiled |
| `Danmaku/SetBlueConfig` | Set the bullet-chat overlay config (background, color, speed, text size) for a BLE-linked device; also re-pushed directly over Bluetooth after the HTTP ack when the device is BLE-connected. | `Background` (int), `Color` (string), `Speed` (int), `TextSize` (int) (`DanmakuSetBlueConfigRequest`) | Base result only (`BaseResponseJson`) | device-control | decompiled |
| `Danmaku/SetConfig` | Set the bullet-chat overlay config (display area, speed) for a WiFi-linked device. | `DisplayArea` (int), `Speed` (int) (`DanmakuSetConfigRequest`) | Base result only (`BaseResponseJson`) | device-control | decompiled |
| `Game/Enter` | Enter the device's built-in arcade/game mode for a given game id — sent over MQTT on WiFi-architecture devices, or as a direct BLE command (`CmdManager.o2(true, gameId)`) on BLE-architecture devices. | `GameId` (int) (`GameEnterRequest`) | n/a (MQTT push / BLE command, no typed HTTP reply read) | device-control | decompiled |
| `Game/Exit` | Exit the device's game mode — MQTT on WiFi devices, or direct BLE (`CmdManager.o2(false, 0)`) otherwise. | Empty (`GameExitRequest`) | n/a (MQTT push / BLE command) | device-control | decompiled |
| `Game/Play` | Send a "play" input/tick to the device's active game — MQTT on WiFi devices, or direct BLE (`CmdManager.v1()`) otherwise. | Empty (`GamePlayRequest`) | n/a (MQTT push / BLE command) | device-control | decompiled |

## Unknown / no signal

None — every command in this batch had at least a declared request/response class and a real
caller in `view/fragment/**` or `**/model/*.java` (`Danmaku/RandomFace` has a request class and is
listed in the `DeviceAndServerCmd` dual-path array, but its call site could not be located, so its
response shape is unconfirmed — see table row above).
