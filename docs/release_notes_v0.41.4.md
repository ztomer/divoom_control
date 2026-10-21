# v0.41.4 — the hot channel reaches the devices the app's settings name

The hot-channel push is enabled, scheduled, and was reaching nobody. The
devices it should push to were stored TWICE — once in the app's settings
(`config.ini`'s `[gallery]` table) and once in `hotchannel.json` — and the
second copy was the empty one, so the loop fetched nothing and pushed
nothing, with nothing anywhere saying so.

This release puts the fact in ONE place (the app's own settings), makes the
cadence a DAY (the content is refreshed almost daily), makes a failed run
LOUD (it reaches the owner's phone on the estate's own push channel), and
starts MEASURING the one question that is still open (is the "monthly best"
category a sliding window?) instead of assuming an answer.

- **The devices come from the settings.** The loop reads `config.ini`'s
  `[gallery]` table — the table the GUI writes when the owner browses the
  gallery with a device, and the table the Routines card's device toggles now
  write. There is no second list to fill and no second list to drift.
- **A stale `hotchannel.json` cannot override the settings.** The old keys
  are read, reported and ignored; the next save of the schedule drops them.
- **Daily.** The default interval is 86400 seconds, in the daemon, in the
  GUI's config and in the Routines card.
- **Loud.** A failed cycle POSTs to the estate's push endpoint — the same
  `ROUTINES_PUSH_URL` the rest of the estate alarms use — and a recovery
  posts quietly.
- **Measured.** Every push records what the category returned (names, dates,
  ids) in the daemon's log and in `~/.config/divoom-control/hotchannel_fetches.json`.
  Two dated snapshots a day apart settle the sliding-window question; the
  release says the question is still open rather than answering it early.

The dead launchd job stays dead: there is no Python job, and nothing
resurrects one.
