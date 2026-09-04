# Tomato/Sleep/AidSleep/WhiteNoise/Alarm API

Source: decompiled Divoom Android APK (JADX), `references/apk/decompiled_src/sources/com/divoom/Divoom/`
(master catalog `http/HttpCommand.java`; shapes from `http/request/**` and `http/response/**`;
callers grepped across `view/fragment/**/model/*.java` and `bluetooth/{f,q}.java`).

Two transports are used under the same `HttpCommand` string constants:

- **HTTP POST** to `app.divoom-gz.com` (via `BaseParams.postRx(...)`) — real cloud round-trips.
- **Raw JSON-over-BLE** (via `bluetooth.q#B(Object)`, which just `JSON.toJSONString()`s the
  request object and writes it as an `SPP_JSON` packet) or **MQTT** (`BaseParams.postMqtt(...)`,
  used only by the `Sleep/*` group for WiFi-connected sleep-light products). Several commands never
  touch HTTP at all — the "cloud" command name is reused purely as a BLE/MQTT JSON envelope. This is
  called out per-row below; it matters because those commands need **no cloud auth** to use.

A recurring **cloud→device sync pattern** appears for both Tomato and Alarm: the app fetches the
cloud list over HTTP (`Tomato/GetList` / `Alarm/Get`), then pushes an item count over BLE
(`Tomato/ListCount` / `Alarm/ListCount`) followed by each item one at a time over BLE
(`Tomato/SendOneByOne` / `Alarm/SendOneByOne`, reusing the `*Set`/`AlarmListItem` shape). The reverse
direction (`Tomato/DevUpdate`, `Alarm/DevUpdate`) is the device pushing its on-device state back to
the app over BLE, parsed in `bluetooth/f.java`.

A public (unofficial) third-party doc of this same remote API exists at
[divoom.2a03.party/api/app.html](https://divoom.2a03.party/api/app.html) (REvoom Team); it confirms
`Alarm/Set` as a real endpoint gated by `Token`/`UserId`/`DeviceId`, consistent with what's found here.
No official Divoom documentation for `AidSleep/*` or `Tomato/*` was found in web search.

| Command | Purpose | Request fields | Response fields | Relevance | Confidence |
|---|---|---|---|---|---|
| `Tomato/Delete` | Delete one cloud-saved Tomato (pomodoro) config by id; also forwarded to the device over BLE after the HTTP delete. | `TomatoId` | `BaseResponseJson` (no extra fields) | device-control | decompiled |
| `Tomato/DeleteFocus` | Delete one completed focus-session record under a Tomato. | `FocusId`, `TomatoId` | `BaseResponseJson` | account/social | decompiled |
| `Tomato/DevUpdate` | Inbound only: device pushes its current Tomato config back to the app over BLE (`bluetooth/f.java`), so the app can re-sync it to the cloud. | `TomatoId`, `WorkTime`, `ShortRestTime`, `LongRestTime`, `SoundSystem`, `SoundType`, `TimeCyclerType` | n/a (inbound push) | device-control | decompiled |
| `Tomato/EditFocus` | Edit a focus session's start/end time and note. | `TomatoId`, `FocusId`, `StartTime`, `EndTime`, `Note` | `BaseResponseJson` | account/social | decompiled |
| `Tomato/FocusAction` | Record a focus-session start/stop action (time-tracking event). | `TomatoId`, `StartTime`, `EndTime`, `FocusTime` | `BaseResponseJson` | account/social | decompiled |
| `Tomato/FocusDone` | Mark a running focus session as completed. | `TomatoId`, `StartTime` | `BaseResponseJson` | account/social | decompiled |
| `Tomato/GetFocusList` | Paginated history of past focus sessions for one Tomato. | `TomatoId` + `BaseLoadMoreRequest` paging | `focusList[]`: `EndTime`, `FocusId`, `Note`, `StartTime` | account/social | decompiled |
| `Tomato/GetList` | Fetch the user's cloud-saved list of Tomato (pomodoro) timer configs (`FinishFlag` filter, paginated). | `FinishFlag` + paging | `tomatoList[]`: `TomatoId`, `TomatoName`, `WorkTime`, `ShortRestTime`, `LongRestTime`, `TimeCyclerType`, `SoundOnOff`, `SoundSystem`, `SoundType`, `SoundVoiceFileId`, `SoundVolume`, `ImageFileId`, `TomatoExplain`, `EstimateTime`, `TargetDate`, `FinishFlag`, `FocusTotalCount`, `FocusTotalTime` | device-control | decompiled |
| `Tomato/ListCount` | Sync handshake (BLE-only, no HTTP): app tells the device how many cloud Tomato configs exist, ahead of a `SendOneByOne` push. | `ListCount` | n/a (BLE fire-and-forget) | device-control | decompiled |
| `Tomato/Listen` | BLE+server command: preview-play a Tomato notification sound at a volume. | `SoundType`, `StartFlag`, `Volume` | `BaseResponseJson` | device-control | decompiled |
| `Tomato/ListenVolume` | Adjust volume while previewing a Tomato sound. | `Volume` | `BaseResponseJson` | device-control | decompiled |
| `Tomato/SendOneByOne` | Sync internals (BLE-only): push one cloud Tomato config item to the device, reusing the `TomatoSet` shape. | Same fields as `Tomato/Set` | n/a (BLE fire-and-forget) | device-control | decompiled |
| `Tomato/Set` | Create/update one Tomato (pomodoro) timer config in the cloud. | `TomatoId`, `TomatoName`, `WorkTime`, `ShortRestTime`, `LongRestTime`, `TimeCyclerType`, `SoundOnOff`, `SoundSystem`, `SoundType`, `SoundVoiceFileId`, `SoundVolume`, `ImageFileId`, `TomatoExplain`, `EstimateTime`, `TargetDate`, `FinishFlag` | `TomatoId` | device-control | decompiled |
| `Tomato/Start` | BLE+server command: notify that a Tomato session has started. | `TomatoId` | `BaseResponseJson` | device-control | decompiled |
| `Sleep/ExitTest` | Exit the sleep-aid "preview/test" state. Transport is **MQTT** (`BaseParams.postMqtt`), used for WiFi sleep-light products (e.g. Dida/FlowToo line), not the BLE pixel displays. | (no fields) | n/a | device-control | decompiled |
| `Sleep/Get` | Fetch the current sleep-aid light/sound config (served from a local cache, `DidaSleepCacheBean`). | (no fields; `BaseRequestJson`) | `Status`, `Minute`, `Color`, `Brightness`, `Volume`, `Mode`, `Scene`, `ChannelIndex` | device-control | decompiled |
| `Sleep/Set` | Push a sleep-aid light/sound config to the device. Transport is MQTT. | `Brightness`, `ChannelIndex`, `Color`, `Minute`, `Mode`, `Scene`, `ShowTime`, `Status`, `Volume` | `BaseResponseJson` | device-control | decompiled |
| `Sleep/Test` | Preview a sleep-aid scene before saving. Transport is MQTT. | `Brightness`, `Color`, `Scene`, `Volume` | `BaseResponseJson` | device-control | decompiled |
| `AidSleep/Add` | Add a track to the user's personal AidSleep library; HTTP POST, then the same request is also pushed to the device over BLE. | `AudioType`, `FileId`, `Language`, `Name`, `SleepId`, `Type`, `VideoType` | `BaseResponseJson` | **device-control — flag** | decompiled |
| `AidSleep/Delete` | Remove a track from the user's personal AidSleep library; HTTP POST, then forwarded to device over BLE. | `SleepId`, `Type` | `BaseResponseJson` | device-control | decompiled |
| `AidSleep/Exit` | BLE-only (no HTTP call at all — just `q.B(AidSleepEditRequest)`): tell the device to exit AidSleep playback/browse mode. | (no fields) | n/a | device-control | decompiled |
| `AidSleep/GetAllList` | **Browse Divoom's full cloud sleep-sound catalog**, paginated, filtered by `Type` (`0`=Natural Sound, `1`=White Noise, `2`=Music — see the three fragments `AidSleepNaturalSoundFragment`/`AidSleepWhiteNoiseFragment`/`AidSleepMusicFragment`, all sharing this one call). | `Type` + `BaseLoadMoreRequest` paging | `SleepList[]` (`AidSleepItem`): `SleepId`, `Name`, `FileId`, `Language`, `AudioType`, `VideoType`, `AddFlag` | **device-control — flag: viable browse feature** | decompiled |
| `AidSleep/GetMyList` | Same response shape as `GetAllList` but scoped to the user's own saved/added tracks (`AidSleepGetMyListRequest`). | `Type` + paging | Same as `AidSleep/GetAllList` | **device-control — flag** | decompiled |
| `AidSleep/Play` | **Not an HTTP call.** Builds `AidSleepPlayRequest{SleepId, Type}` and writes it directly over BLE as a JSON `SPP_JSON` packet (`bluetooth.q#B`) to start playback on the device. Needs no cloud auth once a `SleepId` is known. | `SleepId`, `Type` | n/a (BLE fire-and-forget) | **device-control — flag: viable browse feature** | decompiled |
| `AidSleep/Progress` | Inbound only: device pushes AidSleep playback progress back to the app over BLE (`bluetooth/f.java`). | `Progress` | n/a (inbound push) | device-control | decompiled |
| `WhiteNoise/Get` | Fetch the device's onboard multi-channel white-noise mixer state. This is the built-in fixed white-noise mixer, distinct from the cloud AidSleep sound library. Also received unsolicited as a BLE push using the same response shape. | (no fields) | `OnOff`, `Time`, `EndStatus`, `Volume[8]` (per-channel mix) | device-control | decompiled |
| `WhiteNoise/Set` | Set the onboard white-noise mixer state (per-channel volumes + timer). | `OnOff`, `Time`, `EndStatus`, `Volume[8]` | `BaseResponseJson` | device-control | decompiled |
| `Alarm/Change` | Declared in `HttpCommand.java` only — no request/response class, no caller anywhere in `view/fragment/**` or `bluetooth/*`. Purpose inferred purely from the name (likely a variant/legacy alarm-update path superseded by `Alarm/Set`). | unknown | unknown | account/social (guess) | name-only |
| `Alarm/Del` | Delete one cloud-saved alarm by id; also forwarded to device over BLE (`ServerAndBlueCommand`). | `AlarmId` | `BaseResponseJson` | device-control | decompiled |
| `Alarm/DelAll` | Declared in `HttpCommand.java` only — no request/response class, no caller found. Purpose inferred purely from the name (bulk-delete-all-alarms companion to `Alarm/Del`). | unknown | unknown | account/social (guess) | name-only |
| `Alarm/DevUpdate` | Inbound only: device pushes its current alarm config back to the app over BLE, for re-sync to the cloud. | `AlarmId`, `AlarmTime`, `EnableFlag`, `LcdImageArray`, `RepeatArray`, `SoundFm`, `SoundSystem`, `SoundType`, `Volume` | n/a (inbound push) | device-control | decompiled |
| `Alarm/Get` | Fetch the cloud alarm list (single alarm by id, or all via `IsGetAll`). | `AlarmId`, `IsGetAll` | `AlarmList[]` (`AlarmListItem`): `AlarmId`, `AlarmName`, `AlarmTime`, `Color`, `EarlyFlag`, `EnableFlag`, `ImageFileId`, `LcdImageArray`, `MusicInfo`, `RecordFileId`, `RepeatArray`, `SoundFm`, `SoundSystem`, `SoundType`, `UpdateTime`, `Volume` | device-control | decompiled |
| `Alarm/ListCount` | Sync handshake (BLE-only): app tells device how many cloud alarms exist, ahead of a `SendOneByOne` push — same pattern as `Tomato/ListCount`. | `ListCount` | n/a (BLE fire-and-forget) | device-control | decompiled |
| `Alarm/Listen` | BLE+server command: preview-play an alarm sound at a volume. | `SoundType`, `StartFlag`, `Volume` | `BaseResponseJson` | device-control | decompiled |
| `Alarm/ListenVolume` | Adjust volume while previewing an alarm sound. | `Volume` | `BaseResponseJson` | device-control | decompiled |
| `Alarm/SendOneByOne` | Sync internals (BLE-only): push one cloud alarm to the device, reusing the `AlarmListItem` shape — same pattern as `Tomato/SendOneByOne`. | Same fields as `AlarmListItem` (see `Alarm/Get`) | n/a (BLE fire-and-forget) | device-control | decompiled |
| `Alarm/Set` | Create/update one or more alarms in the cloud. Request wraps a list of `AlarmListItem` plus sync metadata. | `AlarmList[]` (`AlarmListItem`, see `Alarm/Get`), `AlarmUpdateTime`, `IsGetAll`, `ReturnCode`, `ReturnMessage` | `AlarmId`, `isAdd`, `flag` (`AlarmSetResponse`) | device-control | decompiled |

## Unknown / no signal

- `Alarm/Change` — only the string constant exists in `http/HttpCommand.java`; no request/response
  class and no caller found anywhere in `view/fragment/**` or `bluetooth/*`. Purpose is a guess from
  the name alone.
- `Alarm/DelAll` — same situation: constant-only, no request/response shape, no caller found.
