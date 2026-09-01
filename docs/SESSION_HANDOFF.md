# Session Handoff — read this first

**Consolidated roadmap**: `docs/ROADMAP.md` — shipped rounds, open workstreams.
This file tracks the per-round current state and open threads.

This is the **cross-agent session state**. opencode and Claude Code keep their
own conversation stores. THIS FILE + git history + CHANGELOG + ROADMAP are the
shared memory. Read this on entry and **update it at the end of every round**
(see the core rule in `AGENTS.md`).

## How to resume

- **opencode**: `opencode -s ses_184471307ffeCUHgzv9w51O0oA` (or `opencode export <id>`).
- **Claude Code**: reads `CLAUDE.md` → `AGENTS.md` → this file, plus `git log`.
- Both: `git log --oneline`, `CHANGELOG.md`, `docs/ROADMAP.md`.
- This file is the CURRENT state, not an archive. Once a round ships and its
  CHANGELOG stanza is written, its entry here is pruned to git history (house
  rule: one forward-looking doc). To recover older context:
  `git log -p -- docs/SESSION_HANDOFF.md` for past entries,
  `git log --diff-filter=D -- 'docs/**/PLANNING_*'` for round plans.

## Current state — _update this section each round_

- **2026-08-31 — v0.31.0 CUT (R73).** Version bumped across `pyproject.toml`
  and both crates; CHANGELOG stanza and `docs/release_notes_v0.31.0.md`
  written. **Not yet tagged or published** — that is the next action, and it is
  deliberately a separate decision.

  **The round in one line: three API methods that nothing had ever called were
  taken to real hardware, and two of them were broken.** The allowlist that
  excused them is now EMPTY — all 114 shipped API methods have a real caller.

  * `set_temperature_channel` DELETED. There is no temperature channel; `0x01`
    is Lighting, so `temp_type` was eaten as the red byte. White rendered cyan,
    red rendered bright green — both predicted from the layout before testing.
    `docs/CHANNEL_ARCHITECTURE.md` had recorded that exact cyan screen years
    earlier and explained it away as device state. It now carries the rule that
    cost: **a decode is confirmed by the panel, not by concordance between
    documents.**
  * `set_timeplan` DELETED (GUI only; the daemon's 0x56/0x57 are faithful
    ports). It fabricated an `index` the packet has no field for, put `channel`
    in the `mode` byte, and defaulted `week` to 0 = never.
  * `set_clock_rich` WORKS and is wired in. It CYCLES separate panels rather
    than drawing one combined face — `hw_verify.py` had been telling testers to
    look for the wrong thing.
  * `sync_time` confirmed: the clock moved 18:41 -> 21:42.

  **Two long-standing documents were wrong and are corrected.** The R12 audit
  said 0x35 had no APK entry; it is `SPP_SCROLL(53)`, and the audit file making
  the claim had been pruned to git history, so the code cited something nobody
  could open. And R32's "device-side text is impossible" was the wrong command,
  not a missing feature — scrolling text is now fully decoded and implemented
  (see below).

  **I corrupted `docs/ROADMAP.md` this round and committed it** (373 lines ->
  370,588). `s[s.index(A):s.index(B)]` with A after B yields `""`, and
  `str.replace("", new)` inserts between every character. Restored, and gated:
  `tests/test_no_runaway_file_growth.py` puts a 15,000-line ceiling on all
  tracked text, because the 500-line structural cap excludes `docs/`.

### Scrolling text — decoded, implemented, daemon-only

`text.show_scrolling_text` ports the APK's full marquee sequence: 0x6E start
(FIRST — the order is load-bearing), 0x7C glyph packets of 5 characters
(`[cp_lo, cp_hi, glyph[32]]`), 0x86 string, 0x86 rate. The glyphs come from the
`divoom_fond16_*` blob the daemon already embeds at 32 bytes each.

**The Tivoo-Max does not implement it.** Controlled A/B in one
`DIVOOMD_BLE_DEBUG` window: it acked `0x45` and returned nothing for
`0x6E`/`0x7C`/`0x86`, while the same trace confirmed our bytes were correct —
a firmware gap, not an encoding bug. No GUI surface, deliberately. The other
three devices are the same 16x16 class but untested; if one acks `0x7C`,
wiring a button is small work on top of what exists.

## Open threads / next up

Three things, and the first two need you at a keyboard with a device.

**1. The hardware packet — five checks, one command** (R73 closed and removed
the `pic_scan` and `clock_rich` entries).

    python3 scripts/hw_verify.py --self-test        # calibrate FIRST
    python3 scripts/hw_verify.py --out report.json

Start the GUI first: it owns the Bluetooth TCC grant, and the packet REFUSES to
spawn its own daemon because a shell-launched one dies on its first scan with
SIGABRT and an empty stderr. `--self-test` exits **3 = PARTIAL** until a device
is connected, which is honest rather than broken: with nothing attached the
daemon refuses at the no-device precondition before it ever reads the method
name, so the invalid-method branch stays untested.

What the packet decides:

* **Three UNEXPOSED methods** — `set_clock_rich`, `set_temperature_channel`,
  `set_timeplan`. The last three entries in `check_gui_api_reachable.py`'s
  allowlist. Not dead, not superseded: the daemon implements them and the UI
  never offers them, so wire-or-delete depends on whether the device renders
  them.
* **`sync_time`** — R72 routed it to the daemon and the Python path it replaced
  was BROKEN (an `AttributeError` swallowed into a silent `False`). "It returns
  True now" proves nothing; the clock has to be seen to change.
* **R12 visual pass**, **`pic_scan_ctrl` 0x35**, **`search_weather_city`** on a
  configured account.

**2. The browser e2e suite fails randomly at NORMAL machine load.** Two full
runs on one commit failed different, non-overlapping sets of camoufox tests; all
pass in isolation. Since R71 P0 made `pre-push` run the whole CI, a randomly-red
gate teaches `--no-verify` — precisely what P0 existed to prevent. Detail in
`docs/ROADMAP.md` under the OPEN heading. **Do not "fix" it by raising a
timeout**: that threshold was chosen on an idle machine, and the fix is to
measure browser + daemon startup under controlled load.

**3. `config.ini` stores the Divoom account password in PLAINTEXT.** Out of
scope for R71/R72 and never in their ledgers, recorded here so it is not lost.
R72 moved credential writes to the daemon's `cloud_store`, which is now the one
place that would have to change.

### What is NOT open any more

R70's twelve findings, R71's twenty allowlist entries (bar the three above) and
R72's F1-F7 are all closed. Their durable output is
**`docs/CAPABILITY_MAP.md`** — 26 census rows, each with a verdict, plus the
F1-F7 closure table and the three blind spots the census cannot see. Read that
before re-auditing anything; two of R72's seven findings turned out to be
misdescribed by the audit that raised them, and the map records which and why.

## Earlier history

`CHANGELOG.md` is the durable record of what shipped, and `docs/ROADMAP.md` of
what is open. Round-by-round handoff prose is recoverable from
`git log -p -- docs/SESSION_HANDOFF.md` and, for R3–R64, from the archive file
deleted on 2026-08-30:
`git log --diff-filter=D -- 'docs/archive/*'`.

## Hardware note

macOS Bluetooth TCC is granted per RESPONSIBLE PROCESS. A daemon started from a
shell has no grant, so the first BLE scan kills it with **SIGABRT and an empty
stderr** — no panic, no message, nothing in the log. Confirmed 2026-08-30 by
differential: a BLE-linked build dies on the GUI's `scan_devices`, a
`--no-default-features` build drives the same flow cleanly. Users are unaffected
(the GUI launches the daemon and owns the grant); it only bites terminal work.

`scripts/gui_pov.py` warns when the binary it picked links CoreBluetooth, and
names TCC as the likely cause if the daemon aborts silently after a scan.

**To drive a LOCALLY BUILT daemon on hardware (verified R73):** the grant
follows the app bundle (`com.divoom.control`), not the binary, so install into
the bundle and let the app be the responsible process. Back up the original
binary first — adhoc signing is deterministic over content, so restoring the
exact bytes restores the old cdhash and its grant.

```bash
cargo build --manifest-path divoomd/Cargo.toml
cp target/debug/divoomd dist/Divoom.app/Contents/Resources/bin/divoomd
cp target/debug/divoomd dist/Divoom.app/Contents/Frameworks/bin/divoomd
codesign --force --deep --sign - dist/Divoom.app
pkill -f Divoom.app; rm -f /tmp/divoom.sock; open dist/Divoom.app
```

Then drive `/tmp/divoom.sock`. `connect_device(mac=...)` works directly; `scan`
often reports "already in progress" because the GUI is scanning. For a wire
trace, `launchctl setenv DIVOOMD_BLE_DEBUG 1` BEFORE `open` (the env has to
reach a GUI-launched app); the daemon logs to `/private/tmp/divoom_client.log`.

**Reading that trace:** a device ECHOES `basic frame cmd=0xNN` for opcodes its
firmware implements. A silence proves nothing on its own — an idle window looks
identical — so always send a known-good command (0x45) first in the SAME window
and compare.

Watch out: `cargo test` rebuilds `target/debug/divoomd` WITH default features,
so a BLE-free build does not stay BLE-free across a test run.
