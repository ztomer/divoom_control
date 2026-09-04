# Device API

Source: JADX-decompiled Divoom Android app, master command list at
`references/apk/decompiled_src/sources/com/divoom/Divoom/http/HttpCommand.java`
(absolute path, gitignored — not shipped in this repo). Request shapes from
`http/request/**/*.java` (`@JSONField(name=...)`), response shapes from
`http/response/**/*.java`, callers found by grepping the `HttpCommand.<Constant>`
name across `view/fragment/**`, `**/model/*.java`, `bluetooth/f.java` (the
BLE-push-to-cloud relay) and `http/mqtt/MqttService.java` / `U3/C1274b.java`
(the MQTT/push-notification event dispatcher).

Several `Device/*` commands in this batch are not requests the client sends at
all — they are **event tags on server-pushed messages** (MQTT payloads or the
app's "notify" push channel) that the app matches with `.equals()` to decide
how to react (e.g. refresh the device list, restart the MQTT session). Those
are marked below; they have no request body in the traditional sense because
the app is the *receiver*, not the sender.

Public-doc cross-check: the community REvoom Team reference
(https://divoom.2a03.party/api/app.html) documents `Device/GetList` with
response fields `UserPublicIP`, `MasterFlag`, `DeviceList` — this matches the
decompiled `DeviceGetListResponse` shape exactly (this project's
`Device/GetListV2` constant maps to the same response class/shape). The same
page also lists `Device/BindUser`, `Device/Connect`, `Device/ConnectApp`,
`Device/Disconnect`, `Device/GetNewBind`, `Device/GetUpdateInfo`,
`Device/NotifyUpdate`, `Device/SetName`, `Device/SetPlace`, `Device/Unbind` as
real endpoint *names* under "undocumented endpoints" (existence confirmed, no
field-level detail beyond what the APK already gave us). No public source
documents request/response fields for any other command in this batch.

All endpoints below return the standard `BaseResponseJson` envelope
(`ReturnCode`, `ReturnMessage`) unless a richer response class is noted.

| Command | Purpose | Request fields | Response fields | Relevance | Confidence |
|---|---|---|---|---|---|
| Device/AppRestartMqtt | MQTT-pushed event telling the app to tear down and restart its MQTT session (server-initiated reconnect signal). | none — event tag on an inbound MQTT push, not a client-sent request | none (event carries only the base `Command`/`UserId`/timestamp envelope) | internal/moderation | decompiled (`http/mqtt/MqttService.java:109`, `U3/C1274b.java:127`) |
| Device/BindUser | Push/notify event fired when a new secondary user is bound to the device; the app reacts by refreshing its local device list. | none — event tag only | none | account/social | decompiled (`U3/C1274b.java:114`); web-confirmed as a real endpoint name (REvoom docs) |
| Device/BlueNoLanguage | BLE-received push (device reports a language/region restriction over Bluetooth) that the app relays to the cloud, then immediately follows up with `Device/GetNoBanFlag`. | `DeviceBlueNoLanguageRequest` — no dedicated fields beyond inherited base `DeviceId`/`DevicePassword` | `DeviceBlueNoLanguageResponse` — no fields beyond the base envelope | internal/moderation | decompiled (`bluetooth/f.java:603`, `http/request/device/DeviceBlueNoLanguageRequest.java`, `http/response/device/DeviceBlueNoLanguageResponse.java`) |
| Device/CloseClockTimer | Stop a running clock/countdown timer on the device. | `DeviceCloseClockTimerRequest`: `ClockId` (int) | `BaseResponseJson` | device-control | decompiled (`bluetooth/f.java:527`, `http/request/device/DeviceCloseClockTimerRequest.java`) |
| Device/Connect | Push/notify event: a WiFi device came online/connected to the cloud; triggers the app to refresh device state. | none — event tag only | none | device-control | decompiled (`U3/C1274b.java:131`); web-confirmed as a real endpoint name (REvoom docs) |
| Device/ConnectApp | MQTT-pushed event: the app itself connected, so the server marks the device "online" from the app's perspective. | none — event tag only | none | internal/moderation | decompiled (`http/mqtt/MqttService.java:99`); web-confirmed as a real endpoint name (REvoom docs) |
| Device/DeleteResetAll | Tells the cloud that a factory reset was just performed locally (over BLE, or from the WiFi settings UI), clearing server-side pending-reset state. | generic `BaseRequestJson` (`ForcePostServer=true`) | `BaseResponseJson` | device-control | decompiled (`bluetooth/f.java:620`, `view/fragment/more/lightSetting/LightSettingsFragment.java:420`) |
| Device/DeleteShareCodeV2 | Deletes/invalidates the device's currently active share-invite code. | generic `BaseRequestJson` | `BaseResponseJson` | account/social | decompiled (`WifiDeviceServer.b()`) |
| Device/DeleteUserV2 | Removes a bound secondary user from the device's user list (owner-only action). | generic request, field set via caller: `DeleteUserId` (int) | `BaseResponseJson` | account/social | decompiled (`WifiDeviceServer.c()`, `http/request/device/DeviceDeleteUserRequest.java`) |
| Device/Disconnect | Push/notify event: a WiFi device disconnected from the cloud; triggers the app to refresh device state. | none — event tag only | none | device-control | decompiled (`U3/C1274b.java:135`); web-confirmed as a real endpoint name (REvoom docs) |
| Device/DisconnectMqtt | MQTT-pushed event reporting a device online/offline transition. | none — event tag only | `DeviceDisconnectMqttResponse`: `Online` (int) | internal/moderation | decompiled (`http/mqtt/MqttService.java:103`, `http/response/device/DeviceDisconnectMqttResponse.java`) |
| Device/ExitDevice | Leave (un-associate self from) a shared device the current user does not own — same request shape as `Unbind`, different command chosen when the caller isn't the master user. | `DeviceUnbindRequest`: `UnBindDeviceId` (long) | `BaseResponseJson` | account/social | decompiled (`WifiDeviceServer.h()`) |
| Device/GetClassifyFontList | Inferred: fetch the list of font categories/classifications available for clock-face text (candidate response class `ClockFontResponse` matches by name — `classifyList[].{ID,Name,NameEn,FontList[]}` — but no call site was located wiring this specific command to it). | no confirmed request class | candidate: `ClockFontResponse` (unconfirmed) | device-control | name-only |
| Device/GetClockInfo | Fetch info for a specific clock/dial face by ID (WiFi-architecture devices), reusing the "reset clock" request shape with a different command string. | `WifiChannelResetClockRequest`: `ClockId` (int) | not confirmed (parsed generically as raw JSON, not a dedicated typed response class) | device-control | decompiled (`view/fragment/channelWifi/model/WifiChannelModel.java:1716`) |
| Device/GetDispClassify | Inferred: fetch the top-level list of clock-face display categories (candidate response class `ClockClassifyItemListResponse` — `ClassifyList[].{ID,Name,NameEn,DispItemList[]}` — matches by name/shape but no call site was located wiring this specific command). | no confirmed request class | candidate: `ClockClassifyItemListResponse` (unconfirmed) | device-control | name-only |
| Device/GetDispItemList | Inferred: fetch the items within one display/clock-face category. The nested `DispItemList` field (`{ClassifyID,ClassifyName,ClassifyNameEn,Desc,ID,ItemId,Name,NameEn,OpenStatus}`) exists inside `ClockClassifyItemListResponse.ClassifyListJson`, matching this command's name closely, but no direct top-level call site was found. | not confirmed | candidate fields (nested, see above) | device-control | name-only |
| Device/GetFileVersion | Query the currently-installed version of a given resource/firmware file type on the device. | `DeviceGetFileVersionRequest`: `FileType` (int) | `DeviceGetFileVersionResponse`: `FileId` (str), `FileType` (int), `Version` (int) | device-control | decompiled (`bluetooth/f.java:551`) |
| Device/GetFontClassify | Inferred: fetch a flat font-classification list, localized (candidate response class `ClockFontClassifyResponse` — `DispFontList[].{ID,NameCn,NameEn}` — matches by name but no call site was located wiring this specific command). | no confirmed request class | candidate: `ClockFontClassifyResponse` (unconfirmed) | device-control | name-only |
| Device/GetListV2 | List all WiFi devices bound to the user's account, with names/places/IPs. | generic `BaseRequestJson` | `DeviceGetListResponse`: `DeviceList[]` (each: `DeviceId`, `DeviceName`, `DevicePlace`, `DevicePrivateIP`, `DevicePublicIP`, `DeviceSSID`, `DeviceType`, `DeviceVersion`, `LocalToken`, `MasterFlag`, `NetMask`), `MasterFlag` (int), `UserPublicIP` (str) | device-control | decompiled (`U3/C1273a.java:222`); web-confirmed field-level match against REvoom docs' `Device/GetList` |
| Device/GetNewBind | Polled during the WiFi setup flow to detect when the device has just been bound to the current account. | generic `BaseRequestJson` | `DeviceGetNewBindResponse`: `NewBindFlag` (int) | device-control | decompiled (`view/fragment/wifi/model/WifiConnectModel.java:109`, `view/fragment/wifi/WifiConfigFragment_3.java:210`); web-confirmed as a real endpoint name (REvoom docs) |
| Device/GetNoBanFlag | Check whether the device/region is banned/restricted from certain content, following up a `BlueNoLanguage` report. | `DeviceGetNoBanFlagRequest`: `NoBan` (int), plus inherited base `DeviceId`/`DevicePassword` | `DeviceGetNoBanFlagResponse`: `NoBan` (int) | internal/moderation | decompiled (`bluetooth/f.java:610`) |
| Device/GetNoMasterListV2 | List the non-owner users who have shared access to the device. | generic `BaseRequestJson` | `DeviceGetNoMasterListV2`: `UserList[]` (each: `UserId`, `UserNickName`, `UserHeadId`) | account/social | decompiled (`WifiDeviceServer.e()`) |
| Device/GetShareCodeV2 | Generate a device-sharing invite code (with expiry) that another user can redeem. | generic `BaseRequestJson` | `DeviceGetShareDeviceCodeResponse`: `ShareCode` (int), `ExpireTime` (int) | account/social | decompiled (`WifiDeviceServer.f()`) |
| Device/GetSomeFontInfo | Fetch detailed metadata for a specific set of font IDs (used by the clock-face editor's font picker). | `ClockGetFontInfoRequest`: `FontIds[]` (each `{Id}`) | `ClockGetFontInfoResponse` (font detail fields, not read in full here) | device-control | decompiled (`bluetooth/f.java:123`, `view/fragment/clockEdit/model/ClockEditModel.java:128`) |
| Device/GetStorageStatus | Check whether the device's local storage is full. | generic `BaseRequestJson` | `DeviceGetStorageStatusResponse`: `Full` (int) | device-control | decompiled (`bluetooth/f.java:451,546`) |
| Device/GetUpdateFileList | Query which firmware/resource file versions are available for a given set of hardware IDs. | `DeviceGetUpdateFileListRequest`: `HardwareList[]` (int list), `IsTest` (int) | `DeviceGetUpdateFileListResponse`: `VersionList[]` (int list) | device-control | decompiled (request/response classes with real fields found; no live call site located in this APK snapshot) |
| Device/GetUpdateInfo | Check whether a firmware update is available for the device, and what version. | `DeviceGetUpdateInfoRequest`: `Language` (str), `TestFlag` (int) | `DeviceGetUpdateInfoResponse`: `CanUpdate` (int), `Version` (str) | device-control | decompiled (`view/fragment/eventChain/loginChain/WifiDeviceUpdateModel.java:88`); web-confirmed as a real endpoint name (REvoom docs) |
| Device/GetUserDialList | List the clock/dial faces saved to the user's account. | generic `BaseRequestJson` | `DeviceGetUserDialListResponse`: `DialList[]` (each: `Classify`, `ClockId`, `Name`, `Status`, `UpdateTime`) | device-control | decompiled (`view/fragment/clockEdit/model/ClockEditModel.java:96`, "getUserClockList") |
| Device/GiftMode | Toggle "gift mode" — an unconfigured/demo state for a device that hasn't been claimed by its final owner yet. | `GiftModeRequest`: `GiftMode` (int) | `BaseResponseJson` | device-control | decompiled (`view/fragment/wifi/model/WifiConnectModel.java:73`) |
| Device/Hearbeat | MQTT keepalive: server pushes this, the app echoes the same command + `DeviceId` back via `postMqtt` to keep the session alive. (Sic — "Hearbeat" is the actual, misspelled, wire string.) | generic `BaseRequestJson` (`DeviceId` set from the push) | none | internal/moderation | decompiled (`http/mqtt/MqttService.java:84-88`) |
| Device/InputShareCodeV2 | Redeem a share code to gain shared access to another user's device. | `DeviceInputShareCodeRequest`: `ShareCode` (int) | `BaseResponseJson` | account/social | decompiled (`WifiDeviceServer.a()`) |
| Device/NotifyUpdate | Push an "update available" prompt/notification to the device or its owning user. | `DeviceGetUpdateInfoRequest`: `TestFlag` (int) (reused request shape) | `BaseResponseJson` | device-control | decompiled (`WifiDeviceUpdateModel.java:70`); web-confirmed as a real endpoint name (REvoom docs) |
| Device/ResetAll | Full device reset from the Settings UI; on success the app navigates back to the device list (effectively unbinds/resets the device). | generic `BaseRequestJson` (`Command` set explicitly) | `BaseResponseJson` | device-control | decompiled (`WifiLightSettingsModel.java:429`) |
| Device/SetDeviceVersion | Report/set the device's firmware/hardware version value on the server record. | `DeviceSetDeviceVersionRequest`: `DeviceVersion` (int) | `BaseResponseJson` (no dedicated response class found) | device-control | decompiled (request class with real field found; no live call site located in this APK snapshot) |
| Device/SetLog | Toggle device-side debug logging — an internal QA/test feature exposed in the app's hidden "About/Test" screen. | `DeviceSetLogRequest`: `Flag` (int) | `BaseResponseJson` | internal/moderation | decompiled (`view/fragment/more/test/AboutTestFragment.java:417`) |
| Device/SetName | Rename the device. | `DeviceSetNameRequest`: `DeviceName` (str) | `BaseResponseJson` | device-control | decompiled (`WifiDeviceServer.g()`); web-confirmed as a real endpoint name (REvoom docs) |
| Device/SetPlace | Set the device's "place" (a room/location enum, e.g. living room/bedroom). | `DeviceSetPlaceRequest`: `DevicePlace` (int) | `BaseResponseJson` | device-control | decompiled (`http/request/device/DeviceSetPlaceRequest.java`); web-confirmed as a real endpoint name (REvoom docs) |
| Device/SetUTC | Sync the device's clock/timezone to the server's canonical UTC time. | `DeviceSetUtcRequest`: `Time` (str), `Utc` (long) | `BaseResponseJson` | device-control | decompiled (`http/request/device/DeviceSetUtcRequest.java`) |
| Device/Unbind | Unbind (remove) a device from the account, as its owner. | `DeviceUnbindRequest`: `UnBindDeviceId` (long) | `BaseResponseJson` | device-control | decompiled (`WifiDeviceServer.h()`); web-confirmed as a real endpoint name (REvoom docs) |
| Device/WiFiGetLanguageFlag | Check whether the device's currently-set language is prohibited/banned in the current region. | `DeviceWiFiGetLanguageFlagRequest` (`ForcePostServer=true`, no dedicated fields) | `DeviceWiFiGetLanguageFlagResponse`: `ProhibitionLanguage` (int) | internal/moderation | decompiled (`view/activity/b.java:168`) |

## Unknown / no signal

None. Every command in this batch resolved to at least a bare-string caller
or a plausibly-named request/response class; the four marked `name-only`
above (`GetClassifyFontList`, `GetDispClassify`, `GetDispItemList`,
`GetFontClassify`) have candidate classes identified by name/shape match but
lack a confirmed call site tying the exact command string to that exact
class — they are not blind guesses, just unconfirmed.
