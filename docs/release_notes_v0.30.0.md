# v0.30.0 — the gates got real, and the daemon got its jobs back

Two rounds in one release. Nothing here changes what the app looks like; it
changes what the project can *notice*.

## The gate that ran four checks and looked like it ran eighteen

`pre-push` executed `structural.sh` — emoji, conflict markers, file length, disk
hygiene — and nothing else. The rust and python layers were commented out, so
the 17-step CI list and both coverage floors ran only when a human typed
`./scripts/ci_local.sh`.

That hole was invisible because **nothing failed**. A gate that is not wired in
reports nothing at all, which from outside is indistinguishable from a gate that
is wired in and passing.

It is wired now, and all five gate classes are proven to *refuse* a push. It
costs 9m22s (1m50s with `DIVOOM_GATE_FAST=1`, which announces itself every
time). It has already caught three real failures in its author's own work.

## Three defects nobody was looking for

Each was found while fixing something else, and each was worse than the finding
that led to it.

* **The daemon's credential store would have destroyed your settings.**
  `cloud_store::save_config` rewrote the whole of `config.ini`, taking `[gui]`,
  `[gallery]` and the weather settings with it — and it required a non-empty
  password, so an email-only save was impossible, reintroducing a bug the Python
  side had already fixed. Nothing had noticed because no client called it. The
  capability map said "duplicate, move it"; following that literally would have
  eaten user config on the first save.
* **`sync_time` set the device clock to the year 2000** when called without
  arguments, and reported success. It refuses now.
* **The control server's TCP surface was unauthenticated.** It
  reflection-dispatches every GUI API method — device control, credential reads,
  file dialogs — and its authorisation check returned true when no token was
  set. "Bound to 127.0.0.1" was doing the work of an authorisation boundary,
  which loopback is not. It now requires a token; the Unix socket is 0600.

## Dead code, measured rather than guessed

* The API allowlist went **20 → 3**, and **three of its stated reasons were
  false** — one was written from a text match on a docstring.
* **292 lines** of notification polling removed from the shipped client package,
  against a working Rust implementation, with no production caller.
* `save_lan_config` wrote to a config store **nothing has ever read**. Wiring it
  up — the obvious fix for an unreachable method — would have written settings
  no code consumes.
* A verification harness that claimed to mirror the GUI's decode chain was
  checking a path the product stopped taking three releases ago. It would have
  passed on assets the app cannot render and failed on containers it handles
  fine.

## What is now enforced instead of remembered

* `tools/capability_census.py` — 443 daemon commands read from the Rust match
  arms, against an AST walk of the whole shipped Python surface. Reports
  **0 duplicates**, and fails the build on a new one.
* `tools/check_hotchannel_parity.py` — one config file with two parsers, held in
  step because neither reader can be deleted.
* The Python coverage floor now enforces the number it advertises. It was
  claiming 90% and enforcing "≥ 89.5" (coverage.py rounds), passing on a
  0.01-point margin.
* LAN failures say **why**. A Bluetooth-only device now reads "this device is
  connected over Bluetooth, which has no LAN API" instead of a bare failure.

## Known open

* **Three unexposed API methods** (`set_clock_rich`, `set_temperature_channel`,
  `set_timeplan`) and the R12 visual checks need a device. `scripts/hw_verify.py`
  collects all six checks in one command and refuses to invent verdicts when
  nobody is watching.
* **The browser e2e suite fails randomly at normal machine load.** Two full runs
  on one commit failed different, non-overlapping sets; all pass in isolation.
  Since `pre-push` now runs the whole CI, that reddens a push during ordinary
  work — which teaches the bypass habit the gate exists to prevent. It needs
  startup measured under load, not a bigger timeout.
