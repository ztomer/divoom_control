//! The subscriber retry loop, extracted so it is testable.
//!
//! R53.39 (ported from the Python menubar, which this agent replaced): the
//! subscriber loop must NOT permanently die when the daemon drops. The old
//! Python implementation called its shutdown hook and then unconditionally
//! `return`ed, killing the reader thread — so after ANY daemon restart the
//! menubar sat frozen forever, never re-subscribing. That bug shipped once; the
//! guard against it must not be lost just because the implementation moved from
//! Python to Rust.
//!
//! The loop itself lived inline in `main.rs` inside a `thread::spawn`, which
//! made it unreachable from a test. It lives here instead, with `subscribe` and
//! `sleep` injected, so the "keeps re-subscribing" and "stops when quitting"
//! behaviours are both pinned by unit tests.

/// Re-subscribe until told to quit.
///
/// `subscribe` blocks until the subscription ends (daemon drop, or `should_quit`
/// going true). `sleep` backs off between attempts so a dead daemon does not
/// spin a tight reconnect loop. Returns the number of subscribe attempts made,
/// which is what the tests assert on.
pub fn resubscribe_until_quit(
    mut subscribe: impl FnMut(),
    mut sleep: impl FnMut(),
    should_quit: impl Fn() -> bool,
) -> usize {
    let mut attempts = 0;
    while !should_quit() {
        subscribe();
        attempts += 1;
        // Re-check BEFORE sleeping: on quit we exit promptly rather than
        // idling through a full retry delay on shutdown.
        if should_quit() {
            break;
        }
        sleep();
    }
    attempts
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::Cell;

    #[test]
    fn keeps_resubscribing_after_the_daemon_drops() {
        // The R53.39 regression: a subscribe() that returns immediately
        // (connection lost) must be retried, not treated as terminal.
        let quit_after = 5;
        let calls = Cell::new(0);
        let sleeps = Cell::new(0);

        let n = resubscribe_until_quit(
            || calls.set(calls.get() + 1),
            || sleeps.set(sleeps.get() + 1),
            || calls.get() >= quit_after,
        );

        assert_eq!(n, quit_after, "must retry until asked to quit");
        assert!(calls.get() >= 2, "a single drop must not end the loop");
        // Backs off between attempts, but not after the final one.
        assert_eq!(sleeps.get(), quit_after - 1);
    }

    #[test]
    fn does_not_subscribe_at_all_when_already_quitting() {
        let calls = Cell::new(0);
        let n = resubscribe_until_quit(|| calls.set(calls.get() + 1), || {}, || true);
        assert_eq!(n, 0);
        assert_eq!(calls.get(), 0);
    }

    #[test]
    fn stops_promptly_without_sleeping_when_quit_arrives_mid_loop() {
        // Quit flips true during the first subscribe(); we must break before
        // the backoff sleep rather than idling through shutdown.
        let calls = Cell::new(0);
        let sleeps = Cell::new(0);

        let n = resubscribe_until_quit(
            || calls.set(calls.get() + 1),
            || sleeps.set(sleeps.get() + 1),
            || calls.get() >= 1,
        );

        assert_eq!(n, 1);
        assert_eq!(sleeps.get(), 0, "must not sleep on the way out");
    }
}
