# v0.41.5 — the gallery's magic-26 files decode, and the run names the ones it cannot show

The hot channel pushed **34 of 40 files** to the owner's four panels and said
nothing about the other six beyond a count. The six were **magic-26 (`0x1A`)
containers** — the newest art in the gallery — and the native decoder could
not read them: a decoder gap, carried on from silently.

This release reads them, and it makes the run name any file it still cannot
show.

- **The magic-26 container decodes.** A container is
  `[26][frames][speed:u16 BE][rows][cols]` and then, per frame,
  `[len:u32 BE][record]`; the record's flag says how its pixels are coded.
  The gallery's files are the flag-`0x0C` form — a palette and LSB-first
  indices in a 4x4 grid of 16x16 tiles (64x64) — and they now decode, with
  the picture pinned by a SHA-1 and the frames consuming exactly the file.
  The port came out of the app's own native library
  (`divoom_image_decode_Iframe`), which is what renders these files.
- **The run names the files it could not show, and why.** Every failure
  carries its reason — the container, the frame flag, a failed download, a
  device that would not take the image — and the warning names the file.
- **The granularity is unchanged.** A device that could not be reached, or
  that was reached and showed nothing, fails the run and rings the phone. A
  file that could not be shown while the device showed the others is a
  warning. The rule is one pinned function now.
- **What it cost:** 6 of 40 file-attempts, 4 distinct files, **852,302 B of
  the run's 3,308,028 B (25.8%)** downloaded and never shown, 177 frames of
  animation that never arrived. And what the device holds after a run: the
  art is SHOWN, not stored — three of the four panels still read the
  pushed-image channel (0x46 = 5) after the run; what is on the screen
  cannot be read back from this side.
