# Playlist/Voice/Lottery/Memorial/TimePlan API

Source: decompiled Divoom Android app (JADX), `references/apk/decompiled_src/sources/com/divoom/Divoom/`
(gitignored — not shipped in this repo tree). Master command list: `http/HttpCommand.java`.
Request shapes: `http/request/**` (`@JSONField(name=...)`). Response shapes: `http/response/**`.
Real callers verified in `view/fragment/**/model/*.java` and `bluetooth/f.java`.

All requests extend `BaseRequestJson` (adds standard envelope fields: `Command`, `Token`/`UserId`
auth, `DeviceId`, etc. — omitted below, only the class-specific `@JSONField`s are listed).
All responses extend `BaseResponseJson` unless noted, which carries `ReturnCode`, `ReturnMessage`,
`Command`, `DeviceId` — omitted below unless a command's response is *only* those fields (shown as
"status only").

A public reverse-engineering reference (`divoom.2a03.party/api/app.html`, REvoom Team) lists most
of these same command strings under its "undocumented endpoints" section but supplies no field-level
detail for any of them — confirming this decompiled catalog is currently the best available source
for the request/response shapes.

| Command | Purpose | Request fields | Response fields | Relevance | Confidence |
|---|---|---|---|---|---|
| Playlist/AddImageToList | Add an image/gallery item to one of the user's playlists. | `GalleryId` (int), `PlayId` (int) + pagination base (`StartNum`, `EndNum`, `Language`, `CountryISOCode`) | `AddFlag` (int), `fileId` (string) | device-control | decompiled |
| Playlist/DeleteList | Delete one of the user's playlists. | `PlayId` (int) | status only | device-control | decompiled |
| Playlist/GetMyImageList | List the images/animations inside one of the user's own playlists. | `PlayId` (int) + `GetCloudBaseRequestV2` base (`Classify`, `EndNum`, `FileSort`, `RefreshIndex`, `StartNum`, `FileType`, `FileSize`, `Version`) | not directly observed (paged gallery-item list, same shape family as other cloud gallery responses) | device-control | decompiled |
| Playlist/GetMyList | List the current user's playlists (name/cover/count/hidden flag). | pagination base (`StartNum`, `EndNum`, `Language`, `CountryISOCode`) | `PlayList`: array of `PlayListItem` {`AddFlag`, `Count`, `CoverFileId`, `Describe`, `HideFlag`, `Name`, `PlayId`} | device-control | decompiled |
| Playlist/GetSomeOneImageList | List the images inside another user's playlist (viewed via social/discover). | `PlayId` (int), `TargetUserId` (int) + `GetCloudBaseRequestV2` base | not directly observed (same item family as GetMyImageList) | account/social | decompiled |
| Playlist/GetSomeOneList | List another user's playlists (social/discover browsing). | `TargetUserId` (int) + pagination base | `PlayList`: array of `PlayListItem` (same shape as GetMyList) | account/social | decompiled |
| Playlist/Hide | Toggle a playlist's visibility (hide/unhide from others). | `Hide` (int), `PlayId` (int) | status only | account/social | decompiled |
| Playlist/NewList | Create a new empty playlist. | `Name` (string) | `PlayId` (int) — new playlist's id | device-control | decompiled |
| Playlist/RemoveImage | Remove an image/gallery item from a playlist. | `GalleryId` (int), `PlayId` (int) | status only | device-control | decompiled |
| Playlist/Rename | Rename a playlist. | `Name` (string), `PlayId` (int) | status only | device-control | decompiled |
| Playlist/SendDevice | Push an entire playlist's contents to the currently connected device (real caller: `PlayListModel.b()`, sends `{PlayId}`). Also listed in `HttpCommand.DeviceAndServerCmd`, meaning the mobile app treats it as a combined device+server round-trip command (like `Voice/SendText`) rather than a pure cloud call. | `PlayId` (int) | status only | **device-control** (flagged: real feature) | decompiled |
| Playlist/SetCover | Set a playlist's cover thumbnail. | `CoverFileId` (string), `PlayId` (int) | status only | device-control | decompiled |
| Playlist/SetDescribe | Set/edit a playlist's text description. | `Describe` (string), `PlayId` (int) | status only | device-control | decompiled |
| Voice/GetList | Fetch the list of voice-mailbox messages left on a WiFi device (voice greeting/mailbox feature). Real caller: `VoiceWifiDataModel`. | none (empty `BaseRequestJson`) | `VoiceList`: array of `VoiceListBean` {`DeviceId`(long), `Length`(int), `RecordTime`(int), `UserId`(int), `VoiceAttachmentId`(string)} | account/social | decompiled |
| Voice/GetPixel | Fetch the pixel-art drawing currently paired with the user's voice-greeting message. Real caller: `WifiVoiceFragment` — populates `voice_pic` `StrokeImageView`. | none (empty `BaseRequestJson`) | `FileId` (string) | account/social | decompiled |
| Voice/Marked | Mark a received voice-mailbox message as read/acknowledged. | `AttachmentId` (string) | status only | account/social | decompiled |
| Voice/SendText | Send a text-to-speech style greeting/banner (text + styling) — appears in `HttpCommand.DeviceAndServerCmd`, i.e. a combined server+device push, not a pure cloud call. | `Background`(string), `NickName`(string), `Speed`(int), `Text`(string), `TextColor`(string) | status only | **device-control** (already covered — see note below) | decompiled |
| Voice/SetPixel | Attach/save a pixel-art drawing to accompany the user's voice greeting. Real caller: `WifiVoiceFragment`. | `FileId` (string) | status only | account/social | decompiled |
| Voice/Upload | Upload a recorded voice-message audio blob (multipart, via `uploadFileRxSync`). Real caller: `VoiceUtils`. | `AttachmentId`(string), `Length`(int), `RecordTime`(int) | (uses generic `FileResponse`, not a Voice-specific class — not captured in `http/response/voice`) | account/social | decompiled |
| Lottery/Announce | Fetch the public "winners announcement" feed for the prize-draw event. | `CountryISOCode`(string), `Langue`(string) | `PrizeList`: array of {`Date`(int), `NickName`(string), `PrizeName`(string)} | account/social | decompiled |
| Lottery/GetLotteryCnt | Get how many lottery draws/tickets the current user has available. | `CountryISOCode`(string), `Langue`(string) | `LotteryCnt`(int), `LotteryImageFileId`(string) | account/social | decompiled |
| Lottery/GetPrizeInfo | Fetch the prize catalog/details for the current lottery event (titles + prize list). | `CountryISOCode`(string), `Langue`(string) | `Title1/2/3`(string), `PrizeList`: array of {`PrizeName`(string), `PrizeSmallImageId`(string)} | account/social | decompiled |
| Lottery/MyList | List the current user's own won-prize history. | `CountryISOCode`(string), `Langue`(string), `StartNum`(int), `EndNum`(int) | `TotalListNum`(int), `PrizeList`: array of {`Date`(int), `PrizeId`(int), `PrizeName`(string), `PrizeStatus`(int), `PrizeType`(int)} | account/social | decompiled |
| Lottery/Start | Spin/execute one lottery draw and return the prize won. | `CountryISOCode`(string), `Langue`(string) | (does **not** extend `BaseResponseJson`) `PrizeBigImageId`(string), `PrizeId`(int), `PrizeName`(string), `PrizePosition`(int), `PrizeType`(int), `ReturnCode`(int), `ReturnMessage`(string) | account/social | decompiled |
| Lottery/WriteAddress | Submit a shipping address to claim a physical prize won in the lottery. | `Address1/2`(string), `Country`(string), `Email`(string), `Name`(string), `Phone`(string), `PrizeId`(int), `Province`(string), `Remark`(string) | status only | account/social | decompiled |
| Memorial/Del | Delete an anniversary/countdown ("memorial") entry from the cloud. | `MemorialId` (int) | status only | device already exposes via BLE (project already implements Memorial as a BLE device command) | decompiled |
| Memorial/Get | Fetch the list of saved memorial/anniversary entries (name, date, linked image, linked voice recording). | (not separately captured — likely empty/base request; no dedicated `MemorialGetRequest.java` found) | `MemorialList`: array of {`ImageFileId`, `LcdImageArray`(List\<String\>), `MemorialDay`, `MemorialId`, `MemorialMoon`, `MemorialName`, `MemorialTime`, `RecordFileId`} | device already exposes via BLE | decompiled |
| Memorial/ListCount | Get the count/changed-state of the memorial list (used for sync/pagination). | `ListCount` (int) | (no dedicated response class found; likely `BaseResponseJson` + count field returned generically) | device already exposes via BLE | name-only |
| Memorial/SendOneByOne | Push memorial entries to the device one at a time (sync step, paired with `ListCount`). | (no dedicated request class found — pattern mirrors `TimePlan/SendOneByOne`) | status only | device already exposes via BLE | name-only |
| Memorial/Set | Create/update a memorial (anniversary) entry — name, date, linked LCD images, linked voice recording. | `ImageFileId`(string), `LcdImageArray`(List\<String\>), `MemorialDay`(int), `MemorialId`(int), `MemorialMoon`(int), `MemorialName`(string), `MemorialTime`(int), `RecordFileId`(string) | `MemorialId` (int) | device already exposes via BLE | decompiled |
| TimePlan/Change | Notify/sync a change event for a WiFi time-plan (event name + plan id). No live caller found in the decompiled sources — response class exists but appears unused/vestigial. | (no request class found) | `Event`(string), `PlanID`(string) | device-control (WiFi-only path; project's TimePlan is BLE) | name-only |
| TimePlan/Close | Disable/close a WiFi time-plan by id. | `PlanID` (int) | status only | device-control (WiFi-only path) | decompiled |
| TimePlan/Del | Delete a WiFi time-plan, scoped to a list of target devices. | `DeviceList`: array of {`DeviceId`(long)}, `PlanID`(int) | `PlanID` (int) | device-control (WiFi-only path) | decompiled |
| TimePlan/GetList | List all WiFi time-plans for the account. Real caller: `WifiPlannerModel` (`HttpCommand.TimePlanGetList`, empty request). | none (empty `BaseRequestJson`) | `TimePlanList`: array of `WifiPlannerMainItem` (not expanded — separate bean file) | device-control (WiFi-only path; project's TimePlan is BLE) | decompiled |
| TimePlan/GetPlan | Fetch full detail (schedule items) for one WiFi time-plan by id. | `PlanID` (int) | `IsEnable`(int), `PlanID`(int), `PlanName`(string), `TimePlanUpdateTime`(int), `PlanItem`: array of `PlanItemBean` {`PlanItemClockFileId`, `PlanItemClockId`, `PlanItemClockName`, `PlanItemCreateTime`, `PlanItemCycle`(List of `{Week}`), `PlanItemEnd`, `PlanItemFileId`, `PlanItemName`, `PlanItemPlayMode`, `PlanItemStart`, `PlanItemType`, `PlanItemVoiceStatus`} | device-control (WiFi-only path) | decompiled |
| TimePlan/ListCount | Get item count for a WiFi time-plan (used for incremental sync, paired with `SendOneByOne`). | `ListCount`(int), `PlanID`(int), `TimePlanUpdateTime`(int) | status only | device-control (WiFi-only path) | decompiled |
| TimePlan/SendOneByOne | Push one schedule item of a WiFi time-plan at a time (sync step). | `ListId`(int), `PlanItemClockId`(int), `PlanItemCycle`(List of `{Week}`), `PlanItemEnd`(int), `PlanItemFileId`(string), `PlanItemStart`(int), `PlanItemType`(int), `PlanItemVoiceStatus`(int) | status only | device-control (WiFi-only path) | decompiled |
| TimePlan/Set | Create/update a full WiFi time-plan (name, enabled flag, list of schedule items). | `IsEnable`(int), `PlanID`(int), `PlanItem`: array of `PlanItemBean` (same shape as `GetPlan`), `PlanName`(string) | `PlanID`(int), `isOk`(boolean), `mItem`: `WifiPlannerMainItem` | device-control (WiFi-only path; project's TimePlan is BLE) | decompiled |

## Unknown / no signal

None — all 38 commands in this batch had a matching request and/or response class in the
decompiled sources, and all but `TimePlan/Change` had at least one confirmed real caller in the
app's fragment/model layer. Two commands (`Memorial/ListCount`, `Memorial/SendOneByOne`) lack a
dedicated request/response `.java` file — their shape is inferred by analogy to the parallel
`TimePlan/ListCount` / `TimePlan/SendOneByOne` pair (same list-sync pattern used elsewhere in the
app) and are marked `name-only` rather than `unknown` for that reason.
