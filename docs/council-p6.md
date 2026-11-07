# P6.1 and P6.2 — council

The owner answered two hands items (umbrella D7 = P6.1, "snap adjacent panels
into one surface"; D8 = P6.2, "a panel on Wi-Fi as a wall slot") with one word,
"council" (2026-11-07). This file is that council: what is TRUE today, read
from the code, the decompiled vendor app and the owner's own config (no device
was written to); what each persona found, in the form the writer acts on
(severity, the defect, a concrete fix, where to look); a recommended design per
item with its first build step; and the decisions left to the owner.

How it was run: one reviewer read the facts below and wrote each persona's
findings in turn (the skill's cheap convergence form), not five independent
agents. Every fact in section 1 was checked by the coordinator against the file
it cites; persona findings are judgments over those facts, and a persona's fix
is a hypothesis until a test or the panel says otherwise.

## The owner has six decisions open

1. **What "one surface" means across panels that differ.** No two of the four
   bench panels share a pixel pitch (fact F3: 9.9, 6.9, 4.0 and 3.75 mm per
   pixel), so an image cut pixel for pixel cannot line up on the glass.
   Options: (a) **picture mode** — each panel shows the part of one picture
   its glass physically covers, resampled at its own pitch, with the bezels
   hiding what lies behind them (a window, not a mosaic); (b) **pixel mode
   only** — one-for-one cuts, allowed only between panels of equal pitch,
   which needs two panels of one model and none of the bench pairs qualify;
   (c) **both, chosen by the art kind** the daemon already carries (D14:
   a picture is scaled, pixel art is cut): a picture gets (a), pixel art gets
   (b) and is refused with its reason across unequal pitches.
   **Recommended: (c).**
2. **Animation across a joined surface.** Each panel plays its own copy on
   its own clock (fact F6); nothing in the protocol read here starts two
   panels together. Options: (a) static images only on a joined surface until
   drift is measured (M3); (b) allow animation and accept whatever drift the
   panels show; (c) build a re-sync (re-send every N minutes). **Recommended:
   (a)**, revisit with the M3 number.
3. **A panel drops out of a joined surface.** Today the others keep their
   piece and the reply names the missing one (fact F7); nothing re-sends the
   piece when it comes back. Options: (a) keep the hole, mark it on the bench,
   re-send the panel's cut when it relinks; (b) reflow the picture over the
   panels that remain; (c) blank the whole surface. **Recommended: (a).**
4. **The proving pair for the photograph.** Options: (a) Tivoo-Max + Pixoo,
   both flat square faces, pitches 6.9 and 9.9 mm — the honest test of
   picture mode; (b) Ditoo + Timoo, pitches 4.0 and 3.75 mm, nearly equal but
   neither face is a flat panel edge; (c) buy a second panel of one model and
   test pixel mode as well. **Recommended: (a)**, plus (c) only if the owner
   wants pixel art across panels at all.
5. **P6.2's premise is false: no panel in the house is a Wi-Fi panel.** The
   Timoo and the Tivoo-Max are Bluetooth-architecture models (fact F9).
   Options: (a) acquire a Wi-Fi-architecture panel — a Pixoo-64 is the one
   that also unblocks P4.8's 64x64 case; (b) move P6.2 to "Not planned" until
   one is in the house; (c) keep it BLOCKED as now. **Recommended: (b)**,
   unless the owner already means to buy one, then (a).
6. **Which Wi-Fi route, once there is a panel.** Options: (a) the vendor
   app's own `Draw/PixelLocalHttp` multipart upload to port 9000 (fact F10:
   needs a cloud-bound device, its `LocalToken`, and an encoder for the
   app's art format that this repo does not have); (b) the Pixoo-64's
   publicly documented local HTTP API (`Draw/SendHttpGif` on port 80) — not
   in `references/`, so unverified here and not to be written from memory;
   (c) probe both on the panel and keep the one that draws without the cloud.
   **Recommended: (c).**

## 1. What is true today (probed 2026-11-07, read-only)

**F1 — the bench.** Four panels are known to the daemon
(`~/.config/divoom-control/discovered_devices.json`): Pixoo-1, Tivoo-Max-light-3,
Ditoo-light-2, Timoo-light-4. Three are linked (`links.json`: Tivoo-Max, Ditoo,
Pixoo), all over Bluetooth LE (`use_ios_le_protocol: true`, `lan_ip: null` on
every one). The Timoo is placed in a different room ("Ethan") from the other
three ("Shelf") in `topology.json`. No wall is configured (`links.json`
`"wall": null`). All four are 16x16.

**F2 — the cut is right in pixels.** `divoomd/src/wall.rs` cuts one image per
slot (`cut_for`, `show_cut_image`); on 2026-10-20 a Pixoo + Timoo wall gave
exact adjacent halves, 0 of 256 pixels off per half, in grid and free-form
layouts (ROADMAP P6.1, `git show 1c13851:docs/ROADMAP.md`).

**F3 — the glass is not the chassis, and no two panels share a pitch.** The
daemon's chassis table (`divoomd/src/panel_model.rs`, `FAMILIES`, "the
products' published sizes" — not measured here) gives chassis width and the
visible screen edge:

| Panel | Chassis w (mm) | Screen (mm) | Bezel per side (mm) | Pitch (mm/px, 16 px) |
|---|---|---|---|---|
| Pixoo | 200 | 158 | 21 | 9.88 |
| Tivoo-Max | 184 | 110 | 37 | 6.88 |
| Ditoo | 90 | 64 | 13 | 4.00 |
| Timoo | 82.5 | 60 | 11.25 | 3.75 |

The table carries the screen's EDGE only, not where the screen sits in the
chassis; a Ditoo's screen sits above its keys and a Tivoo-Max's in a speaker
face, so "inset equally on every side" is false for at least two of the four.
The "21 bench px" seam recorded for Pixoo + Timoo is derived, not photographed:
(21 + 11.25) mm x 0.65 bench px/mm = 21.

**F4 — the bench draws chassis, the daemon cuts bench rectangles.**
`getWallSlots` (`divoom_gui/web_ui/spatial_rooms.js`) sizes a slot at
`enc.w_mm * 0.65`; in a free-form wall the daemon cuts that rectangle and
resizes it to the panel's 16x16 (`cut_for` with `is_free_form`). So the bezel
is INSIDE each cut: the picture behind a bezel is squeezed onto the glass
instead of being hidden, and the seam is discontinuous by both half-bezels.
The bench already knows the screen size (`spatial_stage.js` draws
`spec.screen_mm`); the cut does not use it.

**F5 — writes go to every panel at once, each on its own link.**
`each_slot` (`divoomd/src/wall/outcome.rs`) spawns one task per slot; each
task encodes its cut and streams it with `0x45 [0x05,...]` then
`stream_animation_8b` (`divoomd/src/wall.rs`). There is no barrier: each panel
shows its piece when its own stream ends.

**F6 — nothing shares a clock.** A GIF's frames go to each panel as its own
0x8B animation, which the panel loops on its own timer. No command read in
this repo or in the decompiled app starts two panels together. The vendor
app's only "multi" switch (`MultiSupportEnum`, on for one Pixoo branch at
`references/apk/decompiled_src/sources/com/divoom/Divoom/utils/DeviceFunction/DeviceFunction.java`
line 927) shows a layout in its Bluetooth settings page and was not traced
further.

**F7 — a dropped panel is named, not repaired.** The wall's reply records
each slot as accepted, failed (with the reason) or unlinked (P6.3,
`WallOutcome`); the other panels keep their piece. Nothing in
`divoomd/src/wall.rs` or `divoomd/src/wall/` re-sends a cut when a panel
relinks (no rejoin path exists).

**F8 — the LAN refusal's text is false.** `LAN_SLOT_REFUSAL`
(`divoomd/src/wall/refusal.rs`) told every client that "the Wi-Fi image upload
Divoom's own app uses is not known", and its doc comment said the method "did
not decompile". Both were corrected in the roadmap on 2026-10-20 and stayed
wrong in the code. Fixed in the commit that adds this file.

**F9 — the Timoo and the Tivoo-Max are NOT Wi-Fi panels.** The vendor app
puts a model on its Wi-Fi architecture (`WifiBlueArchEnum.WifiArchMode`) only
for Pixoo64Wifi (and `_2`, `_5G`), Pixoo16Wifi, Lcd5Wifi (and `_5G`),
PhotoFrameWifi, PhotoFrameWifiPure and PhotoSpeakerWifi (`DeviceFunction.java`
lines 1031, 1069, 1094, 1110); every other model keeps the default
`BlueArchMode` (line 720), the Timoo and the Tivoo-Max among them. The
daemon's own extracted table says the same: `divoomd/src/panel_features.rs`
gives `TIMOO` and `TivooMax` `SPEAKER | SD_CARD | VJ` and no `WIFI`. The
sentence "the Timoo and the Tivoo-Max are the Wi-Fi models" entered the
roadmap in the 2026-11-07 rework (`6a8ccbf`) and is corrected there now.

**F10 — the vendor app's Wi-Fi image path, as far as it is known.**
`DesignSendModel.sendByLocalHttp` (smali,
`references/apk/smali_src/smali/com/divoom/Divoom/view/fragment/designNew/model/DesignSendModel.smali`)
builds a `DrawPixelLocalHttpRequest` with command `Draw/PixelLocalHttp`, the
image bytes from `PixelBean.pixelForLocalHttp` (the app's own art format, via
`c.F` / `c.j` — this repo's `divoomd/src/art_codec.rs` DECODES that family
and has no encoder), and posts it with `BaseParams.uploadFileToLocalDevice`,
which adds the cloud device id and `LocalToken`, to
`http://<DevicePrivateIP>:9000/upload` as multipart
(`references/apk/decompiled_src/sources/com/divoom/Divoom/http/OkHttpUtils.java`).
The private IP comes from the cloud's device list, so the panel must be bound
to the account. The daemon's LAN transport (`divoomd/src/lan.rs`, port 9000,
`/divoom_api`) speaks settings commands only (`divoomd/src/device_call/lan.rs`)
and has no image command. The account lists no device and port 9000 answered
nowhere on the LAN (measured 2026-10-20).

## 2. The panel

### Rams

**1. [high] The product says "one surface" and shows a mosaic.** The snap
joins chassis edges (F4), so the picture is cut across the bezels instead of
behind them: two snapped panels show a squeezed picture with a seam the width
of both bezels. A promise the glass does not keep is worse than no promise.
*Fix:* until a photograph shows one picture across a seam (P6.1's Done when),
the bench says what it does — "lined up" — and nowhere says "one surface".
*Where:* `divoom_gui/web_ui/spatial_snap.js` header, the wall push toast.

**2. [high] A user-facing reason that is false.** F8. *Fix:* the reason says
what is true: the app draws over Bluetooth only and has no Wi-Fi image command
yet. *Where:* `divoomd/src/wall/refusal.rs`, `tests/test_e2e_bench_snap.py`.
Done in this commit.

**3. [med] A blocked item waiting on hardware nobody owns.** P6.2 has been
BLOCKED "on a LAN panel bound to the account" with the two candidates named,
and neither candidate can ever be one (F9). An item that waits on an
impossibility is a decision dressed as a blocker. *Fix:* owner decision 5;
until then the row states the true blocker. *Where:* `docs/ROADMAP.md` P6.2.

### Kare

**1. [high] At 16 pixels, pitch is the picture.** A Pixoo pixel is 9.9 mm, a
Timoo pixel 3.75 mm (F3). Pixel art cut one for one across that seam is a
2.6x jump in scale at the edge; resampled, a 16x16 sprite loses its pixels
entirely. Pixel art across unequal pitches cannot be made honest at any size.
*Fix:* decision 1 (c): pixel art is refused across unequal pitches, naming the
two pitches; pictures use the physical canvas. *Where:* the D14 check in
`DivoomWall::show_image` (`pixel_art_fits`), `divoomd/src/wall.rs`.

**2. [med] The bench must draw the glass, not just the box.** The bench
already renders `screen_mm` inside each chassis (`spatial_stage.js`); the
wall's preview of the cut should show each panel's piece inside its glass
with the bezels drawn as bezels, so the gap the user will see on the shelf is
the gap they see on the bench. *Fix:* the wall preview paints the cut in the
screen square, not the chassis rectangle. *Where:* `spatial_stage.js` (the
`screen_mm` block), `divoomd/src/wall/previews.rs`.

**3. [low] "Snap" names the gesture, not the result.** Keep the word for the
drag; label the outcome by what the panels show ("one picture across 2
panels" only once F4 is fixed).

### Carmack

**1. [high] Measure before building any sync.** F5 and F6 say skew and drift
exist; they do not say how big they are. A static image whose pieces land
80 ms apart is a non-problem, and a two-phase "upload all, then start" scheme
needs a start command the protocol may not have. *Fix:* M2 and M3 below
first; build a barrier only if M2 shows a skew a person can see (over ~100 ms)
and only if a separate start exists. *Where:* `divoomd/src/wall/outcome.rs`
`each_slot`.

**2. [high] One geometry, in millimetres, owned by the daemon.** Today the
cut is computed from bench pixels (`0.65 * w_mm`), a second copy of geometry
whose only source is a drawing scale. *Fix:* the daemon owns each family's
screen RECTANGLE in the chassis (x, y, w, h in mm, measured — M1), a pure
`screen_rect` the cut uses in free-form, and the GUI reads it from
`device_status`'s `chassis` (the parity test
`tests/test_panel_model_parity.py` already holds the GUI to the daemon's
table). *Where:* `divoomd/src/panel_model.rs` `FAMILIES`, `cut_for` in
`divoomd/src/wall.rs`.

**3. [med] A Wi-Fi slot in a Bluetooth wall is a latency mix, not a slot.**
An HTTP upload of an encoded file and a BLE 0x8B stream finish on unrelated
clocks; the first Wi-Fi version should draw a Wi-Fi panel ALONE and measure
its upload-to-glass time before it is ever a slot beside Bluetooth panels.

### Blow

**1. [high] What is the core experience, and is it this?** The bench is four
different toys on a shelf, not a video wall. A seamless surface across four
pitches and four bezel widths is a video-wall feature borrowed from another
product. The version worth having is a SCENE that crosses panels, which is a
time feature (McMillen 1), not a geometry one. *Fix:* ship the smallest proof
(one still picture across the proving pair, photographed); if it does not
look like one picture at shelf distance, delete the "one surface" claim and
keep the bench as a map of the shelf.

**2. [high] Do not build a transport for a panel you do not own.** P6.2 would
be code against a device nobody here can test, and the APK route needs an
encoder this repo lacks (F10). *Fix:* decision 5 (b): "Not planned" until a
Wi-Fi panel is in the house; the refusal (now true) is the whole feature
until then.

### McMillen

**1. [med] The delight is the crossing, not the seam.** Nobody screen-records
a static picture split over two boxes. They record a sprite walking off the
Pixoo's right edge, vanishing into the bezel for exactly as long as the bezel
is wide, and walking out of the Tivoo-Max's left edge. The bezel becomes a
tunnel instead of a defect. *Fix:* the second step after the still-picture
proof: a "hand-off" clip, one sprite per panel, timed so the exit and the
entry are one walk at the physical gap (needs M2's skew number). *Where:* a
new wall operation beside `show_image` in `divoomd/src/wall/dispatch.rs`.

**2. [low] Confirm the join on the glass.** When two panels snap on the
bench, both panels show the same one-second sweep across their shared edge.
The user sees on the shelf which two the app thinks are joined. *Fix:* a
cheap two-frame push on snap, behind the existing wall write path.

### Protocol and hardware realist

**1. [high] The proof needs numbers only the shelf can give.** Five, listed
as M1-M5 below. None can be got from this session (no device writes, no
camera on the panels).

**2. [med] Colour will seam before geometry does.** Four product lines, four
LED batches, four brightness curves: the same RGB at the same brightness
setting will not match across panels. *Fix:* M4 first; if the step is
visible, a per-family gain (three numbers) applied to the cut, measured from
the photograph, never guessed.

**3. [med] A relinked panel shows stale art.** F7. *Fix:* the wall keeps the
last image it pushed and its cut per slot; on relink it re-sends that slot's
cut and marks it in the reply. *Where:* `divoomd/src/wall.rs` (the previews
record already holds the last cut per slot as a data URL — keep the frames
beside it).

## 3. Measurements before any building (owner's hands)

| Id | What | How | Settles |
|---|---|---|---|
| M1 | Each family's screen rectangle in its chassis: left, top, width, height in mm | A ruler on each of the four panels, front face | the `screen_rect` table (Carmack 2) |
| M2 | Skew between two panels' pieces of one still image | The daemon logs each slot's stream end (a log line, no new write path); one push to the proving pair | whether a barrier is needed (Carmack 1); the hand-off timing (McMillen 1) |
| M3 | Animation drift between two panels | One looping GIF on the pair, a phone video at start and after 10 minutes | decision 2 |
| M4 | Colour match | A mid-grey and a white field on the pair at one brightness, one photograph | the per-family gain (realist 2) |
| M5 | The seam | The proving pair edge to edge, one picture, one photograph | P6.1's Done when |

## 4. Recommended design

### P6.1 — one picture across panels

A wall image is placed on a PHYSICAL canvas in millimetres. Each slot is its
chassis rectangle on the bench; what the panel shows is the part of the
canvas behind its SCREEN rectangle (M1), resampled to its pixels. Bezels hide
canvas, as glass frames do. Pixel art (D14) is cut one for one and is allowed
only when every slot has the same pitch; otherwise it is refused naming the
pitches. Static images only until M3. A dropped panel leaves a marked hole and
gets its cut back when it relinks.

**First build step:** after M1, add the screen rectangle to
`FAMILIES` in `divoomd/src/panel_model.rs` and a pure `screen_rect` used by
`cut_for` in free-form, with a test that two chassis touching edge to edge
produce cuts whose canvas rectangles are separated by exactly the two
half-bezels (watched red on today's chassis-based cut).

### P6.2 — a Wi-Fi panel as a wall slot

Not planned until a Wi-Fi-architecture panel is in the house (decision 5).
When one is: probe both routes on it (decision 6), draw on it ALONE first and
measure upload-to-glass time, then admit it as a wall slot only for still
images.

**First build step (now, done here):** the refusal says what is true (F8).
**First build step (with a panel):** a read-only probe of port 9000
(`/divoom_api` with `Channel/GetIndex`, the read `lan.get_channel` already
sends in `divoomd/src/device_call/lan.rs`) and port 80, recorded in this file before
any image code.

## 5. Withdrawn or revised claims

- "The Timoo and the Tivoo-Max are the Wi-Fi models" (ROADMAP P6.2, 2026-11-07
  rework): WITHDRAWN, F9.
- "Measured 21 bench px" for the Pixoo + Timoo seam: REVISED — derived from
  the chassis table, not photographed (F3).
- The refusal's "the Wi-Fi image upload ... is not known": WITHDRAWN, F8/F10.
