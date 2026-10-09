# divoom-control v0.41.1 — the menu bar icon is back to its size, and a v0.41.0 claim corrected

**Released**: 2026-10-08
**Previous**: v0.41.0 (2026-10-05)

A patch release. One thing you will see, one thing v0.41.0 told you that was
wrong, and one release-build guard that could not do its job.

## What you will notice

**The menu bar icon is 18pt again, and sharp on Retina.** v0.41.0's icon was
about 22% larger (22pt instead of 18pt). It was also a 1x bitmap that every
Retina display upscaled. The cause was `tray-icon` 0.26, which takes a bitmap's
pixel height as its height in points, up to a 22pt cap. The glyph is now drawn
on a 36 x 44 px canvas. The cap maps that to exactly 18 x 22pt at 2x, so the
icon keeps its v0.40 size with twice the detail. Rendered side-by-side sheets,
light and dark, are produced by `tools/render_tray_icon.py`. The renderer is
checked byte for byte against the app's own drawing code.

## What v0.41.0 got wrong

**The memory widget was never "8 points above Activity Monitor".** The v0.41.0
notes said the system-stats `mem` figure had moved onto a different definition
than Activity Monitor's. That was wrong. `sysinfo` 0.39.6 computes exactly
Activity Monitor's App + Wired + Compressed. An independent reconstruction from
the kernel's raw page counters differs by 0 bytes when both are read at the
same instant. The OLD figure (sysinfo 0.30) was the one that read low, by
4.2 points on average. The gap between the two versions depends on what the
machine is doing (measured from -3.7 to +6.1 points), so the table in the
v0.41.0 notes describes one moment, not either version. Activity Monitor's
header "Memory Used" reads about 2 points above the widget. It also reads above
the sum of Activity Monitor's own footer fields, so that gap comes from
Activity Monitor. **Nothing to change on your side:** the number was right all
along; only the explanation was wrong. `tools/mem_gauge_compare.py` repeats the
measurement on any Mac.

## Fixed

- **The release build's guard against bundling reverse-engineered material
  could miss a large leak.** The check piped `find` into `grep -q`. Under
  `pipefail`, grep's early exit kills `find` with SIGPIPE, and the check then
  reads as "nothing found". It passed a test bundle holding 20,000 planted
  files. It now asks `find` to stop at the first match itself. The same flaw
  was fixed in the code-signing helper, where a false miss would sign ad hoc
  and lose the Bluetooth permission on reinstall.
- **The DMG is built with `diskutil image create from`.** macOS 27 deprecates
  `hdiutil create`. A test keeps every script off the deprecated verbs.

## Under the hood

- `docs/SESSION_HANDOFF.md` was folded into `docs/ROADMAP.md`. The roadmap is
  now a phased plan of checkable items, and a test checks its shape and every
  path it names.
- CI no longer stores the checkout token in git config. It installs the tools
  the house gates need from gates_of_heck's manifest, and runs the gates through
  the native `goh` binary only.
- Repo-wide test scans list what git would commit, so a nested worktree no
  longer makes them see every file twice.

## Re-check on your setup

Nothing breaking: no API, protocol or stored-data change. After upgrading, the
menu bar icon should be the size it was in v0.40. If macOS has hidden it behind
the notch on a crowded menu bar, free some space and it reappears.
