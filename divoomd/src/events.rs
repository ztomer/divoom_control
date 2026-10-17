//! The daemon's event bus, with the latest value of every key kept (P2.5).
//!
//! Subscribers share one `tokio::sync::broadcast` ring. A subscriber that
//! falls behind it loses the oldest events (`Lagged(n)`) -- and a status
//! subscriber wants the CURRENT truth, not the history, so a hole is the wrong
//! failure and a disconnect is a worse one. Conflation (latest value per key)
//! is the method of record for state streams: the ring stays the delivery path
//! for a subscriber that keeps up, and one that falls behind is resynchronised
//! from [`Events::latest`] instead of being told it has a gap.
//!
//! Every publish goes through [`Events::send`], which records the value and
//! broadcasts it under ONE lock, so the recorded order and the delivered order
//! are the same order: a resync can never hand a subscriber an older value for
//! a key than the stream it is rejoining would have.

use std::collections::HashMap;
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};

use serde_json::Value;
use tokio::sync::broadcast;

/// Ring size for subscribers that keep up. A subscriber further behind than
/// this is resynchronised from the latest values, not dropped.
pub const RING: usize = 32;

#[derive(Default)]
struct Latest {
    seq: u64,
    by_key: HashMap<String, (u64, Value)>,
}

/// Broadcast with conflation: see the module docs.
pub struct Events {
    tx: broadcast::Sender<Value>,
    latest: Mutex<Latest>,
}

impl Events {
    #[must_use]
    pub fn new(capacity: usize) -> Arc<Self> {
        let (tx, _) = broadcast::channel(capacity.max(1));
        Arc::new(Self {
            tx,
            latest: Mutex::new(Latest::default()),
        })
    }

    /// A bus and a receiver on it, the shape `broadcast::channel` returns.
    #[must_use]
    pub fn channel(capacity: usize) -> (Arc<Self>, broadcast::Receiver<Value>) {
        let bus = Self::new(capacity);
        let rx = bus.subscribe();
        (bus, rx)
    }

    /// A poisoned lock still holds usable values: each write replaces one
    /// whole entry, so there is no half-made state to protect.
    fn lock(&self) -> MutexGuard<'_, Latest> {
        self.latest.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// What an event supersedes: the previous event with the same key.
    ///
    /// A job's state is per job (`kind`) on a panel; every other event is per
    /// panel (`mac`, or `lan_ip` for a LAN panel), or fleet-wide when it names
    /// none. `activity` is deliberately NOT split by `kind`: a panel shows one
    /// thing, so a new activity replaces the old one whatever its kind.
    #[must_use]
    pub fn key(ev: &Value) -> String {
        let field = |k: &str| ev.get(k).and_then(Value::as_str).unwrap_or("");
        let ty = field("type");
        let panel = ev
            .get("mac")
            .or_else(|| ev.get("lan_ip"))
            .and_then(Value::as_str)
            .unwrap_or("");
        if ty == "live_job_state" {
            format!("{ty}|{panel}|{}", field("kind"))
        } else {
            format!("{ty}|{panel}")
        }
    }

    /// Record `ev` as its key's latest value and broadcast it.
    ///
    /// # Errors
    ///
    /// When nobody is subscribed, exactly as `broadcast::Sender::send`; the
    /// value is still recorded, so a later subscriber's resync carries it.
    pub fn send(&self, ev: Value) -> Result<usize, broadcast::error::SendError<Value>> {
        let mut st = self.lock();
        st.seq += 1;
        let seq = st.seq;
        st.by_key.insert(Self::key(&ev), (seq, ev.clone()));
        // Under the lock on purpose (module docs): `send` is synchronous and
        // never waits on a receiver, so holding it here costs nothing.
        let sent = self.tx.send(ev);
        drop(st);
        sent
    }

    /// A receiver starting at the next event.
    #[must_use]
    pub fn subscribe(&self) -> broadcast::Receiver<Value> {
        self.tx.subscribe()
    }

    /// Re-attach `rx` at the tail and return every key's latest value, in the
    /// order they were published. Atomic with respect to [`Self::send`]: an
    /// event is either in the returned values or ahead of `rx`, and anything
    /// in both is the same value twice, which a state reader absorbs.
    #[must_use]
    pub fn resync(&self, rx: &mut broadcast::Receiver<Value>) -> Vec<Value> {
        let st = self.lock();
        *rx = self.tx.subscribe();
        let mut all: Vec<(u64, Value)> = st.by_key.values().cloned().collect();
        drop(st);
        all.sort_by_key(|(seq, _)| *seq);
        all.into_iter().map(|(_, v)| v).collect()
    }
}

#[cfg(test)]
#[path = "events_tests.rs"]
mod tests;
