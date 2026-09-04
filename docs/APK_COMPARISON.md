# APK Protocol & Encoding Comparison

**Purpose:** Byte-level comparison of our encoding/streaming against the
decompiled Divoom Android app (`references/apk/`). The APK is the
authoritative reference; divergences are noted and categorized by risk.

**Sources:**
- Our code: `divoom_lib/display/animation.py`, `animation_8b.py`,
  `divoom_lib/utils/divoom_image_encode.py`, `divoom_image_encode_32.py`,
  `divoom_lib/framing.py`, `ble_transport.py`
- APK: `references/apk/decompiled_src/sources/com/divoom/Divoom/bluetooth/`
  (`s.java`, `q.java`, `CmdManager.java`, `DesignSendModel.java`,
  `NDKMain.java`, `HotUpdateHandle.java`)
- Third-party refs: futpib, hass-divoom (marked where used)

---

## 1. Executive Summary

| Component | Status | Risk | Evidence |
|-----------|--------|------|----------|
| **0x8B START payload** `[0x00][size:4 LE]` | [OK] MATCH | none | APK `CmdManager.n()` line 1525, our `_phase_start()` |
| **0x8B DATA payload** `[0x01][size:4 LE][idx:2 LE][≤256 bytes]` | [OK] MATCH | none | APK `h.f()` with `f30416i=true`, our `_phase_data()` |
| **0x8B chunk size** 256 bytes | [OK] MATCH | none | APK `hVar.q(256)`, our `SENDING_DATA_CHUNK_SIZE` |
| **Frame body header:** `AA LLLL TTTT RR NN` | [OK] MATCH | none | APK native `NDKMain.pixelEncode()` output, our `encode_animation_frame()` |
| **Color palette:** 3-byte RGB, first-seen order | [OK] MATCH | none | APK `W2.c.F()` `bArr.length % 768`, our palette construction |
| **Pixel data:** LSB-first continuous bit pack | [OK] MATCH | none | RomRider protocol (both derive from same spec) |
| **0x49 packet index** `PACKET_NUM u8` | [OK] MATCH | resolved R38 | APK `e3/h.java` `f()` loop starts at **i12=0** (0-based). Our code now starts at **0** (Python `packet_num=0`, C `packet_num=0`). |
| **0x49 total_len + index field sizes** (16px: 2B+1B; 32px: 4B+2B) | [OK] MATCH | none | APK `e3/h.java` lines 164-168: `i9={2,4}`, `i11={1,2}` by screen mode. Our code matches. |
| **BLE wire framing** | [NO] DIFFERENT | low (transport) | Our: iOS LE `FE EF AA 55 ... CMD ... CK CK 02`. APK: SPP Basic `01 LL LL CMD ... CK CK 02`. Both preserve same cmd+payload. |
| **0x8B TERMINATE (CW=2)** | [NO] EXTRA (removed R35d) | resolved | APK does NOT send terminate — verified on 4 hardware devices (Timoo SPP, Ditoo BLE, Tivoo Max BLE, Pixoo BLE). Removed. |
| **32x32 pre-frames (0x05/0x06)** | [NO] NOT IN APK | **high** | `0x05` and `0x06` only appear as **SPP escape sequences** (`s.java` `l()` method), NOT as pre-frames. Our pre-frames come from **hass-divoom**. No APK code path sends them. |
| **32x32 frame header RR=0x03, 2-byte NN** | [NO] NOT IN APK | **high** | APK uses same `AA LLLL TTTT RR NN` format via `NDKMain.pixelEncode()` for ALL sizes (`RR=0x00`, 1-byte NN). Our RR=0x03, 2-byte NN come from **hass-divoom**. |
| **APK BlueHigh encoding (`pixelEncodeBlueHigh`)** | [NO] NOT IMPLEMENTED | medium | APK has a SEPARATE native encoding path for high-res (Pixoo Max): header byte `0x25`/`0x2A` + `rowCnt`/`columnCnt`. We don't use this — our AA format matches the standard `pixelEncode()` path. |
| **Color quantization** (>256 colors) | [NO] MISSING | low | APK native has `colorQuantityV1/V2`. We raise ValueError. OK as long as callers pre-quantize. |
| **0x8B device-ready wait** | [OK] FIXED (R35) | none | `_expected_response_command` now set before START so iOS LE notification handler routes device's `[0]` ACK. |
| **0x8B retransmit serving** `[1][idx:2 LE]` | [WARN] TIMING DIFF | low | Our: post-stream poll loop (1s quiet timeout). APK: event-driven, interleaved with initial send. |
| **Inter-chunk delay** | [NO] DIFFERENT | low | Our: 10ms BLE + GATT ACK pacing. APK: 40ms SPP sleep. Both effective. |

---

## 2. Frame Body Format — Byte-by-Byte

### 2.1 Static Image (`encode_static_image`)

| Offset | Size | Field | Our value | APK value | Match |
|--------|------|-------|-----------|-----------|-------|
| 0 | 1 | AA | `0xAA` | Native output includes `0xAA` | [OK] |
| 1-2 | 2 | LLLL | LE u16 = `6 + 3*N + pixel_bytes` | Same | [OK] |
| 3-5 | 3 | padding | `0x00 0x00 0x00` | Same | [OK] |
| 6 | 1 | NN | u8 (0=256) | `(byte)n` | [OK] |
| 7.. | N*3 | COLOR_DATA | R G B, first-seen | Same | [OK] |
| ... | P | PIXEL_DATA | LSB-first bit pack | Same | [OK] |

Header is 6 bytes (no TTTT, no RR, 3 zero bytes where TTTT+RR would be).

### 2.2 Animation Frame (`encode_animation_frame`, 16x16)

| Offset | Size | Field | Our value | APK value | Match |
|--------|------|-------|-----------|-----------|-------|
| 0 | 1 | AA | `0xAA` | Native output includes `0xAA` | [OK] |
| 1-2 | 2 | LLLL | LE u16 = `7 + 3*N + pixel_bytes` | Same | [OK] |
| 3-4 | 2 | TTTT | LE u16, display time in ms | Same (from `speed` param to `pixelEncode`) | [OK] |
| 5 | 1 | RR | `0x00` (reset palette) | Native handles | [OK] (for 16x16) |
| 6 | 1 | NN | u8 (0=256) | `(byte)n` | [OK] |
| 7.. | N*3 | COLOR_DATA | R G B, first-seen | Same | [OK] |
| ... | P | PIXEL_DATA | LSB-first bit pack | Same | [OK] |

Header is 7 bytes.

### 2.3 Animation Frame (`encode_animation_frame_32`, 32x32) — DEPARTURE FROM APK

**APK standard path** (`NDKMain.pixelEncode()`, used for all sizes on most devices):
```
Same AA LLLL TTTT RR NN format as 16x16:
  [0xAA][LLLL LE u16][TTTT LE u16][0x00][NN u8][COLOR_DATA][PIXEL_DATA]
Header is 7 bytes. RR=0x00, NN=1 byte, same as 16x16.
```

**Our 32x32 path** (`encode_animation_frame_32`, from hass-divoom):
```
  [0xAA][LLLL LE u16][TTTT LE u16][0x03][NN_NN LE u16][COLOR_DATA][PIXEL_DATA]
Header is 8 bytes. RR=0x03, NN=2 bytes (u16).
```

**APK BlueHigh path** (`NDKMain.pixelEncodeBlueHigh()`, for Pixoo Max 32x32+):
```
APK header before calling native:
  header = {0x25, validCnt, speed>>8, speed&255, rowCnt, columnCnt}
  For 32x32: {0x25=37, 1, speed_hi, speed_lo, 2, 2}
Native output: (unknown internal format, wrapped with header)
```

**Verdict:** Our RR=0x03 and 2-byte NN come from **hass-divoom**, not the APK.
The APK's standard `pixelEncode()` produces the same 7-byte AA format for
ALL display sizes. The BlueHigh path (0x25 format) is separate and we
don't use it. Test on hardware: does RR=0x00 + 1-byte NN work for 32x32?

### 2.4 32x32 Pre-Frames — NOT IN APK

**Our pre-frames** (from hass-divoom):
```
Pre-frame 1: [0xAA] [0x05 0x00] [0x00 0x00 0x05 0x00 0x00]    (LLLL=5, body=5 bytes)
Pre-frame 2: [0xAA] [0x06 0x00] [0x00 0x00 0x06 0x00 0x00 0x00]  (LLLL=6, body=6 bytes)
```

**APK finding:** `0x05` and `0x06` only appear in `s.java` `l()` method as
**SPP escape sequences** (byte-stuffing for old-mode framing):
- `0x01` → `[0x03, 0x04]`  (escape for SPP start byte)
- `0x02` → `[0x03, 0x05]`  (escape for SPP end byte)
- `0x03` → `[0x03, 0x06]`  (escape for SPP escape byte)

No APK code path sends a `0x05` or `0x06` byte as a "pre-frame" before pixel
data. The APK's 32x32 encoding either:
1. Goes through standard `pixelEncode()` → standard AA format (no pre-frames)
2. Goes through BlueHigh `pixelEncodeBlueHigh()` → 0x25/0x2A header (no pre-frames)

**To verify on hardware:** Remove the two pre-frames from
`divoom_image_encode_32.py` and test a 32x32 animation. If it works, the
pre-frames are unnecessary for this device/firmware.

---

## 3. Packetization Formats

### 3.1 0x8B Animation Stream

APK source: `CmdManager.n()` → `e3.h.g()` / `e3.h.f()` → `s.c()`.
Our source: `animation_8b.py` → `stream_animation_8b` in `animation.py`.

**START:**
```
APK:   q.s().F(s.c(SPP_APP_NEW_GIF_CMD2020, [0x00] + file_size(4 LE)))
Ours:  send_command(0x8B, [0x00] + file_size(4 LE), write_with_response=False)
```
MATCH. Wire payload is `[0x00][size:4 LE]`.

**DATA (N packets):**
```
APK:   hVar.l([0x01]), hVar.i(true), hVar.q(256)
       → f30412e = {1}  (control word in prefix)
       → f30416i = true  (4-byte total_len, 2-byte index)
       → f30418k = 256   (chunk size)
       Payload: [0x01][file_size:4 LE][chunk_idx:2 LE][data:≤256 bytes]

Ours:  [0x01][file_size:4 LE][offset_id:2 LE][chunk:≤256 bytes]
```
MATCH. Same control word, same size/idx fields, same chunk max.

**TERMINATE:**
```
APK:   NOT SENT
Ours:  [0x02] after 0.5s settle
```
DIVERGENCE. APK relies on `file_size` in START to know length. Our
extra byte is tolerated by tested hardware but may confuse other firmware.

**Chunk index semantics (load-bearing):**
```
APK:   chunk_idx is a sequential index (0, 1, 2, ...)
       Device places chunk N at byte N*256 in reconstructed file.
Ours:  offset_id is the same sequential index (0, 1, 2, ...)
```
MATCH. This was the root cause of the R11 stall bug (was byte offset,
not chunk index).

### 3.2 0x49 Chunked Animation (legacy)

APK source: `CmdManager.o()` → `e3/h.java` `f()` method.
Our source: `image_encode.c` `_py_encode_animation`.

```
APK:   TOTAL_LEN(i9 bytes LE) + PACKET_NUM(i11 bytes LE, 0-based) + chunk(≤chunk_size bytes)
Ours:  TOTAL_LEN(LE u16) + PACKET_NUM(u8, 1-based) + chunk(≤200 bytes)
```

**Packet index counter — CONFIRMED 0-based in APK.**
APK `e3/h.java` line 178-179:
```java
for (int i12 = 0; i12 < iCeil; i12++) {
    byte[] bArrC = L.c(L.b(L.d(L.d(bArrB, length, i9, false),
         i12, i11, false), ...), ...);
```
The loop iterates `i12 = 0, 1, 2, ...` and encodes it directly. **Our 1-based
counter is wrong.** Should be fixed to 0-based.

**Field sizes:**

| Screen size | APK `i9` (total_len) | APK `i11` (index) | Our total_len | Our index |
|-------------|----------------------|-------------------|---------------|-----------|
| 16px | 2 bytes LE u16 | 1 byte u8 | 2 bytes LE u16 | 1 byte u8 (1-based [NO]) |
| 32px+ | 4 bytes LE u32 | 2 bytes LE u16 | 4 bytes LE u32 (via C) | 2 bytes LE u16 |

**Chunk size:**
- APK default: `f30418k = 200` bytes (set in `e3/h.java`)
- APK 0x8B path: `hVar.q(256)` → 256 bytes
- Our 0x49 path: 200 bytes — MATCHES APK default
- Our 0x8B path: 256 bytes — MATCHES APK

**To fix:** Change `packet_num` from 1-based to 0-based in the 0x49 encoder
(`image_encode.c` and Python fallback).

### 3.3 0x44 Static Image

APK source: `CmdManager.l()`.
Our source: `sender_protocol.py` `encode_static_image`.

```
APK:   Prefix: [0x00, 0x0A, 0x0A, 0x04]
       Data:   [0xAA][LLLL][0x00 0x00 0x00][NN][COLOR_DATA][PIXEL_DATA]

Ours:  Same prefix, same frame body format
```
MATCH.

---

## 4. BLE Framing Layer

### 4.1 APK SPP Basic Protocol (`s.k()` / `s.l()`)

Format used over classic Bluetooth RFCOMM:
```
Offset  Size  Description
------  ----  -------------------------------
  0      1    0x01 (start byte)
  1-2    2    LL LL = (packet_len - 4) LE u16
  3      1    Command ID byte
  4..n-3 ?    Payload (command-specific)
  n-2..n-1 2  CRC: sum(bytes 1..n-3) LE u16
  n      1    0x02 (end byte)
```

Old mode `s.l()` additionally byte-stuffs values 1, 2, 3 in payload.

### 4.2 Our iOS LE Protocol (`encode_ios_le_payload`)

Format used over macOS BLE GATT (from APK `com.divoom.Divoom.bluetooth.c#b`):
```
Offset  Size  Description
------  ----  -------------------------------
  0-3    4    0xFE 0xEF 0xAA 0x55 (header)
  4-5    2    Length = total_bytes - 7, LE u16
  6      1    Packet number (low byte)
  7      1    Command ID byte
  8..n-3 ?    Payload (command-specific, WITHOUT command id)
  n-2..n-1 2  CRC: sum(bytes 4..n-3) LE u16
  n      1    0x02 (end byte)
```

Both wrap the same CMD+PAYLOAD in different envelopes. The payload bytes
(cmd args) are identical between the two formats.

### 4.3 Our SPP (BT Classic) Path

When `use_spp=True`, we use `encode_basic_payload` which matches the
APK's SPP Basic Protocol format exactly (`01 LL LL CMD ... CK CK 02`).

---

## 5. Display Pipeline vs APK

The full chain for showing a GIF on device:

### Our path (`show_image` → `stream_animation_8b`)

```
show_image(path)
  → show_design(name, channel=0x05)    # switch to display channel
    → send_command(0x45, [0x05])
  → process_image(path)
    → resize to device resolution
    → encode frames via encode_animation_frame / encode_animation_frame_32
  → _build_animation_blob(frames)       # concatenate frame bodies
  → Animation.stream_animation_8b(blob) # 3-phase 0x8B send
```

### APK path (`DesignSendModel` → BLE)

```
DesignSendModel.sendToOneDevice(pixelBean)
  → CmdManager.h(pixelBean)            # encode
    → NDKMain.pixelEncode(rawRGB, speed, width, null...)
      # Returns encoded byte[] with AA LLLL TTTT RR NN ... format
    → e3.h.g(encodedData) → list of 256-byte chunks
  → CmdManager.n(pixelBean)            # send via 0x8B
    → q.s().F(s.c(0x8B, [0x00, size:4 LE]))   # START
    # Returns chunk list; stored in pixelCacheList
    # Later (device-driven): startSendAllAni() sends all chunks
  → DesignSendModel.startSendAllAni()  # triggered by device [0] ACK
    → q.s().o()                        # clear queue
    → for each chunk: q.s().F(chunk)   # fire-and-forget, 40ms delay
```

### Key differences

| Aspect | Our path | APK path |
|--------|----------|----------|
| **Channel switch** | `show_design()` via 0x45, hardcoded to channel 5 | APK can switch to channel 1 (clock) or 5 (display) |
| **Encoder** | Python/C `encode_animation_frame` | Native NDK `pixelEncode()` |
| **Chunking** | On-the-fly during stream | Pre-chunked before START |
| **Device-ready gate** | Bounded `_await_8b_device_ready(2s)` | Indefinite reactive wait |
| **Send trigger** | Immediate after START+wait | Device's `[0]` response calls `startSendAllAni()` |
| **First data delivery** | ~200ms-2s (device-ready ACK) | Immediate on device request |
| **Retransmits** | Post-stream poll loop | Event-driven, any time |
| **Chunk resend method** | Re-read from source blob | `q.s().z()` immediate from `pixelCacheList` |
