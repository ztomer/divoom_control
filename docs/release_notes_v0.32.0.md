# v0.32.0 — R74: a daemon that cannot be reached cannot be fixed

A user reported a crash and, separately, that `/tmp/divoom.sock` was "in use by
another program". Both turned out to be ours, and both were the same shape of
mistake: **a system that could not describe its own state, and instruments that
read identically for "fine" and "broken".**

## The daemon could go completely deaf, then blame a stranger

A `divoomd` ran for five days holding 64 connections and answering nobody. Every
attempt to start a replacement said the socket was in use by another program.
There was no other program.

Two independent design defects:

**The connection cap and reachability were the same resource.** The accept loop
waited for a semaphore permit around `accept()`, so a full cap parked it.
`connect()` still succeeded — the kernel completes it onto the listen backlog —
and then nothing ever came back, for any command, including `get_status`. The
daemon was not slow; it was deaf, and indistinguishable from a foreign program
on the path.

It now accepts unconditionally and refuses the overflow in one reply line, which
carries `daemon_version` so a busy daemon stays identifiable. **A cap must bound
work, never reachability.**

**The subscription TTL was reset by the daemon's own output.** The watchdog
pushed its deadline out every time an event was DELIVERED. Written to answer "is
this client still there?", it answered "have we written to it recently?" — and
since events are a broadcast, deliveries moved every subscriber's deadline in
lockstep and ranked nobody. It could only ever reap a subscriber on a silent
channel, which is not the case anyone needed bounded.

Request/reply clients close as soon as they have an answer, so subscriptions
were the only thing that could accumulate, and the only thing whose watchdog
could not bite.

Subscriptions are now a bounded, **self-cleaning LRU registry**: nothing is
disturbed until a slot is needed, then the least-recently-active one is
reclaimed — only if quiet past `RENEGOTIATE_AFTER` — and told to reconnect with
`{"type":"resubscribe"}`. If every slot is demonstrably active the newcomer is
refused with a reason; without that floor, newcomers evict each other in a loop.
Activity means bytes FROM the client, for the same reason the old watchdog
failed. Their budget is half the connection budget, so they can never starve
requests.

`socket_bind` no longer calls silence "another program" either: a listener that
accepts and says nothing is `UnresponsiveListener` (stop our own pid); one that
answers in a foreign protocol stays `ForeignListener` (leave it alone). Opposite
remedies, so they must not share a variant.

## The GUI crashed a stranger's Python to focus its own window

`gui_main.main()` focused an already-running Control Center with
`osascript -e 'tell application "Python" to activate'`. That does not address
our GUI — it asks LaunchServices to resolve the NAME "Python" and LAUNCH
whatever answers. On a machine with TeX Live Utility installed, that is its
embedded Python 3.9.10, which Gatekeeper app-translocates into `$TMPDIR`,
breaking its `@rpath` so it aborts in dyld. One crash report per attempt, and
the window never came forward.

Focus now goes through System Events addressed by `unix id`, which can only
front a process that already exists. `tools/check_applescript_launch.py` fails
any source that addresses an application by name without an `is running` guard.

## Instruments

Every gate here was blind the same way — it could not represent the failing
state:

- The back-pressure test asserted the over-cap client gets **no reply within
  300ms**. That reading is identical for correct back-pressure and for a daemon
  that will never answer again, so it stayed green through the whole outage.
- Its sibling encoded the conflation in a FIXTURE: the "foreign listener" test
  drove a listener that accepts and says nothing, so silence was the only shape
  ever exercised, labelled with the wrong remedy.
- Six repo gates reported "OK — 0 files clean" over an empty tree. They are
  fixed with one shared guard (`tools/_empty_scope.py`), not excused.

## Upgrade notes

No protocol break. Clients may now receive `{"type":"resubscribe"}` on a
subscription and should reconnect; the bundled menu bar and GUI already do. A
client that arrives while the daemon is at its connection cap now gets an
explicit error reply instead of hanging.
