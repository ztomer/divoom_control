# Custom Channel Push: Current Implementation vs. APK

**Status: REFERENCE.** The implementation plan below shipped across R35–R61.
This doc documents the wire formats and key differences for maintenance.

## The Problem

`sync_artwork` (gallery "Update Device") calls `divoom.display.show_image()`,
which calls `show_design()` then pushes AA-encoded frames over `0x8B`. Data
transfers correctly and the device renders it — **but on the HOT channel, not
the CUSTOM/DESIGN channel**.

Root cause: our channel-routing mechanism (`0x45 [0x05]`) is different from the
APK's (`0xBD [0x31]`), and the APK uses a different data command family
(`0x014C`/`0x8C`) instead of `0x8B` for user-define content.

## Current Code — Wire Sequence

```
show_design()                   → 0x45 [0x05, 0x00, …]
show_image() → _build_animation_blob(frames)
               → AA-format per frame: 0xAA, LLLL, TTTT, RR=0x00, NN, palette, pixel_indices
stream_animation_8b(blob)       → 0x8B [0x00, file_size:4 LE]         START
                                 0x8B [0x01, file_size:4 LE, chunk_idx:2 LE, chunk:≤256B]  DATA ×N
                                 _serve_8b_retransmits(…)              RETRANSMIT
```

## APK — Wire Sequence

APK source: `DesignSendModel.playByBlue()` → `CmdManager.y3()` + `CmdManager.n()`.

```
clear pixel cache queue            → internal (q.s().o())
stop hot update                    → 0x9F  (HotUpdateHandle.p().C())
"start gif" routing signal         → 0xBD [0x31]   (CmdManager.y3())
                                  ← SPP_DIVOOM_EXTERN_CMD
                                  ← SPP_SECOND_APP_SEND_GIF_START
[if device supports NewAniSendMode2020]:
  encode pixel data (e3.h encoder)
  send header                      → 0x014C [0x00, total_len:4 LE]
  send data packets ×N             → 0x014C [prefix, total_len, idx, suffix, chunk]
[else (old mode)]:
  send data packets ×N             → 0x49  [frames…]
```

## Key Differences

### 1. Channel Routing Signal

| Aspect | Current Code | APK |
|--------|-------------|-----|
| Command | `0x45 [0x05]` | `0xBD [0x31]` |
| Mechanism | Channel switch (set active display mode) | Extended command (signal "next data is for custom channel") |

### 2. Data Protocol

| Aspect | Current Code | APK (New Mode) | APK (Old Mode) |
|--------|-------------|----------------|----------------|
| Command | `0x8B` | `0x014C` | `0xB1` or `0x49` |
| Chunking | 256-byte, 2-byte idx | 200/256/182-byte, 1-2 idx | Full frame in one or few |
| Header | `[0x00, file_size:4 LE]` | `[0x00, total_len:4 LE]` | (none) |

### 3. Encoder

AA frame body is identical between our encoder and the APK's (verified in R35c).
Differences are all in the wrapping protocol.

## Command ID Cross-Reference

| Hex | APK Enum | Our Usage |
|-----|----------|-----------|
| `0x45` | `SPP_SET_BOX_MODE` | Channel switching (clock/visualizer/design/hot) |
| `0x8B` | `SPP_APP_NEW_SEND_GIF_CMD` | Animation stream (3-phase START/DATA/retransmit) |
| `0x49` | `SPP_SET_MUL_BOX_COLOR` | Fallback path for single-frame images |
| `0xBD` | `SPP_DIVOOM_EXTERN_CMD` | Custom channel routing |
| `0x014C` | `SPP_APP_NEW_GIF_CMD2020` | APK's new-mode animation protocol |
| `0x8C` | `SPP_APP_NEW_USER_DEFINE2020` | APK's new-mode custom art data |
| `0xB1` | `SPP_SET_USER_GIF` | APK's old-mode custom art protocol |
| `0x9F` | `SPP_HOT_PAUSE_FILE_SEND` | Stop hot update before push |

## Two Channels — Don't Conflate

| Property | DesignSendModel (drawing) | LightMakeNewModel (custom art) |
|----------|--------------------------|-------------------------------|
| Purpose | Transient display, one-shot | Persistent storage, 3×12 slots |
| Start signal | `0xBD [0x31]` | `0xBD [0x17, page]` |
| Header | `CmdManager.n()/o()` | `CmdManager.N2(page, 12-items)` |
| Data cmd | `0x8B` (new) or `0x49` (old) | `0x8C` (new) or `0xB1` (old) |
| End | No explicit terminator | `CmdManager.K0()` → `[0x02]` |
| Page select | N/A | `0xBD [0x17, page]` |

## Key Wire Formats

Old mode (`SPP_SET_USER_GIF` = 0xB1):
```
N2() header:  [0x00, 0x00, page_index]
K0() end:     [0x02]
Data chunks:  [0x01][chunk_size:2 LE][chunk_data]
```

New mode (`SPP_APP_NEW_USER_DEFINE2020` = 0x8C):
```
N2() header:  [0x00, totalLen_LE32, page_index]
K0() end:     [0x02]
Data chunks:  [0x01][total_len:4 LE][idx:2 LE][data]
```

All data chunks use the same cmd as the N2 header and K0 end for the chosen mode.

## Implementation Status

The custom art push (`custom_art_push.py` + `divoomd/src/art.rs`) and page
query (`query_page`) are **DONE**, wire-tested, and the gallery UI
(`custom_art.js`/`custom_art.css`) is shipped. The monthly-best → hot channel
push reuses `hot_update.py`. See `CHANGELOG.md` for shipped rounds.
