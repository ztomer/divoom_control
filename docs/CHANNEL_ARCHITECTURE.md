# Divoom Channel Architecture

## Priority

**APK takes precedence.** The official Divoom Android app (`references/apk/`) is the authoritative protocol reference. Third-party implementations are secondary sources; they may use different code paths that work on specific devices but should not override APK behavior unless hardware-tested.

| Source | Role | Authority |
|--------|------|-----------|
| **APK decompile** (`references/apk/`) | Official Divoom Android app | **Authoritative** — protocol, UI toggles, canonical payloads |
| **hass-divoom** (`references/divoom-refs/hass-divoom/`) | Mature Home Assistant integration | **Secondary** — proven on real Pixoo/Tivoo/Ditoo/Timebox hardware, may use different byte layouts for same channel (proven to work but not canonical) |
| **futpib** (`references/divoom-refs/futpib/`) | Rust CLI | **Tertiary** — clean-room protocol implementation, differs in structure (see footnotes) |

This document notes **every place our library diverges from the APK**, and why. Different devices (Pixoo, Pixoo Max, Timebox, Aurabox, Ditoo) may require different code paths — see device-specific notes throughout. **The APK format is always the canonical first choice; fall back to hass-divoom/futpib only when APK format fails on a target device.**

---

---

## Overview

The Divoom device has two distinct mode-switching concepts:

1. **Light mode (channel)** — what the display shows (clock, weather, visualizer, etc.)
2. **Work mode** — how the device operates (BT, FM radio, Line-in, SD card, USB audio)

All **light mode** switching uses a single BLE command: `SPP_SET_BOX_MODE` (`0x45`).

---

## Cross-Reference: Channel IDs — CONFIRMED (all sources agree)

The first byte of the `0x45` payload selects the channel:

| ID | APK | hass-divoom | futpib¹ |
|----|-----|-------------|---------|
| `0x00` | CLOCK | clock | — |
| `0x01` | TEMPRETURE | light/temp | Light |
| `0x02` | COLOR_LIGHT | light (TBM/Aurabox) | Hot |
| `0x03` | SPECIAL_LIGHT | effects | Special |
| `0x04` | SOUND_LIGHT | visualization | Music |
| `0x05` | SOUND_USER | design | — |
| `0x06` | MUSIC | lyrics/scoreboard | — |

¹ futpib uses a **different** channel numbering from APK/hass-divoom. Its first byte is:
- `0x01` = `BoxMode::Light` with sub_modes: 0=clock, 1=temp, 2=color, 3=special, 4=sound, 5=sound-user, 6=music. All produce `[0x01, sub_mode, ...]`.
- `0x02` = `BoxMode::Hot`
- `0x03` = `BoxMode::Special`
- `0x04` = `BoxMode::Music`
- No named variant produces `0x00`, `0x05`, or `0x06` as the first byte.

**Verdict: IDs 0x00–0x06 are universal between APK and hass-divoom. futpib uses an independent 0x01–0x04 scheme with Light sub-modes covering the same capabilities.**

---

## CLOCK channel

### 6-byte format (`t2(CLOCK, l, m, n, o)` — APK only)

Used by `LightViewModel.o()` (`LightViewModel.java:167-172`). This is the **simple** channel switch: just time format + digit color, no overlays.

| Offset | APK field | DB column | Meaning |
|--------|-----------|-----------|---------|
| 0 | `0x00` | — | CLOCK mode identifier |
| 1 | `f10919l` | `time_type` | 0 = 12-hour, 1 = 24-hour |
| 2 | `f10920m` | `time_r` | Clock digit Red (0-255) |
| 3 | `f10921n` | `time_g` | Clock digit Green (0-255) |
| 4 | `f10922o` | `time_b` | Clock digit Blue (0-255) |
| 5 | `0x00` | — | Padding |

### 10-byte "ENV_MODE" format (`CmdManager.C2()` — APK only)

Used by `LightViewModel.x()` (`LightViewModel.java:219-223`). This is the **rich** clock config with overlay toggles.

| Offset | APK field | DB column | Meaning |
|--------|-----------|-----------|---------|
| 0 | `ENV_MODE` | — | Always `0x00` |
| 1 | `time_type` | `time_type` | Clock face category (0=12h, 1=24h) |
| 2 | `time_show_mode` | `time_show_mode` | 0-based clock face index (0-14) |
| 3 | `time_check[0]` | `time_check[0]` | Unknown (set to 1 by `s.java` read-back decoder) |
| 4 | `time_check[1]` | `time_check[1]` | **Humidity** overlay (0=off, 1=on) |
| 5 | `time_check[2]` | `time_check[2]` | **Weather** overlay (0=off, 1=on) |
| 6 | `time_check[3]` | `time_check[3]` | **Date/Number** overlay (0=off, 1=on) |
| 7 | `time_r` | `time_r` | Clock color Red |
| 8 | `time_g` | `time_g` | Clock color Green |
| 9 | `time_b` | `time_b` | Clock color Blue |

**Note:** This 10-byte format is ONLY found in the APK. Neither hass-divoom nor futpib use it.

### 10-byte "legacy" format (hass-divoom + our library — NOT in APK)

Both **hass-divoom** (`divoom.py:533-561`) and **our library** (`divoom_lib/display/__init__.py:25-51`) use an **identical** 10-byte format:

| Offset | hass-divoom / our lib | Meaning |
|--------|----------------------|---------|
| 0 | `0x00` | Clock mode |
| 1 | `twentyfour` (0/1) | 24-hour flag |
| 2 | `clock_style` (0-15) | Clock face index |
| 3 | `0x01` | Clock activated |
| 4 | `weather` (0/1) | Weather overlay |
| 5 | `temp` (0/1) | Temperature overlay |
| 6 | `calendar` (0/1) | Calendar/date overlay |
| 7 | R | Color Red |
| 8 | G | Color Green |
| 9 | B | Color Blue |

**This is a DIFFERENT byte layout from the APK's `CmdManager.C2()`. Our library diverges from the APK here — see §Divergences below.**

| Byte | APK C2() | hass-divoom / our lib | Conflict? |
|------|----------|----------------------|-----------|
| 4 | humidity | **weather** | [conflict] Byte 4 = different meaning |
| 5 | weather | **temp** | [conflict] Byte 5 = different meaning |
| 6 | date/number | **calendar** | [same] Same concept |

**Verdict: APK C2() is the canonical format. Our existing `show_clock()` uses a hass-divoom-compatible format that's proven on real hardware but is a deliberate protocol divergence (see §Divergences).** Whether the device interprets bytes 4-6 as humidity/weather/date (APK) or weather/temp/calendar (hass-divoom) depends on which byte layout is sent — the device firmware follows the APK spec. Strategy: keep our existing `show_clock()` as the hass-divoom-compatible path (proven on Pixoo). Add the APK's `C2()` layout as a separate `set_clock_rich()` API — prefer this for future implementations since it matches the vendor app.

---

## TEMPRETURE channel — CONFIRMED (APK + hass-divoom agree)

The payload is `[0x01, unit, R, G, B, 0x00]`.

| Offset | APK field | hass-divoom field | Meaning |
|--------|-----------|-------------------|---------|
| 0 | `0x01` | `0x01` | TEMPRETURE mode |
| 1 | `temp_type` | `0x00/0x01` | 0 = Celsius, 1 = Fahrenheit |
| 2 | `temp_r` | R | Display color Red |
| 3 | `temp_g` | G | Display color Green |
| 4 | `temp_b` | B | Display color Blue |
| 5 | `0x00` | `0x00` | Padding |

**Confirmed by:**
- APK: `t2(TEMPRETURE, d, p, q, r)` → `{0x01, d, p, q, r, 0}` (`CmdManager.java:1721`)
- hass-divoom: `TimeboxMini.show_temperature()` → `[0x01, unit, R, G, B, 0x00]` (`timeboxmini.py:143-152`)
- hass-divoom: `Aurabox.show_temperature()` → `[0x01]` + separate `set temp unit` (`aurabox.py:176-188`)
- futpib: `Light{ sub_mode: 1, color, brightness, on }` → `[0x01, sub_mode(0-6), R, G, B, brightness, on, 0, 0, 0]` — **10-byte variant** with brightness/on. Different from APK's 6-byte format.

**Device variation:** Aurabox/TimeboxMini use `[0x01]` bare (no color/unit). The base Divoom class delegates to `show_clock()` + `set temp type` (0x2B). futpib uses a **10-byte** format with brightness/on bytes.

For our Pixoo/Pixoo Max target, the APK's 6-byte `[0x01, unit, R, G, B, 0x00]` is the correct format. The 10-byte variant (from futpib) may also work — try the 6-byte first since it's what the APK uses.

> **Divergence in our library:** `show_temperature()` does **not exist** in `divoom_lib/display/`. Our `Weather.set()` sends 0x5F data only — there is no 0x45 channel switch to TEMPRETURE mode.
> 
> **R26 will fix this.** The daemon `api_channels.py` will implement `set_temperature_channel()` using the APK-canonical byte layout: `[0x01, temp_type, R, G, B, 0x00]`. The earlier "cyan screen" with this format was a device-state issue (missing 0x5F data after switch), not a byte-order problem. The APK is ground truth.

---

## Weather data push (0x5F) — CONFIRMED (APK + hass-divoom + our lib agree)

All sources send `[signed_temp_byte, weather_code]` on command `0x5F`.

**APK source:** `CmdManager.q1(byte netTemp, byte typeDemo)` → `SPP_SEND_CUR_NET_TEMP(95)` = `0x5F` with `[netTemp, typeDemo]`.

| Offset | Meaning | Range |
|--------|---------|-------|
| 0 | Temperature (signed byte, two's complement) | -127..128 |
| 1 | Weather type code | 1..18 |

**Weather codes** — two different mappings exist:

### APK mapping (from `WeatherUtils.returnType()`, OpenWeatherMap icon codes)

| Code | Condition |
|------|-----------|
| 1 | Clear sky (day) |
| 2 | Few clouds (day) |
| 3 | Scattered clouds (day) |
| 4 | Broken/overcast clouds (day) |
| 5 | Shower rain (day) |
| 6 | Rain (day) |
| 7 | Thunderstorm (day) |
| 8 | Snow (day) |
| 9 | Mist/fog (day) |
| 10 | Clear sky (night) |
| 11 | Few clouds (night) |
| 12 | Scattered clouds (night) |
| 13 | Broken clouds (night) |
| 14 | Shower rain (night) |
| 15 | Rain (night) |
| 16 | Thunderstorm (night) |
| 17 | Snow (night) |
| 18 | Mist/fog (night) |

### hass-divoom / our library mapping (subset, from `node-divoom-timebox-evo`)

Our `WeatherType` enum and hass-divoom's `WEATHER_MODES` both use this subset:

| Code | Condition |
|------|-----------|
| 1 | Sunny / Clear |
| 3 | Cloudy / CloudySky |
| 5 | Thunderstorm / Lightning |
| 6 | Rain / Rainy |
| 8 | Snow / Snowy |
| 9 | Fog |

**Note:** codes 2, 4, 7, 10-18 exist in the APK but are not mapped by hass-divoom or our library. Our library should either adopt the APK's full set or validate that the 6-code subset maps correctly on the target device.

---

## COLOR_LIGHT channel — device-specific mapping

APK: `v2(COLOR_LIGHT, f, g, h, i, y)` → `[0x02, f, g, h, i, y]`.

hass-divoom `show_light()` device variations:
- **Base Divoom class:** `[0x01, R, G, B, brightness, mode, on, 0, 0, 0, 0]` — channel 1.
- **TimeboxMini / Aurabox overrides:** `[0x02, R, G, B, ...]` — channel 2.

Different devices map color light to different channel IDs (1 or 2). The APK always uses channel 2.

---

## SPECIAL_LIGHT channel — CONFIRMED

| Source | Payload |
|--------|---------|
| APK `s2(SPECIAL_LIGHT, e)` | `[0x03, effect_id]` |
| hass-divoom `show_effects(n)` | `[0x03, number]` |
| futpib `Special{ sub_type }` | `[0x03, sub_type]` |

All agree: `[0x03, effect_index]`.

---

## SOUND_LIGHT / MUSIC channels

APK: SOUND_LIGHT = `[0x04, 7 params]`, MUSIC = `[0x06, 0, 0, 0, 0, 0]`.

hass-divoom: visualization = `[0x04, number]` (1 param only). Lyrics/scoreboard = `[0x06, ...]`.

futpib: `Light{ sub_mode: 4 }` for sound, `Music{ sub_type }` for music (`[0x04, sub_type, 0*8]`).

All consistent.

---

## Clock face selection — TWO competing protocols

### Method 1: APK 10-byte `C2()` (0x45 with `time_show_mode` at byte 2)

The APK's `LightClockFragment` sets `time_show_mode` (byte 2) in the 10-byte ENV_MODE payload. Valid range: 0-14 (15 clock faces).

### Method 2: Extended command 0xBD/0x14 (futpib)

futpib sends `SET_USER_DEFINE_TIME` (extended command `0xBD`, sub-command `0x14`) with a 2-byte LE `clock_id`. This is a COMPLETELY DIFFERENT protocol path.

Only method 1 is in the APK. Method 2 is unique to futpib (and possibly other reverse-engineering efforts). Our library should use method 1 (via `CmdManager.C2()`).

---

## The two-model split (`m` vs `k`)

Only in the APK. External references don't have this — they use simple function calls.

| Model | DB table | APK accessor | Used for |
|-------|----------|-------------|----------|
| `m` | `LightInfo` | `LightViewModel.c()` | Simple channel params (temp_type, temp_RGB, clock_type, clock_RGB) |
| `k` | `LightCache` | `LightViewModel.f()` | Rich clock config (time_show_mode, time_check[4]) |

---

## BLE pacing / interleaving — CONFIRMED across all sources

| Source | Timing |
|--------|--------|
| APK `CmdManager.B3()` | 100ms delay (`j7.j.e0(100L, ...)`) before starting commands |
| futpib `lib.rs` | 200ms sleep between animation packets |
| Our library `BLETransport.send_payload()` | 50ms minimum inter-write pacing |
| hass-divoom `send_payload()` | `select.select(..., 0.1)` = 100ms socket-ready wait |

The 50-200ms range is consistent. The critical gap remains: **no mechanism protects multi-phase sequences (0x8B start/data/terminate) from interleaving.**

- **futpib** avoids interleaving trivially: it reconnects BLE for each command (`connect → fire_and_forget → disconnect`), so only one command exists per connection.
- **hass-divoom** uses WiFi SPP with a persistent TCP socket — commands serialize naturally over the stream socket, but multi-phase operations still have no atomic guard.
- **Our daemon** keeps a persistent BLE connection + event loop. The `_write_lock` serializes individual GATT writes but does NOT protect multi-phase sequences. Interleaving is a real risk when a channel switch (0x45) arrives during an animation push (0x8B).

---

---

## Divergences from APK in our library

Our code intentionally deviates from the APK in several places. Each is documented here with rationale.

| # | Area | Our library | APK (canonical) | Impact |
|---|------|-------------|-----------------|--------|
| 1 | **CLOCK 10-byte format** | hass-divoom layout: `[0x00, 24h, style, 1, weather, temp, calendar, R, G, B]` | C2() layout: `[0x00, time_type, time_show_mode, ?, humidity, weather, date, R, G, B]` | Different overlays at bytes 4-6. Our format is proven on Pixoo; APK format is canonical for future code. |
| 2 | **TEMPRETURE channel switch** | **Not implemented.** `Weather.set()` sends 0x5F data only. No 0x45/0x01 channel switch exists. | `t2(TEMPRETURE, temp_type, R, G, B)` → `[0x01, temp_type, R, G, B, 0x00]` (6 bytes, 0x45) | Cannot switch to standalone temperature display mode. R26 will implement using APK canonical format. |
| 3 | **Weather codes** | `WeatherType` enum: {1, 3, 5, 6, 8, 9} — 6-code subset from `node-divoom-timebox-evo`. | `WeatherUtils.returnType()`: 1-18, full OpenWeatherMap mapping with day/night variants. | Our 6 codes should map correctly on target; codes 2, 4, 7, 10-18 are valid but unmapped. |
| 4 | **Channel constant names** | `CHANNEL_ID_TIME`, `LIGHTNING`, `CLOUD`, `VJ_EFFECTS`, `VISUALIZATION`, `ANIMATION`, `SCOREBOARD` | `CLOCK`, `TEMPRETURE`, `COLOR_LIGHT`, `SPECIAL_LIGHT`, `SOUND_LIGHT`, `SOUND_USER`, `MUSIC` | **Cosmetic only** — byte values (0x00-0x06) are identical. APK names should be preferred in new code for clarity. |
| 5 | **Command naming** | `"set light mode"` (0x45), `"set temp"` (0x5F) | `SPP_SET_BOX_MODE` (0x45), `SPP_SEND_CUR_NET_TEMP` (0x5F) | **Cosmetic only** — wire bytes are identical. Command names are library-internal. |

**Guideline:** When implementing new channel functions, use the APK format as the primary code path. Add a hass-divoom-compatible fallback only when a device is known to reject the APK format.

---

## 0x8b chunked animation upload (SPP_APP_NEW_GIF_CMD2020) — APK comparison (R34 §1b)

Audited 2026-06-09 against the decompiled APK. APK sources:
`CmdManager.n(PixelBean)` (builds start + chunk packets), `e3/h.java`
(`f()` = the chunker; configured `l([1])` `i(true)` `q(256)`),
`bluetooth/s.java` (the 0x8b response handler),
`DesignSendModel.sendToOneDevice / startSendAllAni / resendBlueData`.

### Wire format — CONFIRMED IDENTICAL

| Packet | Our library (`animation.py` 0x8b handlers) | APK |
|---|---|---|
| START (CW=0) | `[0x00][file_size:4 LE]` | `[0][total_len:4 LE]` (`L.d(…, 4)`) |
| DATA (CW=1) | `[0x01][file_size:4 LE][chunk_idx:2 LE][≤256 bytes]` | `[1][total_len:4 LE][idx:2 LE][≤256]` (`i(true)` → idx 2 bytes; `q(256)`) |
| Chunk size | 256 (chunk N → byte N×256) | 256 |

One APK extra: when `DeviceFunction.f11419e0` (round-LCD devices, e.g. Times
Gate), START gains a trailing `isCircle` byte. Not relevant to our targets
(Pixoo/Tivoo/Ditoo/Timoo); add if such a device is ever supported.

### Flow — APK is DEVICE-DRIVEN (we now match on BLE, R34 §1b)

The APK does **not** sleep-and-blast. After sending START it returns the chunk
list into a cache and **waits for the device's 0x8b response**:

- response `payload[0] == 0` → "device requests the animation" →
  `startSendAllAni()` drains all cached chunks through the send queue;
- response `payload[0] == 1`, `payload[1:3]` = chunk idx (u16 LE) → "device
  requests retransmit of chunk N" → `resendBlueData(N)`.

Notably the APK sends **no CW=2 terminate** in this flow; futpib does. We keep
the terminate (hardware-validated, devices tolerate it).

Our `Animation.stream_animation_8b` (shared by `show_image` and
`stream_raw_bin_payload`, which is now a delegator) implements both APK
behaviors on BLE: after START it waits up to 3s for the ready ACK (falling back
to the legacy 0.5s sleep when no reply — older firmware/LAN/SPP), and after the
chunk loop it serves retransmit requests until the device goes quiet. A lost
chunk no longer means a permanently failed upload.

---

## Implementation status (all DONE)

The recommendations below were made when this doc was written and have since shipped:

- **Channel-switch helpers** — `set_clock_rich()` (APK C2() 10-byte format) and
  `set_temperature_channel()` (6-byte APK format) implemented in daemon RPC (R26).
- **Command queue** — ring-buffer command queue in `divoom_daemon/command_queue.py` (R27).
- **Weather push** — confirmed 0x5F only, channel switch is separate (R26 revert).
- **`show_clock()` legacy format preserved** — APK C2() added as `set_clock_rich()`;
  the two overlay layouts coexist.

---

## References

### APK
- `SppProc$LIGHT_MODE.java` — channel ID enum  
- `CmdManager.java:1721` — `t2()` 6-byte format  
- `CmdManager.java:316` — `C2()` 10-byte ENV_MODE format  
- `LightViewModel.java:167` — `o()` CLOCK 6-byte switch  
- `LightViewModel.java:191` — `s()` TEMPRETURE 6-byte switch  
- `LightViewModel.java:219` — `x()` CLOCK 10-byte rich config  
- `m.java` — LightInfo model (simple channel params)  
- `k.java` — LightCache model (rich clock config including `time_check[4]`)  
- `n.java` — LightInfo DB adapter (column names)  
- `l.java` — LightCache DB adapter (column names, `time_check` BLOB)  
- `s.java` — protocol decoder (byte offsets for reading back device state)  

### External references
- `references/divoom-refs/hass-divoom/.../devices/divoom.py` — `show_clock()` legacy 10-byte, `show_light()`, `send_weather()`, `show_temperature()`  
- `references/divoom-refs/hass-divoom/.../devices/timeboxmini.py` — `show_temperature()` [0x01, unit, R, G, B, 0x00]  
- `references/divoom-refs/hass-divoom/.../notify.py` — weather codes  
- `references/divoom-refs/futpib/src/main.rs` — BoxMode enum, 10-byte Light format with brightness  
- `references/divoom-refs/futpib/src/protocol/command.rs` — command IDs  
- `references/divoom-refs/futpib/src/protocol/packet.rs` — packet framing  

### Our library
- `divoom_lib/display/__init__.py:25-51` — `show_clock()` legacy 10-byte format  
- `divoom_lib/system/weather.py` — `Weather.set()` sends 0x5F  
- `ENGINEERING_NOTES.md` — BLE constraints
