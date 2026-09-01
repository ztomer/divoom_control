# v0.31.0 — R73: three unexposed methods met the hardware

The previous release listed three API methods that had never been called by
anything and could not be judged without a device. They were tested on real
hardware this round. **Two of the three were broken.**

Nothing here changes what the app looks like, except that one slider and one
set of checkboxes now do something.

## A temperature channel that never existed

`set_temperature_channel` sent `[0x01, temp_type, R, G, B, 0x00]`. But `0x01`
is the **Lighting** channel — this repo's own `Channel::Lighting = 0x01` says
so. The parser expects the colour to start at offset 1, so `temp_type` was
eaten as RED and every byte after it shifted down one.

Both outcomes were predicted from the byte layout *before* testing, and both
matched on the panel:

| Requested | Sent | Read as | Seen |
|---|---|---|---|
| white, Celsius | `01 00 FF FF FF 00` | r=00 g=FF b=FF | **cyan** |
| red, Fahrenheit | `01 01 FF 00 00 00` | r=01 g=FF b=00 | **bright green** |

A third device went dark — also predicted, by the other documented layout,
where the same shift lands `0x00` in the brightness byte.

**Someone had already seen this.** `docs/CHANNEL_ARCHITECTURE.md` recorded the
exact cyan screen and explained it away: *"a device-state issue... The APK is
ground truth."* Two sources "agreeing" (the APK and hass-divoom) were treated
as confirmation — but hass-divoom's `show_temperature()` describes
TimeboxMini/Aurabox. Agreement about a different device family is not evidence
about this one.

That file now carries the rule it cost: **a decode is confirmed by the panel,
not by concordance between documents.**

## A schedule that could never fire

`set_timeplan` accepted an `index` the 0x56 packet does not carry, wrote
`channel` into the `mode` byte, hardcoded `type` to Animation while supplying
an empty animation, and defaulted `week` to 0 — no days. Four fabrications in
one signature. It never fired. Removed.

## What was actually working

* **`set_clock_rich`** — confirmed, and now wired in. It does not draw one
  combined face as assumed: it makes the panel **cycle** separate weather /
  date / temperature / clock screens. The verification script had been telling
  testers to look for the wrong thing, which would have marked a working
  command broken.
* **`sync_time`** — the device clock moved 18:41 → 21:42.

**The reachability allowlist is now empty.** All 114 shipped API methods have a
real caller: 0 unreachable, 0 python-only, 0 allowlisted.

## 0x35 was never a missing opcode

The R12 audit concluded `pic_scan_ctrl` had no entry in the APK's command
table and was probably invented. `SppProc$CMD_TYPE.java` has it:
`SPP_SAND_PAINT_CTRL(52)`, then **`SPP_SCROLL(53)`** = 0x35. The audit file
making that claim had itself been pruned to git history, so the code cited
something nobody could open to check.

Our bytes already matched `CmdManager.b3` exactly. It shows nothing because it
sets the scroll mode for content the device is *already* scrolling, and this
app has no scrolling-content path. Renamed `set_scroll`; the invented
`control=1` branch removed; under-specified calls now refuse instead of
sending a zero-speed no-op and reporting success.

## Scrolling text: decoded, implemented, not supported by the panel

R32 concluded device-side text was impossible after `0x87` rendered nothing.
It was the wrong command. The device has no font — the APK uploads the
**glyphs** first (0x6E start, 0x7C glyph packets of 5 characters, 0x86 string,
0x86 rate; the start must come first). The daemon implements all of it, reusing
the `divoom_fond16_*` blob it already embeds at exactly 32 bytes per glyph.

The Tivoo-Max does not implement the command set. Proven with a controlled A/B
in one window rather than argued:

```
tx cmd=0x45 (show_light)  ->  basic frame cmd=0x45     <- device acks
tx cmd=0x6e               ->  (nothing)
tx cmd=0x7c               ->  (nothing)
tx cmd=0x86  x2           ->  (nothing)
```

The same trace shows our bytes were correct, so this is a firmware gap. Kept in
the daemon with tests and **no GUI surface** — a button that does nothing is
what this round spent its length removing.

## New gates

* **`test_web_ui_element_ids.py`** — `getElementById` returns null for an id
  nothing defines, and this codebase's `?.checked || false` style turns that
  into a silent `false` forever: a dead control with a clean console. Written
  while the scan showed 0 unresolved ids, which is the only cheap moment.
* **`test_no_runaway_file_growth.py`** — a 15,000-line ceiling on all tracked
  text. A scripted edit turned `docs/ROADMAP.md` into **370,588 lines** and it
  was committed: `s[s.index(A):s.index(B)]` with A after B yields `""`, and
  `str.replace("", new)` inserts between every character. The 500-line
  structural cap excludes `docs/`, so the one gate that measures size was
  looking away.

## The class

Both broken methods share one shape: **a method whose parameters do not
correspond to the fields of the packet it sends.** Both were
reachable-but-never-called. Of the three uncalled methods audited, two were
wrong — being unexercised was the shared property, not a coincidence.

## Known open

* **R12 visual pass** — album cover, custom art and weather on a device, at
  real scale, light and dark surroundings. Needs a person looking.
* **`search_weather_city`** returns `RC=1` on a valid, logged-in account while
  two sibling cloud calls succeed on the same session. Recorded, not patched:
  guessing which field Divoom now wants would be inventing a protocol.
* **The browser e2e suite fails randomly at normal machine load** (unchanged
  from v0.30.0). Since `pre-push` runs the whole CI, that reddens a push during
  ordinary work and teaches the bypass habit the gate exists to prevent.
