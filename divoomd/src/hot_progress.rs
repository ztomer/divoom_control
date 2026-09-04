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
#[derive(Clone)]
pub struct HotProgress {
    inner: Arc<Mutex<Value>>,
    /// Event sink. `None` only in tests that construct a bare progress cell;
    /// the daemon always wires this to its broadcast channel.
    tx: Option<tokio::sync::broadcast::Sender<Value>>,
}

impl Default for HotProgress {
    fn default() -> Self {
        Self {
            inner: Arc::new(Mutex::new(json!({"phase": "idle"}))),
            tx: None,
        }
    }
}

impl HotProgress {
    /// Build a progress cell wired to the daemon's event bus.
    pub fn with_events(tx: tokio::sync::broadcast::Sender<Value>) -> Self {
        Self {
            inner: Arc::new(Mutex::new(json!({"phase": "idle"}))),
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
    pub fn set(&self, val: Value) {
        if let Ok(mut g) = self.inner.lock() {
            *g = val.clone();
        }
        self.broadcast(&val);
    }

    pub fn get(&self) -> Value {
        self.inner
            .lock()
            .map(|g| g.clone())
            .unwrap_or_else(|_| json!({}))
    }

    /// Atomically claim the slot; returns false if an update is already running.
    pub fn try_begin(&self) -> bool {
        {
            let mut g = match self.inner.lock() {
                Ok(g) => g,
                Err(_) => return false,
            };
            let phase = g.get("phase").and_then(|v| v.as_str()).unwrap_or("idle");
            if matches!(
                phase,
                "starting" | "fetching_manifest" | "downloading" | "uploading"
            ) {
                return false;
            }
            *g = json!({"phase": "starting"});
        } // release the lock before broadcasting — a subscriber callback must
          // never be able to re-enter this mutex.
        self.broadcast(&json!({"phase": "starting"}));
        true
    }

    /// Reset a stuck "starting" state (queue-expired before task ran).
    pub fn clear_stuck_starting(&self) {
        let stuck = {
            match self.inner.lock() {
                Ok(mut g) => {
                    if g.get("phase").and_then(|v| v.as_str()) == Some("starting") {
                        let v = json!({"phase":"error","error":"hot update did not start (queue timeout)"});
                        *g = v.clone();
                        Some(v)
                    } else {
                        None
                    }
                }
                Err(_) => None,
            }
        };
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
        let (tx, mut rx) = tokio::sync::broadcast::channel(32);
        let p = HotProgress::with_events(tx);

        p.set(json!({"phase": "fetching_manifest"}));
        p.set(json!({"phase": "downloading", "current": 1, "total": 3}));
        p.set(json!({"phase": "uploading", "current": 2, "total": 3}));
        p.set(json!({"phase": "done", "result": {"served": []}}));

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
        let (tx, mut rx) = tokio::sync::broadcast::channel(8);
        let p = HotProgress::with_events(tx);
        p.set(json!({"phase": "downloading", "current": 1, "total": 2}));
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
        let (tx, mut rx) = tokio::sync::broadcast::channel(8);
        let p = HotProgress::with_events(tx);
        assert!(p.try_begin());
        let events = drain(&mut rx);
        assert_eq!(events.len(), 1, "claiming the slot is a phase change");
        assert_eq!(events[0]["phase"], json!("starting"));
    }

    #[test]
    fn try_begin_refuses_a_second_run_and_stays_silent() {
        let (tx, mut rx) = tokio::sync::broadcast::channel(8);
        let p = HotProgress::with_events(tx);
        assert!(p.try_begin());
        drain(&mut rx);
        assert!(!p.try_begin(), "a second concurrent update must be refused");
        assert!(
            drain(&mut rx).is_empty(),
            "a refused claim is not a phase change"
        );
    }

    #[test]
    fn clear_stuck_starting_broadcasts_the_error() {
        // Without this event the UI would sit on "Preparing..." even though the
        // daemon had given up — the exact hang, one layer down.
        let (tx, mut rx) = tokio::sync::broadcast::channel(8);
        let p = HotProgress::with_events(tx);
        assert!(p.try_begin());
        drain(&mut rx);
        p.clear_stuck_starting();
        let events = drain(&mut rx);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0]["phase"], json!("error"));
    }

    #[test]
    fn clear_stuck_starting_is_a_no_op_when_not_stuck() {
        let (tx, mut rx) = tokio::sync::broadcast::channel(8);
        let p = HotProgress::with_events(tx);
        p.set(json!({"phase": "done"}));
        drain(&mut rx);
        p.clear_stuck_starting();
        assert!(drain(&mut rx).is_empty());
        assert_eq!(p.get()["phase"], json!("done"));
    }

    #[test]
    fn stored_state_still_matches_the_last_event() {
        // hot_update_progress (the resync path) must agree with the stream.
        let (tx, mut rx) = tokio::sync::broadcast::channel(8);
        let p = HotProgress::with_events(tx);
        p.set(json!({"phase": "uploading", "current": 7, "total": 9}));
        let events = drain(&mut rx);
        assert_eq!(p.get()["phase"], events[0]["phase"]);
        assert_eq!(p.get()["current"], events[0]["current"]);
    }

    #[test]
    fn a_cell_without_subscribers_does_not_fail() {
        // No UI attached is the normal case, not an error.
        let (tx, rx) = tokio::sync::broadcast::channel(4);
        drop(rx);
        let p = HotProgress::with_events(tx);
        p.set(json!({"phase": "done"}));
        assert_eq!(p.get()["phase"], json!("done"));
    }
}
