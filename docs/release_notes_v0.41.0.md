# divoom-control v0.41.0 — every dependency current, and the gates that were lying about it

**Released**: 2026-10-05
**Previous**: v0.40.0 (2026-09-25)

This release is mostly invisible, which is the point: nothing was broken, several
things were quietly not working, and the round was spent finding the second kind.

## What you will notice

**The system-stats widget's memory figure reads higher.** It now sits roughly 8
percentage points ABOVE Activity Monitor's "Memory Used". Nothing regressed — the
`sysinfo` crate changed how it accounts for macOS memory pages in 0.38.3, and
0.39.6 carries it. Measured by building 0.30 and 0.39 side by side against the
same machine at the same moment:

| `sysinfo` | used | share of 64 GiB |
|---|---|---|
| 0.30.13 | 37.16 GiB | 58.1% |
| 0.39.6 | 42.13 GiB | 65.8% |

The old figure matched Activity Monitor (independently reconstructed from
`vm_stat` at 57.6%), so the widget is now deliberately on a different definition.
The measurement and the reasoning are recorded at the call site so a later
session does not "correct" it back into a hand-rolled `vm_stat` sum.

**The menu bar icon is about 22% larger.** `tray-icon` 0.26 raised the macOS
status-item height cap from 18pt to 22pt, and this app's glyph renders at its
natural 22pt where it used to be forced to 18pt. No test can see this; if it
reads too heavy next to the system items, the fix is to pre-downscale the artwork,
not to reintroduce a deprecated API.

## Not breaking

No public API changed and no stored data format changed. If you install
`requirements.txt` directly rather than via `pip install -e .`, note that it no
longer lists `numpy` or `psutil`: neither was imported by anything in the shipped
tree, and `psutil` was additionally being force-collected into the app bundle by
`divoom.spec` while the project's own gate listed it as forbidden in the GUI.

## What was actually wrong

Four gates were **red before this round started**, and none of it was caused by
it:

- **A dependency feature had been deleted upstream, and the app was pinned to
  the last version that still had it.** `reqwest` 0.13.2 removed the optional
  dependency behind the `webpki-roots` feature this project declared, so
  `cargo update` could no longer move `reqwest` — it printed the fact in a
  parenthetical and **exited 0**, and no gate printed that line. A plain
  43-package dependency update had been stuck behind it for months. This is now
  gated by `tools/check_cargo_features.py`.
- **TLS trust anchors moved** from a bundled Mozilla CA store to the macOS
  Keychain, because `reqwest`'s `rustls` now uses the platform verifier. Verified
  three ways against the real Divoom cloud host, including the case that matters:
  a self-signed certificate must be **rejected**.
- **The BLE self-heal read a dependency's error wording** to decide whether to
  rebuild the Bluetooth central, so an upstream reword would have silently
  disabled it. The decision is now made from the typed error, with no wildcard
  arm, so an upstream change is a compile error instead of a silent regression.
- **An e2e test waited on a condition the app satisfies by itself.** Nine browser
  waits counted toast calls; the app raises a startup toast about a second after
  load with no interaction. One test therefore asserted on a toast it had not
  created. The browser suite went from 165 passed / 1 failed to 177 passed.

## Verification

- 25/25 local gate steps pass (`./scripts/ci_local.sh`), and GitHub CI is green
  on the tagged commit.
- 495 Rust tests and 1610 Python tests in the default suite; 177 browser tests;
  1095 legacy-library tests.
- Every new gate was **calibrated** — each was broken and watched go red before
  being trusted. Several were wrong on the first attempt, which is recorded in
  the commit history rather than tidied away.
- `cargo audit` green against an empty advisory ignore list, in both this project
  and the sibling `antiknob`.

## Known issues carried forward

- A genuinely dead CoreBluetooth central is still missed on one code path inside
  `btleplug` (its `adapter.rs` keeps a raw `SendError` whose text matches none of
  the markers). Pre-existing; now a one-line structural fix rather than a fragile
  one, and it deliberately waits for its own change because it alters which
  operations retry.
- The `0x1189 CH57x` gesture mapping and byte 5 of a chained record remain
  unverified in the sibling `antiknob` for want of the hardware.
- `pyinstaller` is intentionally one minor behind, because it changes the bundle
  and wants a bundle diff in its own commit.