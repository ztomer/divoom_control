//! Live-job health: say what a job is actually doing.
//!
//! # Why (R67, class C4)
//!
//! Every live job had this shape:
//!
//! ```ignore
//! if get_device_transport(&daemon, &mac).await.is_some() {
//!     ... push ...
//! }                       // else: nothing. No event, no state, no error.
//! tokio::time::sleep(interval).await;
//! ```
//!
//! With no device connected the job pushed nothing, said nothing, and slept —
//! for **15 minutes** in weather's case. The GUI toggle made it worse by
//! returning `True` without reading the daemon's reply, so "enabled" and
//! "working" were indistinguishable. A user with a disconnected device saw a
//! green switch and a dead widget, with nothing anywhere to explain it.
//!
//! A job now publishes its state on every transition, so the UI can render the
//! difference between *running*, *waiting for a device*, and *failing* — and so
//! "nothing is happening" always carries a reason (house rule: honest states).
//!
//! Transitions only: a job that is waiting says so once, not every tick, or the
//! event stream becomes a heartbeat nobody reads.

use serde_json::{json, Value};
use std::sync::Mutex;
use std::time::Duration;

/// What a live job is doing right now.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum JobState {
    /// Pushing frames normally.
    Running,
    /// Alive, but the device it targets is not connected. Not an error — the
    /// user unplugged something — but it must be VISIBLE.
    WaitingForDevice,
    /// The last cycle failed, with a reason.
    Failed(String),
}

impl JobState {
    fn tag(&self) -> &'static str {
        match self {
            Self::Running => "running",
            Self::WaitingForDevice => "waiting_for_device",
            Self::Failed(_) => "failed",
        }
    }

    /// A short, user-facing explanation. A state the UI cannot explain is not
    /// much better than silence.
    fn detail(&self) -> Option<&str> {
        match self {
            Self::Failed(reason) => Some(reason),
            _ => None,
        }
    }
}

/// Publishes a job's state to the daemon event bus, but only when it CHANGES.
pub struct JobHealth {
    kind: String,
    mac: String,
    tx: tokio::sync::broadcast::Sender<Value>,
    last: Mutex<Option<JobState>>,
}

impl JobHealth {
    pub fn new(kind: &str, mac: &str, tx: tokio::sync::broadcast::Sender<Value>) -> Self {
        Self {
            kind: kind.to_string(),
            mac: mac.to_string(),
            tx,
            last: Mutex::new(None),
        }
    }

    /// Record the current state; emit `live_job_state` if it differs from the
    /// last one. Returns true when an event was emitted.
    pub fn report(&self, state: JobState) -> bool {
        {
            let mut guard = match self.last.lock() {
                Ok(g) => g,
                Err(_) => return false,
            };
            if guard.as_ref() == Some(&state) {
                return false;
            }
            *guard = Some(state.clone());
        }
        let mut ev = json!({
            "type": "live_job_state",
            "kind": self.kind,
            "mac": self.mac,
            "state": state.tag(),
        });
        if let Some(d) = state.detail() {
            ev["detail"] = json!(d);
        }
        let _ = self.tx.send(ev);
        true
    }

    /// Convenience: report Running.
    pub fn running(&self) -> bool {
        self.report(JobState::Running)
    }

    /// Convenience: report WaitingForDevice.
    pub fn waiting(&self) -> bool {
        self.report(JobState::WaitingForDevice)
    }

    /// Convenience: report Failed.
    pub fn failed(&self, reason: impl Into<String>) -> bool {
        self.report(JobState::Failed(reason.into()))
    }
}

/// How long to wait before re-checking, given the job's normal interval.
///
/// A job with nothing to talk to should NOT sleep through its full cycle:
/// weather's is 15 minutes, so reconnecting a device left the widget dead for
/// up to a quarter of an hour. While waiting, poll briskly enough to feel
/// instant, and never longer than the job's own interval.
pub fn wait_interval(normal: Duration) -> Duration {
    const WAITING_POLL: Duration = Duration::from_secs(5);
    if normal < WAITING_POLL {
        normal
    } else {
        WAITING_POLL
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn bus() -> (
        tokio::sync::broadcast::Sender<Value>,
        tokio::sync::broadcast::Receiver<Value>,
    ) {
        tokio::sync::broadcast::channel(16)
    }

    fn drain(rx: &mut tokio::sync::broadcast::Receiver<Value>) -> Vec<Value> {
        let mut out = Vec::new();
        while let Ok(v) = rx.try_recv() {
            out.push(v);
        }
        out
    }

    #[test]
    fn waiting_for_device_is_announced_not_silent() {
        // The C4 defect: a job with no device said nothing at all.
        let (tx, mut rx) = bus();
        let h = JobHealth::new("weather", "AA:BB", tx);
        assert!(h.waiting());
        let events = drain(&mut rx);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0]["type"], json!("live_job_state"));
        assert_eq!(events[0]["state"], json!("waiting_for_device"));
        assert_eq!(events[0]["kind"], json!("weather"));
        assert_eq!(events[0]["mac"], json!("AA:BB"));
    }

    #[test]
    fn only_transitions_are_published() {
        // Otherwise a 5s waiting poll becomes a 5s heartbeat nobody reads.
        let (tx, mut rx) = bus();
        let h = JobHealth::new("music", "AA:BB", tx);
        assert!(h.waiting());
        assert!(!h.waiting(), "repeat of the same state must not re-emit");
        assert!(!h.waiting());
        assert_eq!(drain(&mut rx).len(), 1);
    }

    #[test]
    fn recovering_is_published() {
        let (tx, mut rx) = bus();
        let h = JobHealth::new("sysmon", "AA:BB", tx);
        h.waiting();
        drain(&mut rx);
        assert!(h.running(), "waiting -> running is a transition");
        let events = drain(&mut rx);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0]["state"], json!("running"));
    }

    #[test]
    fn failures_carry_their_reason() {
        // "It stopped working" with no reason is the silence this replaces.
        let (tx, mut rx) = bus();
        let h = JobHealth::new("stocks", "AA:BB", tx);
        assert!(h.failed("wttr.in returned 503"));
        let events = drain(&mut rx);
        assert_eq!(events[0]["state"], json!("failed"));
        assert_eq!(events[0]["detail"], json!("wttr.in returned 503"));
    }

    #[test]
    fn a_different_failure_reason_is_a_new_transition() {
        let (tx, mut rx) = bus();
        let h = JobHealth::new("stocks", "AA:BB", tx);
        h.failed("timeout");
        drain(&mut rx);
        assert!(h.failed("503"), "a different reason is worth reporting");
        assert_eq!(drain(&mut rx).len(), 1);
    }

    #[test]
    fn waiting_poll_never_exceeds_the_jobs_own_interval() {
        // weather's 15-minute cycle must not become a 15-minute blind spot.
        assert_eq!(
            wait_interval(Duration::from_secs(900)),
            Duration::from_secs(5)
        );
        assert_eq!(
            wait_interval(Duration::from_secs(15)),
            Duration::from_secs(5)
        );
        // A job that already ticks faster than the poll keeps its own cadence.
        assert_eq!(
            wait_interval(Duration::from_secs(2)),
            Duration::from_secs(2)
        );
    }
}
