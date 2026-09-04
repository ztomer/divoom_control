# Draw/Led/Lyric API

Source: JADX-decompiled Divoom Android app, `references/apk/decompiled_src/sources/com/divoom/Divoom/`
(gitignored). Master list `http/HttpCommand.java`; shapes in `http/request/**`, `http/response/**`;
callers grepped from `view/fragment/**/model/*.java` and `http/mqtt/MqttService.java`.

This domain is the phone's **live pixel-drawing/sync protocol**: uploading/streaming a drawn or
uploaded image to a device over WiFi (with an MQTT-based retransmit/ack channel for lost packets),
the user's saved custom color palettes for the pixel-art editor, and the LED-marquee / lyric-display
text-scroll features. No public docs (doc.divoom-gz.com, github.com/r12f/divoom, pixoo-rest, etc.)
cover this `Draw/*`, `Led/*`, `Lyric/*`, `Mixer/*` cloud namespace — two web searches turned up only
the local-Pixoo REST API and generic repo descriptions, confirming this batch is reverse-engineering-only.

| Command | Purpose | Request fields | Response fields | Relevance | Confidence |
|---|---|---|---|---|---|
| `Draw/CopyColorListV2` | Duplicate one of the user's saved cloud color palettes under a new name. | `NewName` (string), `PaletteId` (int) | `PaletteId` (int, new palette's id) | device-control | decompiled |
| `Draw/DeleteColorListV2` | Delete one or more saved color palettes. | `PaletteIdArray` (int[]) | (base only) | device-control | decompiled |
| `Draw/EqLocalHttp` | Upload a drawn/EQ-visualizer pixel image (with author/head metadata) to cloud storage and push it to the device over WiFi; the "EQ" variant of `PixelLocalHttp` used when the audio-reactive EQ effect is being synced. | `FileName`, `Flag` (packet flag), `ImageName`, `AuthorId`, `NickName`, `HeadFileId`, `HeadFileName`, `SoundFileName`, `LcdIndex` (int[]) | (base only) | device-control | decompiled |
| `Draw/ExitSync` | Tell one or more LCD-indexed device screens to exit pixel-drawing sync mode (return to normal display). | `LcdArray` (int[]) | (base only) | device-control | decompiled |
| `Draw/GetPaletteColorList` | Fetch the palette color list (legacy/simple variant, no request params beyond base auth fields). | (base only, no extra fields) | unknown (no response class found) | device-control | name-only |
| `Draw/GetPaletteV2` | Paginated fetch of the user's saved custom color palettes. | `AndroidFlag` (int, +base load-more paging fields) | `Index` (int), `PaletteList[]` (each: `PaletteId`, `Name`, `ColorList[]`) | device-control | decompiled |
| `Draw/LocalEq` | After uploading a temp file (via `CloudUploadTemp`), publish its `FileId` to the device over MQTT to sync the EQ/audio-visualizer graphic locally. | `FileId` (string) | (base only) | device-control | decompiled |
| `Draw/NeedEqData` | **Device→app MQTT push.** Device reports a missing EQ-image packet (by `LcdIndex`+`PacketId`); app looks up the cached packet and republishes it over MQTT. Part of the packet-loss retransmit protocol for streamed EQ pixel data. | (push payload) `LcdIndex` (int), `PacketId` (int) — parsed as `DrawCacheResponse` | n/a (push, no reply envelope) | device-control | decompiled |
| `Draw/NeedLocalData` | **Device→app MQTT push.** Same retransmit mechanism as `NeedEqData` but for the normal (non-EQ) pixel-drawing stream. | (push payload) `LcdIndex` (int), `PacketId` (int) — parsed as `DrawCacheResponse` | n/a (push) | device-control | decompiled |
| `Draw/NeedSendDraw` | **Device→app MQTT push.** Device signals it's ready/waiting for the app to (re)send the current drawing; app posts an internal event bus message to trigger a resend. | (push payload, not parsed into a typed class — just triggers a resend) | n/a (push) | device-control | decompiled |
| `Draw/NewColorListV2` | Create a new saved color palette. | `NewName` (string), `ColorList` (List\<String\>) | `PaletteId` (int, new palette's id) | device-control | decompiled |
| `Draw/PixelLocalHttp` | Shares the exact request shape used by `Draw/EqLocalHttp` (`DrawPixelLocalHttpRequest`: `AuthorId`, `FileName`, `Flag`, `HeadFileId`, `HeadFileName`, `ImageName`, `LcdIndex[]`, `NickName`, `SoundFileName`) — the non-EQ local pixel-image upload+sync variant. No call site in the decompiled sources sets this exact command string (the only usage found always overrides it to `DrawEqLocalHttp`), so it may be superseded/dead in this app version. | same fields as `Draw/EqLocalHttp` (inferred) | (base only, inferred) | device-control | name-only |
| `Draw/RenameColorListV2` | Rename a saved color palette. | `NewName` (string), `PaletteId` (int) | (base only) | device-control | decompiled |
| `Draw/SendByLcdIndex` | Trigger a (re)send of the current drawing to a specific LCD-indexed screen (used when the same image hash was already sent, to push it to one more panel in a multi-panel/5-LCD setup). | `LcdIndex` (int) | (base only) | device-control | decompiled |
| `Draw/SendLocal` | Legacy chunked local-image upload (base64 image data split into offset/length chunks). Request class (`DrawingRequest`) exists and sets this command in its constructor, but no instantiation site was found in the decompiled sources — appears superseded by `Draw/PixelLocalHttp`/`Draw/EqLocalHttp`. | `ImageData` (base64 string), `ImageFlag` (int), `Offset` (int), `TotalLen` (int) | unknown | device-control | name-only |
| `Draw/SendRemote` | Send a previously-uploaded cloud image (referenced by `FileId`) to the device, with author/head metadata for attribution display. | `AuthorHeadId`, `AuthorId`, `AuthorNickName`, `FileId`, `ImageName`, `LcdArray` (int[]), `SoundFileId` | (base only) | device-control | decompiled |
| `Draw/SetColorListV2` | Overwrite the color list of an existing saved palette. | `ColorList` (List\<String\>), `PaletteId` (int) | (base only) | device-control | decompiled |
| `Draw/SetInfo` | Set text/caption overlay info to be drawn together with the current pixel image (text, color, font, size, effect, start position/frame size, scroll speed) on one or more LCD-indexed screens. | `LcdArray` (int[]), `PicEffect` (int), `Text` (string), `TextColor` (string), `TextEffect` (int), `TextFont` (int), `textFrameHeight` (int), `TextFrameWidth` (int), `TextSize` (int), `TextSpeed` (int), `TextStartX` (int), `TextStartY` (int) | (base only) | device-control | decompiled |
| `Draw/SetPaletteColor` | Implied by name: set an individual color slot within a palette (sibling of `SetColorListV2`, which replaces the whole list). No request/response class or call site exists anywhere in the decompiled sources — only the bare `HttpCommand` string constant. | unknown | unknown | device-control (unconfirmed) | name-only |
| `Draw/SetPaletteIndexV2` | Select which saved palette (by list index) is the "active" one in the pixel-art editor. | `Index` (int) | (base only) | device-control | decompiled |
| `Draw/SetScroll` (`HttpCommand.ScrollSet`) | Implied by name: configure image scroll behavior for the drawing (a narrower cousin of `SetSpeedMode`'s `ScrollMode`/`Speed` fields). No request/response class or call site exists anywhere in the decompiled sources — only the bare string constant. | unknown | unknown | device-control (unconfirmed) | name-only |
| `Draw/SetSpeedMode` | Set the scroll mode and speed for the current drawing/animation on one or more LCD-indexed screens. | `LcdArray` (int[]), `ScrollMode` (int), `Speed` (int) | (base only) | device-control | decompiled |
| `Draw/UpLoadAndSend` | Upload a drawn image (with author/head metadata) directly to the device without going through the cloud-file `FileId` indirection that `SendRemote` uses. Request class exists with full fields but no instantiation site was found in the decompiled sources. | `AuthorHeadId`, `AuthorId`, `AuthorNickName`, `ImageName`, `LcdArray` (int[]) | unknown | device-control | name-only |
| `Draw/UpLoadEqAndSend` | Implied by name: the EQ/audio-visualizer counterpart of `UpLoadAndSend`. No request/response class or call site exists anywhere in the decompiled sources — only the bare string constant, no field signal at all. | unknown | unknown | device-control (unconfirmed) | unknown |
| `Led/SendData` | Send raw LED marquee/strip data to the device. Request class exists with one field but no call site was found. | `LedData` (string, likely base64/hex-encoded LED frame data) | unknown | device-control | name-only |
| `Led/SetText` | Set the scrolling text and speed shown on an LED marquee/text-strip device. Request class exists but no call site was found. | `Text` (string), `TextSpeed` (int) | unknown | device-control | name-only |
| `Led/SetTextSpeed` | Change only the scroll speed of the current LED marquee text. Request class exists but no call site was found. | `Speed` (int) | unknown | device-control | name-only |
| `Led/Stop` | **Device→app MQTT push.** Device reports the LED-marquee mode has exited/stopped (matched against the current user id via `DrawSyncResponse.UserId`); app fires an internal "exit LED" event. | (push payload) `UserId` (int) — parsed as `DrawSyncResponse` | n/a (push) | device-control | decompiled |
| `Lyric/Enter` | Enter lyric-display mode on the device (plain command, no extra fields). | (base only) | (base only) | device-control | decompiled |
| `Lyric/GetConfig` | Fetch the current lyric-display config (background style, text effect). | (base only) | `Background` (int), `TextEffect` (int) | device-control | decompiled |
| `Lyric/SetConfig` | Set the lyric-display background style and text effect. | `Background` (int), `TextEffect` (int) | (base only) | device-control | decompiled |
| `Mixer/Start` | Start the "mixer" feature (starts an audio-reactive/EQ session; `IsConnectAudio` defaults to 0 in the request constructor). Request class exists but no call site was found in the decompiled sources. | `IsConnectAudio` (int) | unknown | device-control | name-only |

## Unknown / no signal

Commands with genuinely no request/response class and no field signal anywhere in the decompiled
sources beyond the bare `HttpCommand` string constant:

- `Draw/UpLoadEqAndSend` — no request/response class, no call site; purpose inferred only from the
  name (presumed EQ counterpart of `Draw/UpLoadAndSend`).

Note: `Draw/SetPaletteColor` and `Draw/SetScroll` are also class-less/caller-less (see table rows
above, marked "name-only" / "unconfirmed") but their purpose is reasonably inferable from adjacent,
confirmed sibling commands (`SetColorListV2`, `SetSpeedMode`), so they were kept in the main table
rather than this bucket.
