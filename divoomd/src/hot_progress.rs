//! Hot-channel update progress — stored for polling AND broadcast to subscribers.
//!
//! Split out of `art.rs` in R67 when that file crossed the house 500-line cap.

use serde_json::{json, Value};
use std::sync::{Arc, Mutex};

/// Hot-update progress: stored for polling AND broadcast to subscribers.
///
/// R67/C6: this used to be a bare `Arc<Mutex<Value>>` that only stored. R59
/// deleted the GUI's 600 ms poll in favour of `hot_progress` events, but the
/// only code emitting that event was `sync_artwork.rs` — a different flow. The
/// hot-channel path called `set()` five times and broadcast nothing, so the
/// button sat on "Preparing..." forever and, because the terminal event never
/// arrived, stayed disabled after the first click.
///
/// Store-and-broadcast are now the SAME operation. There is no way to advance
/// the phase without telling subscribers, because there is no setter that only
/// stores. `hot_update_progress` remains as an explicit resync path for a
/// client that connects mid-update or misses an event.
///
/// U.5: every phase names the panel the run is for (`mac`, set by
/// [`HotProgress::try_begin`]). The events named no panel, so the Hot tab
/// showed another panel's Sync Now on whichever panel it was showing.
#[derive(Clone)]
pub struct HotProgress {
    inner: Arc<Mutex<Value>>,
    /// The panel the running (or last) update is for.
    panel: Arc<Mutex<String>>,
    /// Event sink. `None` only in tests that construct a bare progress cell;
    /// the daemon always wires this to its broadcast channel.
    tx: Option<Arc<crate::events::Events>>,
}

impl Default for HotProgress {
    fn default() -> Self {
        Self {
            inner: Arc::new(Mutex::new(json!({"phase": "idle"}))),
            panel: Arc::new(Mutex::new(String::new())),
            tx: None,
        }
    }
}

impl HotProgress {
    /// Build a progress cell wired to the daemon's event bus.
    #[must_use]
    pub fn with_events(tx: Arc<crate::events::Events>) -> Self {
        Self {
            inner: Arc::new(Mutex::new(json!({"phase": "idle"}))),
            panel: Arc::new(Mutex::new(String::new())),
            tx: Some(tx),
        }
    }

    /// Publish an already-stored value to subscribers.
    ///
    /// `send` fails only when there are no receivers, which is normal (no UI
    /// attached) and not an error worth surfacing.
    fn broadcast(&self, val: &Value) {
        if let Some(tx) = &self.tx {
            let mut ev = val.clone();
            if let Some(obj) = ev.as_object_mut() {
                obj.insert("type".into(), json!("hot_progress"));
            }
            let _ = tx.send(ev);
        }
    }

    /// Store the new phase AND tell every subscriber. There is deliberately no
    /// store-only variant — that split is what broke the UI.
    pub fn set(&self, val: &Value) {
        let val = self.named(val);
        if let Ok(mut g) = self.inner.lock() {
            *g = val.clone();
        }
        self.broadcast(&val);
    }

    /// `val` carrying the panel the update is for, when one is named.
    fn named(&self, val: &Value) -> Value {
        let mut v = val.clone();
        let panel = self.panel.lock().map(|p| p.clone()).unwrap_or_default();
        if let (false, Some(obj)) = (panel.is_empty(), v.as_object_mut()) {
            obj.insert("mac".into(), json!(panel));
        }
        v
    }

    #[must_use]
    pub fn get(&self) -> Value {
        self.inner.lock().map_or_else(|_| json!({}), |g| g.clone())
    }

    /// Atomically claim the slot for the panel `mac` names; returns false if
    /// an update is already running.
    #[must_use]
    pub fn try_begin(&self, mac: &str) -> bool {
        let starting = {
            let Ok(mut g) = self.inner.lock() else {
                return false;
            };
            let phase = g.get("phase").and_then(|v| v.as_str()).unwrap_or("idle");
            if matches!(
                phase,
                "starting" | "fetching_manifest" | "downloading" | "uploading"
            ) {
                return false;
            }
            if let Ok(mut p) = self.panel.lock() {
                *p = mac.to_string();
            }
            let starting = self.named(&json!({"phase": "starting"}));
            *g = starting.clone();
            starting
        }; // release the lock before broadcasting — a subscriber callback must
           // never be able to re-enter this mutex.
        self.broadcast(&starting);
        true
    }

    /// Reset a stuck "starting" state (queue-expired before task ran).
    pub fn clear_stuck_starting(&self) {
        // A poisoned mutex means another thread died holding it: nothing
        // coherent to reset, so there is nothing to broadcast.
        let stuck = self.inner.lock().ok().and_then(|mut g| {
            if g.get("phase").and_then(|v| v.as_str()) == Some("starting") {
                let v = self.named(
                    &json!({"phase":"error","error":"hot update did not start (queue timeout)"}),
                );
                *g = v.clone();
                Some(v)
            } else {
                None
            }
        });
        if let Some(v) = stuck {
            self.broadcast(&v);
        }
    }
}

#[cfg(test)]
mod hot_progress_tests {
    use super::HotProgress;
    use serde_json::json;

    /// Drain everything currently queued on a receiver.
    fn drain(
        rx: &mut tokio::sync::broadcast::Receiver<serde_json::Value>,
    ) -> Vec<serde_json::Value> {
        let mut out = Vec::new();
        while let Ok(v) = rx.try_recv() {
            out.push(v);
        }
        out
    }

    #[test]
    fn set_broadcasts_every_phase() {
        // R67/C6: the whole defect. `set` stored and did not emit, so a UI that
        // had dropped its poll saw nothing at all.
        let tx = crate::events::Events::new(32);
        let mut rx = tx.subscribe();
        let p = HotProgress::with_events(tx);

        p.set(&json!({"phase": "fetching_manifest"}));
        p.set(&json!({"phase": "downloading", "current": 1, "total": 3}));
        p.set(&json!({"phase": "uploading", "current": 2, "total": 3}));
        p.set(&json!({"phase": "done", "result": {"served": []}}));

        let events = drain(&mut rx);
        let phases: Vec<&str> = events
            .iter()
            .filter_map(|e| e.get("phase").and_then(|v| v.as_str()))
            .collect();
        assert_eq!(
            phases,
            vec!["fetching_manifest", "downloading", "uploading", "done"],
            "every set() must reach subscribers, in order"
        );
    }

    #[test]
    fn broadcast_events_are_tagged_hot_progress() {
        // The GUI forwarder routes purely on `type`; an untagged event is
        // dropped on the floor before it reaches window.Divoom.onHotProgress.
        let (tx, mut rx) = crate::events::Events::channel(8);
        let p = HotProgress::with_events(tx);
        p.set(&json!({"phase": "downloading", "current": 1, "total": 2}));
        let events = drain(&mut rx);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0]["type"], json!("hot_progress"));
        assert_eq!(
            events[0]["current"],
            json!(1),
            "payload fields survive tagging"
        );
    }

    #[test]
    fn try_begin_broadcasts_the_starting_phase() {
        let (tx, mut rx) = crate::events::Events::channel(8);
        let p = HotProgress::with_events(tx);
        assert!(p.try_begin("P1"));
        let events = drain(&mut rx);
        assert_eq!(events.len(), 1, "claiming the slot is a phase change");
        assert_eq!(events[0]["phase"], json!("starting"));
    }

    /// U.5: every phase names its panel, so a client shows a run only on the
    /// panel it is for.
    #[test]
    fn every_phase_names_the_panel_the_run_is_for() {
        let (tx, mut rx) = crate::events::Events::channel(8);
        let p = HotProgress::with_events(tx);
        assert!(p.try_begin("f90d2cc9"));
        p.set(&json!({"phase": "uploading", "current": 1, "total": 2}));
        p.set(&json!({"phase": "done", "result": {}}));
        let events = drain(&mut rx);
        assert_eq!(events.len(), 3);
        for e in &events {
            assert_eq!(e["mac"], json!("f90d2cc9"), "{e}");
        }
        assert_eq!(p.get()["mac"], json!("f90d2cc9"), "the poll names it too");
    }

    #[test]
    fn try_begin_refuses_a_second_run_and_stays_silent() {
        let (tx, mut rx) = crate::events::Events::channel(8);
        let p = HotProgress::with_events(tx);
        assert!(p.try_begin("P1"));
        drain(&mut rx);
        assert!(
            !p.try_begin("P2"),
            "a second concurrent update must be refused"
        );
        assert_eq!(
            drain(&mut rx).len(),
            0,
            "a refused claim is not a phase change"
        );
    }

    #[test]
    fn clear_stuck_starting_broadcasts_the_error() {
        // Without this event the UI would sit on "Preparing..." even though the
        // daemon had given up — the exact hang, one layer down.
        let (tx, mut rx) = crate::events::Events::channel(8);
        let p = HotProgress::with_events(tx);
        assert!(p.try_begin("P1"));
        drain(&mut rx);
        p.clear_stuck_starting();
        let events = drain(&mut rx);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0]["phase"], json!("error"));
    }

    #[test]
    fn clear_stuck_starting_is_a_no_op_when_not_stuck() {
        let (tx, mut rx) = crate::events::Events::channel(8);
        let p = HotProgress::with_events(tx);
        p.set(&json!({"phase": "done"}));
        drain(&mut rx);
        p.clear_stuck_starting();
        // Held in a local so a failure prints WHICH progress messages were
        // queued rather than just "some were".
        let leftover = drain(&mut rx);
        assert_eq!(
            leftover,
            [] as [serde_json::Value; 0],
            "clear_stuck_starting must not queue a message"
        );
        assert_eq!(p.get()["phase"], json!("done"));
    }

    #[test]
    fn stored_state_still_matches_the_last_event() {
        // hot_update_progress (the resync path) must agree with the stream.
        let (tx, mut rx) = crate::events::Events::channel(8);
        let p = HotProgress::with_events(tx);
        p.set(&json!({"phase": "uploading", "current": 7, "total": 9}));
        let events = drain(&mut rx);
        assert_eq!(p.get()["phase"], events[0]["phase"]);
        assert_eq!(p.get()["current"], events[0]["current"]);
    }

    #[test]
    fn a_cell_without_subscribers_does_not_fail() {
        // No UI attached is the normal case, not an error.
        let (tx, rx) = crate::events::Events::channel(4);
        drop(rx);
        let p = HotProgress::with_events(tx);
        p.set(&json!({"phase": "done"}));
        assert_eq!(p.get()["phase"], json!("done"));
    }
}
