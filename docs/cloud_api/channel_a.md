# Channel API — batch A

Source: decompiled Divoom Android APK (JADX), `references/apk/decompiled_src/sources/com/divoom/Divoom/`
(master catalog `http/HttpCommand.java`; shapes from `http/request/channel/**` and
`http/request/channel/wifi/**` / `http/response/channel/**`, `http/response/system/**`; callers
grepped across `view/fragment/channelWifi/**`, `view/fragment/myClock/**`,
`view/fragment/more/lightsettingWifi/**`, `http/mqtt/MqttService.java`, `bluetooth/f.java`).

This batch covers 50 `Channel/*` commands. Most request classes extend
`http/request/channel/wifi/BaseChannelRequest`, which carries a standard set of inherited fields
(`ClockId`, `PageIndex`, `ParentClockId`, `ParentItemId`, `LcdIndependence`, `LcdIndex`, `Language`)
on top of whatever fields the row lists — noted as "(+ base)" below. A number of `Get*` commands use
a completely generic request (`BaseRequestJson`, no extra fields, or `BaseChannelRequest` with no
override) — the cloud presumably keys the response off the session's `Token`/`UserId`/`DeviceId`
alone. Several `Get*` responses are also pushed unsolicited over **MQTT** to WiFi-connected devices
(`http/mqtt/MqttService.java`), reusing the same response shape as the HTTP round-trip — noted per row.

One command, `Channel/DeviceGetMyClock`, is not an HTTP round-trip at all: it's the JSON envelope
used to push the user's cloud "My Clock" list down to the physical device (`bluetooth/q#B(...)`),
right after `Channel/MyClockGetList` returns from the cloud.

A public (unofficial) third-party doc site, [divoom.2a03.party/api/app.html](https://divoom.2a03.party/api/app.html)
(REvoom Team), documents the **Pixoo64 local LAN device API** — a different API surface (talks
directly to the device's own HTTP server, no `Token`/`UserId`) that happens to reuse some of the
same command-name strings (`Channel/GetAll`, `Channel/GetConfig`, `Channel/GetSongInfo` all appear
there, listed as "undocumented" with no parameters given). That is **not** confirmation of the
`app.divoom-gz.com` cloud shapes documented below — it's a naming coincidence between two unrelated
Divoom protocols, flagged per-row where it applies. Web search (`divoom Channel API GetClockList`,
`divoom cloud API app.divoom-gz.com reverse engineered github r12f divoom`) turned up no public
documentation of the cloud `app.divoom-gz.com` Channel/* endpoints themselves — r12f/divoom and
similar community projects target the Pixoo64 local LAN API, not this cloud API.

| Command | Purpose | Request fields | Response fields | Relevance | Confidence |
|---|---|---|---|---|---|
| `Channel/Add5LcdHistory` | Record that a clock face was set on a 5-LCD ("Times Gate" multi-panel) device, adding it to play history. | `ClockId` (+ base) | `BaseResponseJson` (no extra fields) | device-control | decompiled |
| `Channel/AddEqData` | Upload/add a custom EQ (music-visualizer) background image, with author metadata, for a clock. | `AuthorHeadId`, `AuthorId`, `AuthorNickName`, `FileId`, `ImageName` (+ base) | `BaseResponseJson` | device-control | decompiled |
| `Channel/AddHistory` | Record that a clock face was set as active, adding it to play history (non-5LCD counterpart of `Add5LcdHistory`). | `ClockId` (+ base) | `BaseResponseJson` | device-control | decompiled |
| `Channel/AddIndependence` | Add a new independent LCD zone (5-LCD split-panel device) and return its new zone index. | none (`BaseRequestJson`) | `LcdIndependence` | device-control | decompiled |
| `Channel/CleanCustom` | Clear/remove all items on a given custom (DIY) gallery page. | `CustomPageIndex` (+ base) | `BaseResponseJson` (assumed generic; no dedicated response class found) | device-control | decompiled |
| `Channel/ClockCommentLike` | Like/unlike a user comment left on a clock face in the community store. | `CommentId`, `IsLike` | `BaseResponseJson` | account/social | decompiled |
| `Channel/CoverPixelClock` | Set/upload a custom cover thumbnail (pixel-art file) for a clock face. | `ClockId`, `CoverPixelFileId` | `BaseResponseJson` (assumed) | device-control | decompiled |
| `Channel/CustomChange` | No caller and no request/response class found. By naming position among `GetCustomList`/`SetCustom`/`DeleteCustom`/`CleanCustom`, likely reorders or moves an item on a custom (DIY) gallery page. | unknown | unknown | device-control (inferred) | name-only |
| `Channel/DelHistory` | No caller and no request/response class found. By naming position next to `AddHistory`/`Add5LcdHistory`, likely removes an entry from clock play history. | unknown | unknown | device-control (inferred) | name-only |
| `Channel/DelIndependence` | Delete an independent LCD zone (5-LCD split-panel device) by index. | `LcdIndependence` | `BaseResponseJson` | device-control | decompiled |
| `Channel/DeleteCustom` | Delete one image/item from a custom (DIY) gallery page. | `CustomId`, `CustomPageIndex` (+ base) | `BaseResponseJson` (assumed) | device-control | decompiled |
| `Channel/DeleteEq` | Delete one EQ (music-visualizer) background image entry by position. Reuses the `Set`-side request class (`WifiChannelSetEqPositionRequest`) with the command field overridden. | `EqPosition` (+ base) | `BaseResponseJson` | device-control | decompiled |
| `Channel/DeletePixelClock` | Delete a custom pixel-art clock/dial the user created. | `ClockId` (+ base, via bare `BaseChannelRequest`) | `BaseResponseJson` | device-control | decompiled |
| `Channel/DeviceGetMyClock` | Not an HTTP call: push the user's full "My Clock" id list down to the physical device over BLE/MQTT (`bluetooth.q#B`), immediately after `Channel/MyClockGetList` returns from the cloud. | `ClockList` (`List<Integer>`) | n/a (outbound device push, no HTTP response) | device-control | decompiled |
| `Channel/EqDataChange` | No caller and no request/response class found. By naming position next to `AddEqData`/`DeleteEq`/`GetEqDataList`, likely reorders/updates the EQ visualizer image list. | unknown | unknown | device-control (inferred) | name-only |
| `Channel/ExitNightPreview` | Exit/cancel the temporary "night mode" brightness preview shown while adjusting night-light settings. | none (`BaseRequestJson`) | `BaseResponseJson` (assumed) | device-control | decompiled |
| `Channel/Get5LcdClockList` | Fetch the clock-face catalog for 5-LCD ("Times Gate" multi-panel) devices, grouped by category. | none beyond base (`BaseChannelRequest`) | `GroupList[]` (`GroupListItem`) | device-control | decompiled |
| `Channel/Get5LcdClockListV2` | V2 of the above: same response shape, adds a `Flag` filter to the request. | `Flag` (+ base) | `GroupList[]` (`GroupListItem`, same `WifiGet5LcdClockListResponse` as V1) | device-control | decompiled |
| `Channel/Get5LcdInfo` | No live caller found (only the V2 variant is invoked); presumed legacy predecessor of `Get5LcdInfoV2` — fetch current 5-LCD split-zone configuration. | unknown | unknown | device-control (inferred) | name-only |
| `Channel/Get5LcdInfoV2` | Fetch the current 5-LCD device's split-panel (independent zone) configuration and which clock/channel is on each zone. | none beyond base (`BaseChannelRequest`) | `ChannelType`, `ClockId`, `LcdIndependence`, `LcdIndependenceList[]` | device-control | decompiled |
| `Channel/GetAlbumTime` | Get the scheduled active-time window (start/end, enabled days) for the photo album/gallery channel display. | none beyond base (`BaseChannelRequest`) | `EndTime`, `IsEnable`, `StartTime`, `VoiceEnable`, `WeekArray` (`WifiChannelTimeItemResponse`) | device-control | decompiled |
| `Channel/GetAll` | Fetch the full list of channel "scenes" (named channel groupings), each with `ChannelId`/`ChannelName` entries — a channel picker/reorder shape. No live caller found in this app version (dead/legacy code path, request+response classes still present). Note: `Channel/GetAll` also appears (unrelated) in the Pixoo64 local-LAN API docs, not confirmation of this cloud shape. | none (`BaseRequestJson`) | `SceneList[]`: `SceneName`, `ChannelList[]`: `ChannelId`, `ChannelName` | device-control | decompiled |
| `Channel/GetAllCustomTime` | Get the scheduled display-time windows for all custom (DIY) gallery pages at once. | none beyond base (`BaseChannelRequest`) | `TimeList[]` (`WifiChannelCustomTimeItem`) | device-control | decompiled |
| `Channel/GetAmbientLight` | Get the ambient/RGB light-strip settings (brightness, color, cycling effect). Also delivered unsolicited over MQTT. | none (`BaseRequestJson`) | `Brightness`, `ColorCycle`, `EqOnOff`, `SelectEffect`, `color` | device-control | decompiled |
| `Channel/GetClockCommentList` | Fetch paginated user comments left on a specific clock face in the community store. | `ClockId`, `EndNum`, `Language`, `MessageId`, `StartNum`, `Type` | `CommentList[]`, `CommentListNum`, `CurListNum` (`GetCommentListV3Response`) | account/social | decompiled |
| `Channel/GetClockConfig` | Fetch a clock face's editable configuration (description text, like state/count, configurable sub-item lists) for its detail/settings screen. | `ClockId`, `Language` (+ base) | `AlbumShapePicId`, `ClockExPlain`, `ClockExPlainPicId`, `IsMyLike`, `ItemList[]`, `ItemList2[]`, `LikeCnt` | device-control | decompiled |
| `Channel/GetClockFont` | Fetch the list of selectable clock-face fonts and the currently selected font id. | generic list-pagination request via the base list fragment (`BaseLoadMoreRequest`-style; no dedicated request class) | `FontId`, `FontList[]` (`WifiChannelClockFontItem`) | device-control | decompiled |
| `Channel/GetClockInfo` | Get the currently displayed clock's basic runtime info (brightness, active clock id / LCD index, creation time). Also delivered over MQTT. | none beyond base (`BaseChannelRequest`) | `Brightness`, `ClockId`, `LcdIndex`, `ProduceTime` | device-control | decompiled |
| `Channel/GetClockList` | Fetch the main browsable catalog of clock faces/dials (grouped categories) for the channel/clock store. | `CountryISOCode`, `Flag`, `Version` (+ base) | `HistoryFlag`, `GroupList[]` | device-control | decompiled |
| `Channel/GetClockStyle` | Fetch selectable visual style variants for a given clock face, plus the currently applied style. | `ClockId` (+ `BaseLoadMoreRequest` paging) | `CurStyleId`, `CurStylePixelImageId`, `StyleList[]` (`WifiChannelClockStyleItem`) | device-control | decompiled |
| `Channel/GetConfig` | Fetch the device's overall channel display configuration (active channel index, clock/gallery timing, rotation, startup clock). Note: `Channel/GetConfig` also appears (unrelated) in the Pixoo64 local-LAN API docs, not confirmation of this cloud shape. | none beyond base (`BaseChannelRequest`) | `ChannelIndex`, `ClockTime`, `GalleryShowTimeFlag`, `GalleryTime`, `Language`, `RotationFlag`, `SingleGalleyTime`, `StartUpClockId`, `StartUpClockImageFileId`, `StartUpClockOnOff` | device-control | decompiled |
| `Channel/GetCustomGalleryTime` | Get the per-image display-duration/sound settings for one custom (DIY) gallery item. | `CustomId` (+ base) | `GalleryShowTimeFlag`, `SingleGalleyTime`, `SoundOnOff` | device-control | decompiled |
| `Channel/GetCustomList` | Fetch the list of images/items on a given custom (DIY) gallery page. | `CustomPageIndex` (+ base) | `CustomList[]` (`CustomListItem`) | device-control | decompiled |
| `Channel/GetCustomPageIndex` | Get the currently active custom (DIY) gallery page index shown on the device. | none found beyond base (called with no extra fields) | `CustomPageIndex` | device-control | decompiled |
| `Channel/GetElementStyleList` | Fetch selectable clock-face element styles (e.g. date/round widget styles) filtered by item type. | `ItemType` (+ `BaseLoadMoreRequest` paging) | `GroupList[]` (`ElementStyleGroupListItem`) | device-control | decompiled |
| `Channel/GetEqDataList` | Fetch the list of custom EQ (music-visualizer) background images available for a clock. | none beyond base (`BaseChannelRequest`) | `EqDataList[]` (`EqDataListItem`) | device-control | decompiled |
| `Channel/GetEqPosition` | Get which EQ visualizer background image position/index is currently selected for a clock. Also delivered over MQTT. | none beyond base (`BaseChannelRequest`) | `EqPosition` | device-control | decompiled |
| `Channel/GetEqTime` | Get the scheduled active-time window for the EQ (music visualizer) channel display. | none beyond base (`BaseChannelRequest`) | `EndTime`, `IsEnable`, `StartTime`, `VoiceEnable`, `WeekArray` (`WifiChannelTimeItemResponse`) | device-control | decompiled |
| `Channel/GetIndependenceConfig` | Get the schedule/voice settings for one independent LCD zone (5-LCD split-panel device). | `LcdIndependence` | `EndTime`, `IsEnable`, `StartTime`, `VoiceEnable`, `WeekArray` | device-control | decompiled |
| `Channel/GetIndex` | Get the index of the currently selected clock/channel slot within the current channel/category. | none found (generic) | `SelectIndex` | device-control | decompiled |
| `Channel/GetNightView` | Get the device's scheduled "night mode" dimming settings (brightness + on/off time window). | none (`BaseRequestJson`) | `Brightness`, `EndTime`, `OnOff`, `StartTime` | device-control | decompiled |
| `Channel/GetNotifyList` | Get the list of phone-notification types (and their on/off state) the device is configured to show. | none (`BaseRequestJson`) | `NotifyList[]`: `NotifyId`, `NotifyName`, `NotifyOnOff` | device-control | decompiled |
| `Channel/GetOnOff` | Get the device's scheduled screen/system on-off timer settings. | none (`BaseRequestJson`) | `EndTime`, `OnOff`, `StartTime` | device-control | decompiled |
| `Channel/GetOnOffScreen` | Get the device's current screen on/off state. Also delivered over MQTT (separate `http/response/system` class, same `OnOff` shape). | none (`BaseRequestJson`) | `OnOff` | device-control | decompiled |
| `Channel/GetOneCustom` | Fetch details (image file id) of a single item on a custom (DIY) gallery page. | `CustomId`, `CustomPageIndex` (+ base) | `CustomId`, `CustomPageIndex`, `FileId` | device-control | decompiled |
| `Channel/GetRGBInfo` | Get the RGB ambient light-strip/key-light configuration (brightness, color, cycle mode, per-light list). Also delivered over MQTT. | none (`BaseRequestJson`) | `Brightness`, `Color`, `ColorCycle`, `KeyOnOff`, `LightList[]`, `OnOff`, `SelectLightIndex` | device-control | decompiled |
| `Channel/GetSongInfo` | Now-playing song info for a music/EQ visualizer clock face, delivered as an MQTT push to the device. Note: `Channel/GetSongInfo` also appears (unrelated) in the Pixoo64 local-LAN API docs, not confirmation of this cloud shape. | none (`BaseRequestJson`) | `songInfo` (String) | device-control | decompiled |
| `Channel/GetStartupChannel` (field `ChannelGetStartup`) | Get which channel index the device should show on startup/boot. Response class found; no live HTTP caller confirmed in this app version (its `Set` counterpart, `Channel/SetStartupChannel`, is actively called). | unknown (no dedicated request class found) | `ChannelIndex` | device-control | decompiled |
| `Channel/GetSubClockList` | Fetch a filtered sub-list of clock faces by clock type (e.g. picking a sub-clock for a split panel). | `ClockType` (+ `BaseLoadMoreRequest` paging) | `ClockList[]` (`ClockListItem`, shared `MyClockStoreClockGetListResponse`) | device-control | decompiled |
| `Channel/GetSubscribe` | Get the currently subscribed content (a followed user's shared photo album/playlist) that the device channel is displaying. Hybrid: the underlying mechanism is following another user, but the effect is device channel content. | `Language` (+ base) | `AlbumId`, `AlbumName`, `AuthorType`, `PlayId`, `PlayName`, `SubscribeType`, `UserList[]` | device-control | decompiled |

## Unknown / no signal

None. Every command in this batch resolved to at least a purpose inference from the decompiled
source (either a real request/response class, a live caller, or an unambiguous naming position next
to sibling commands that do have classes/callers). The `name-only` rows above
(`Channel/CustomChange`, `Channel/DelHistory`, `Channel/EqDataChange`, `Channel/Get5LcdInfo`) have no
dedicated request/response class and no live caller, but their purpose is inferable with reasonable
confidence from their position in a clear command family (e.g. `Add5LcdHistory`/`AddHistory` implies
`DelHistory` removes a history entry) — they are listed as `name-only`, not `unknown`.
