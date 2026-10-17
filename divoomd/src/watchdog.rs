//! An in-process wedge detector for the serving loop (P2.6).
//!
//! Nothing outside the daemon can tell a wedged divoomd from a quiet one:
//! launchd has no watchdog (verified as an absence), and the protocol has only
//! a client-sent `ping`. On 2026-09-07 a divoomd stayed deaf for five days.
//!
//! The detector therefore lives INSIDE the process, and its evidence comes
//! from INSIDE the loop it guards: the accept loop beats a [`Heartbeat`] on
//! every turn, including a timer turn when no client connects, and a plain OS
//! thread -- not a task on the runtime it is judging, which a wedged runtime
//! would starve along with everything else -- checks that the beats keep
//! coming. A side-channel probe is the gray-failure blind spot: it keeps
//! succeeding while the thing it was meant to watch is stuck.
//!
//! On a wedge the daemon logs what it can (how long the loop has been silent,
//! and who holds its connections) and exits, so the next client request
//! respawns it (`ensure_daemon` in the GUI and the client). Exiting is the
//! honest move: a process that cannot serve is worse than none, because a
//! client sees "connected" and then silence.
//!
//! Time is the monotonic clock, which on macOS stops while the machine
//! sleeps, so a lid closed overnight is not mistaken for a wedge.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

/// How often the accept loop beats when nothing else wakes it.
pub const BEAT_EVERY: Duration = Duration::from_secs(1);

/// How long the loop may go without a beat before it is declared wedged.
/// The stated bound: a wedge is reported within this plus one check
/// interval (at most a second). Thirty beats missed is not jitter.
pub const WEDGE_AFTER: Duration = Duration::from_secs(30);

/// The exit status of a daemon that declared itself wedged: `EX_TEMPFAIL`
/// (sysexits.h), "try again later", which is what a respawn does.
pub const EXIT_WEDGED: i32 = 75;

/// Proof of life from the serving loop.
pub struct Heartbeat {
    base: Instant,
    every: Duration,
    /// Milliseconds after `base` of the last beat.
    last_ms: AtomicU64,
}

impl Heartbeat {
    /// A heartbeat that counts as beaten now, expected every `every`.
    #[must_use]
    pub fn new(every: Duration) -> Arc<Self> {
        Arc::new(Self {
            base: Instant::now(),
            every,
            last_ms: AtomicU64::new(0),
        })
    }

    fn now_ms(&self) -> u64 {
        u64::try_from(self.base.elapsed().as_millis()).unwrap_or(u64::MAX)
    }

    /// The loop turned.
    pub fn beat(&self) {
        self.last_ms.store(self.now_ms(), Ordering::Release);
    }

    /// How often the loop should beat when idle.
    #[must_use]
    pub const fn every(&self) -> Duration {
        self.every
    }

    /// Time since the last beat.
    #[must_use]
    pub fn silent_for(&self) -> Duration {
        let last = self.last_ms.load(Ordering::Acquire);
        Duration::from_millis(self.now_ms().saturating_sub(last))
    }
}

/// Watch `heartbeat` on a dedicated OS thread; call `on_wedge` with the
/// silence once it exceeds `bound`, then stop watching.
///
/// Checks at a quarter of the bound (at most every second), so a wedge is
/// reported within `bound` plus one check.
///
/// # Panics
///
/// When the OS refuses to start a thread, at startup: a daemon that cannot
/// watch itself should not start believing it is watched.
pub fn watch(
    heartbeat: Arc<Heartbeat>,
    bound: Duration,
    on_wedge: impl FnOnce(Duration) + Send + 'static,
) -> std::thread::JoinHandle<()> {
    let check = (bound / 4).min(Duration::from_secs(1));
    std::thread::Builder::new()
        .name("divoomd-watchdog".into())
        .spawn(move || loop {
            let slept_from = Instant::now();
            std::thread::sleep(check);
            // The watchdog's own sleep overran by more than half the bound:
            // the whole process was suspended (SIGSTOP, a debugger), and the
            // loop's silence is the watchdog's own. Give the loop one check
            // to beat before judging it.
            if slept_from.elapsed() > check + bound / 2 {
                continue;
            }
            let silence = heartbeat.silent_for();
            if silence > bound {
                on_wedge(silence);
                return;
            }
        })
        .expect("spawn the watchdog thread")
}

/// The daemon's watchdog: exit [`EXIT_WEDGED`] on a wedge.
///
/// Before exiting it logs the silence and who held the connections -- the
/// evidence the 2026-09-07 wedge was lost for want of -- and the exit lets the
/// next client respawn a daemon that serves.
///
/// # Panics
///
/// As [`watch`]: only if the OS refuses a thread at startup.
#[must_use = "the handle is the only way to observe the watchdog thread"]
pub fn exit_when_wedged(
    heartbeat: Arc<Heartbeat>,
    census: Arc<crate::connections::Connections>,
    bound: Duration,
) -> std::thread::JoinHandle<()> {
    watch(heartbeat, bound, move |silence| {
        let held = census
            .try_snapshot()
            .map_or_else(|| "(table locked)".to_string(), |v| v.to_string());
        eprintln!(
            "divoomd: WEDGED -- the serving loop has not turned for {}ms (bound {}s); \
             exiting {EXIT_WEDGED} for a respawn. connections: {held}",
            silence.as_millis(),
            bound.as_secs(),
        );
        std::process::exit(EXIT_WEDGED);
    })
}
