# Photo/PhotoFrame/Discover API

Reference catalog for the `Photo/*` and `PhotoFrame/*` domains (device
photo-frame album management + slideshow playback) and the `Discover/*`
domain (the app's home-screen "Discover" tab — curated albums, radio
stations, store links, themes, and "what's new" content).

Source: decompiled Divoom Android app (JADX) at
`references/apk/decompiled_src/sources/com/divoom/Divoom/` — master command
list in `http/HttpCommand.java`, request shapes in `http/request/**`,
response shapes in `http/response/**`, callers found by grepping the
`HttpCommand.*` constant across `view/fragment/**/*.java` and
`**/model/*.java`.

**Transport note (important for this project):** `http/HttpCommand.java`
defines two routing arrays that change which of these commands actually
reach `app.divoom-gz.com`:
- `ForceDeviceHttp = {PhotoGetPhotoList, PhotoTestLocal}` — these two are
  **always** sent to the device's own local LAN HTTP server
  (`OkHttpUtils.postLocalDevice`), never to the cloud.
- `DeviceAndServerCmd` includes `PhotoPlayAlbum`, `PhotoSetAlbumCover`,
  `PhotoDeletePhoto`, `PhotoRemovePhotoFromAlbum`, `PhotoDevicePhotoToAlbum`
  — these are routed to the local device when Wi-Fi-connected, and fall
  back to the cloud server or MQTT otherwise (`http/BaseParams.java:325-343`,
  `isForceDeviceHttpCommand`/`isDeviceAndServerCmd`). All other `Photo/*`
  commands (album CRUD, config) go straight to the cloud endpoint.
- `Photo/Enter` is not an HTTP call at all in this build — `LyricModel.h()`
  sends it as a bare `{"Command":"Photo/Enter"}` payload over **Bluetooth
  SPP** (`bluetooth/q.java`'s `B(Object)` → `writeWifiJson`, tagged
  `SPP_JSON`), reusing the same command-name string. Worth knowing since
  this project talks BLE directly to the device.

A public (reverse-engineered) endpoint list exists at
[divoom.2a03.party/api/app.html](https://divoom.2a03.party/api/app.html)
(REvoom Team). It independently lists `PhotoFrame/GetList` and all nine
`Discover/*` commands in this batch by name, but documents **no fields**
for any of them — the decompiled shapes below are the only field-level
source found. No other public documentation of the `Photo/*` or
`Discover/*` domains was found via web search.

| Command | Purpose | Request fields | Response fields | Relevance | Confidence |
|---|---|---|---|---|---|
| `Photo/ChangeScaling` | Set whether the device's photo-frame slideshow fills the frame (fit vs. crop) for the active device. | `PhotoChangeScalingRequest`: FillFrame | `BaseResponseJson` | device-control | decompiled |
| `Photo/DeleteAlbum` | Delete a photo album ("clock") from the device by `ClockId`. Also handled as an incoming response tag over Bluetooth (`bluetooth/f.java`), confirming it's mirrored on the BLE side too. | `PhotoDeleteAlbumRequest`: ClockId | `BaseResponseJson` | device-control | decompiled |
| `Photo/DeletePhoto` | Delete one or more photos from an album on the device. In `DeviceAndServerCmd` (local-first, cloud/MQTT fallback). | `PhotoDeletePhotoRequest` (extends `BaseChannelRequest`): ClockId, PhotoList[] | `BaseResponseJson` | device-control | decompiled |
| `Photo/DevicePhotoToAlbum` | Move photos already stored on the device into a target album (`ToClockId`). In `DeviceAndServerCmd`. | `PhotoDevicePhotoToAlbumRequest`: PhotoList[], ToClockId | `PhotoGetAlbumConfigResponse` (reused at this call site — effectively just the base ack fields; likely copy-paste, not a real config payload) | device-control | decompiled |
| `Photo/Enter` | Tell the device to enter photo/lyric display mode. **Not an HTTP call** — sent as a bare `{"Command":"Photo/Enter"}` over Bluetooth SPP via `bluetooth/q.B()` (`LyricModel.h()`). No response is parsed (fire-and-forget). | none (bare command, no body) | n/a (BLE fire-and-forget) | device-control | decompiled |
| `Photo/GetAlbumConfig` | Fetch the photo-frame slideshow/display settings for the active device (fill/crop, overlays, slideshow theme+speed, video playback options). | none (empty `BaseRequestJson`) | `PhotoGetAlbumConfigResponse`: DisplayOrder, FillFrame, FrameBackground, ReversePhotoOrder, ShowClock, ShowTitle, ShowWeather, SlideshowSpeed, SlideshowTheme, VideoAutoMute, VideoAutoPlay, VideoPlayBack, VideoVolume | device-control | decompiled |
| `Photo/GetAlbumList` | List the photo albums ("clocks") configured for the device. | none (empty `PhotoGetAlbumListRequest`) | `PhotoGetAlbumListResponse`: AlbumList[] (`AlbumListItem`: AlbumType, ClockId, ClockName) | device-control | decompiled |
| `Photo/GetPhotoList` | Paginated listing of photos within a given album/clock. **Always routed to the device's local LAN HTTP server** (`ForceDeviceHttp` — never reaches the cloud). | `PhotoGetPhotoListRequest` (extends `BaseLoadMoreRequest`): ClockId, ParentClockId, ParentItemId (+ inherited pagination) | `PhotoGetPhotoListResponse`: PhotoList[] (`PhotoListItem`: FileId, PhotoId) | device-control | decompiled |
| `Photo/LocalAddToAlbum` | Upload a local photo (from the phone) into a device album. Shares the large `PhotoAddToAlbumRequest` shape used for local uploads. | `PhotoAddToAlbumRequest` (extends `BaseChannelRequest`): ClockId, FileName, PreviewFileName, PhotoFlag, PhotoIndex, PhotoTotalCnt, PhotoTitle, PhotoHeight/Width, PhotoX/Y, SendTime, TakingTime (+ non-serialized crop/scale/local-file fields) | not typed at this call site (base ack expected) | device-control | decompiled |
| `Photo/NewAlbum` | Create a new photo album ("clock") with a given name. | `PhotoNewAlbumRequest`: ClockId, ClockName | `PhotoNewAlbumResponse`: ClockId, ClockName, ImagePixelId | device-control | decompiled |
| `Photo/PlayAlbum` | Start slideshow playback of a given album on the device screen — the core "play this album" action. In `DeviceAndServerCmd`. | `PhotoPlayAlbumRequest`: AlbumId | `BaseResponseJson` | device-control | decompiled |
| `Photo/RemovePhotoFromAlbum` | Remove specific photos from an album (reuses `PhotoDeletePhotoRequest`: ClockId + PhotoList). In `DeviceAndServerCmd`. | `PhotoDeletePhotoRequest`: ClockId, PhotoList[] | `BaseResponseJson` | device-control | decompiled |
| `Photo/RenameAlbum` | Rename an existing album. | `PhotoRenameAlbumRequest`: ClockId, ClockName | `BaseResponseJson` | device-control | decompiled |
| `Photo/SetAlbumConfig` | Set the photo-frame slideshow/display settings (mirror of `Photo/GetAlbumConfig`'s fields, plus `SubSlideshowTheme`). A parallel `BluePhotoSetAlbumConfigRequest` with only 4 fields (DisplayOrder, ReversePhotoOrder, SlideshowSpeed, SlideshowTheme) is used on the Bluetooth-connected variant of this screen, implying BLE-connected devices only expose a subset of these settings. | `PhotoSetAlbumConfigRequest`: DisplayOrder, FillFrame, FrameBackground, ReversePhotoOrder, ShowClock, ShowTitle, ShowWeather, SlideshowSpeed, SlideshowTheme, SubSlideshowTheme, VideoAutoMute, VideoAutoPlay, VideoPlayBack, VideoVolume | `BaseResponseJson` | device-control | decompiled |
| `Photo/SetAlbumCover` | Set the cover thumbnail image for an album (`FileId` from a prior upload). In `DeviceAndServerCmd`. | `PhotoSetAlbumCoverRequest`: ClockId, FileId, PhotoId | `BaseResponseJson` | device-control | decompiled |
| `Photo/TestLocal` | Unknown intent — no dedicated request/response class and **zero** callers anywhere in the decompiled sources beyond the `HttpCommand` declaration. Only signal is membership in `ForceDeviceHttp` alongside `Photo/GetPhotoList`, i.e. it's wired to always route to the device's local HTTP server if it were ever invoked — suggesting a local-connectivity probe/health-check for the photo-frame feature that isn't called from any current UI path in this build. | — | — | device-control (unconfirmed) | name-only |
| `PhotoFrame/GetList` | Fetch a catalog of preset/stock photo-frame layouts (big/small image ids + pixel start coordinates), keyed by `Language` — a content catalog rather than the user's own album. The only command in this batch with a public (if field-less) doc entry at divoom.2a03.party. | `PhotoFrameGetListRequest`: Language | `PhotoFrameGetListResponse`: PhotoList[] (`PhotoListBean`: BigImageId, PhotoName, PixelStartX, PixelStartY, SmallImageId) | device-control (content source for the photo-frame feature) | decompiled |
| `Discover/GetAlbumImageList` | Fetch the images inside one curated "Discover" album, with paging/sort/size filters (via `GetCloudBaseRequestV2`). | `DiscoverGetAlbumImageListRequest` (extends `GetCloudBaseRequestV2`): AlbumId (+ inherited FileSize, FileSort, paging) | not resolved at this call site (generic `CloudRefreshFragment` handles the response type) | account/social | decompiled |
| `Discover/GetAlbumImageListV3` | Same call site and request shape as `Discover/GetAlbumImageList` (`CloudAlbumInfoFragment`) — appears to be a versioned server-side alias, not a distinct client-side shape. | `DiscoverGetAlbumImageListRequest` (same as V1) | not resolved at this call site | account/social | decompiled |
| `Discover/GetAlbumInfo` | Fetch social/engagement metadata (comments, likes, shares, forum id) for one curated Discover album. | `DiscoverGetAlbumInfoRequest`: AlbumId, CountryISOCode, Langue | `DiscoverGetAlbumInfoResponse`: CommentCnt, ForumId, KeyWork, LikeCnt, ShareCnt | account/social | decompiled |
| `Discover/GetAlbumList` | List curated "Discover" content albums for the home-screen tab, localized. | `DiscoverGetAlbumListRequest`: CountryISOCode, Langue | `DiscoverGetAlbumListResponse`: AlbumList[] (`AlbumListItem`: AlbumBigImageId, AlbumId, AlbumImageId, AlbumName) | account/social | decompiled |
| `Discover/GetAlbumListV3` | Versioned variant of `Discover/GetAlbumList` — `CloudAlbumModel` calls it with `CloudGetAlbumListV2Request`/`CloudGetAlbumListV2Response` (paginated: StartNum, EndNum, FileSort, FileSize) instead of the V1 shape, i.e. a newer paginated album-list endpoint under the same Discover command family. | `CloudGetAlbumListV2Request`: StartNum, EndNum, FileSort, FileSize | `CloudGetAlbumListV2Response` (shape not expanded in this batch) | account/social | decompiled |
| `Discover/GetRadioList` | List curated internet-radio stations shown in the Discover tab, localized. Content-discovery listing only — no play action lives on this command (that's the separate `fm/Radio*` family). | `DiscoverGetRadioListRequest`: CountryISOCode, Langue | `DiscoverGetRadioListResponse`: RadioList[] (`RadioListItem`: RadioImageId, RadioName) | account/social | decompiled |
| `Discover/GetStoreList` | List entries for Divoom's in-app "store" (merch/product links), localized, with an optional `Type` filter. | `DiscoverGetStoreListRequest`: CountryISOCode, Langue, Type | `DiscoverGetStoreListResponse`: MallLinkUrl, StoreList[] (`StoreListItem`: LinkUrl, StoreImageId, StoreName) | account/social (commerce/marketing) | decompiled |
| `Discover/GetTheme` | Fetch themed/seasonal curated content entries for the Discover tab, localized. | `DiscoverGetThemeRequest`: CountryISOCode, Langue | `DiscoverGetThemeResponse`: ThemeList[] (`ThemeListItem`: ForumId, ImageId, Title) | account/social | decompiled |
| `Discover/GetTopNew` | Fetch the "what's new" banner/highlight content for the Discover tab, localized. | `DiscoverGetTopNewRequest`: CountryISOCode, Langue | `DiscoverGetTopNewResponse`: NewImageId, NewList[] (`MedalListItem` — item shape not resolved in this batch), TextColor | account/social | decompiled |

## Unknown / no signal

- `Photo/TestLocal` — declared as an `HttpCommand` constant and included in
  the `ForceDeviceHttp` local-routing array, but has no dedicated
  request/response class and no caller anywhere in the decompiled sources.
  Likely a dormant local-connectivity probe for the photo-frame feature,
  or dead code from an earlier build.
