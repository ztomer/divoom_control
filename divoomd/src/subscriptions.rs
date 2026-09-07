//! A bounded, self-cleaning subscription registry (LRU admission).
//!
//! # Why this replaces a blanket lifetime
//!
//! The first fix for accumulated subscriptions gave every subscription an
//! absolute deadline, so all of them renegotiated on a timer whether or not
//! anything was wrong. That is churn charged to healthy clients to solve a
//! problem caused by dead ones.
//!
//! This registry disturbs a subscription only when a NEW one needs the slot, and
//! then picks the least-recently-active occupant — and only if it has been
//! inactive for at least `renegotiate_after`. A busy daemon with room to spare
//! never evicts anybody; a daemon full of stale registrations heals the moment a
//! real client shows up.
//!
//! # What counts as activity
//!
//! Bytes FROM the client, nothing else.
//!
//! This is the whole point, and the reason the previous watchdog was useless.
//! That one reset its deadline every time the daemon DELIVERED an event, i.e. on
//! its own output. Events are a BROADCAST — every subscriber receives the same
//! ones — so deliveries move every deadline in lockstep and can never separate a
//! live subscriber from a dead one. Liveness evidence has to come from the peer.
//!
//! A client that never speaks is therefore never "active", and its entry ages
//! from the moment it subscribed. That is the correct default: we have no
//! evidence it is there, so it is the first thing displaced when a slot is
//! genuinely needed. Any byte a client sends counts, so a client that wants to
//! defend its slot only has to say something.

use std::sync::{Arc, Mutex};
use std::time::Duration;

use tokio::sync::Notify;
use tokio::time::Instant;

/// A subscription must be inactive at least this long before a newcomer may
/// take its slot. Below it the registry reports itself full instead, so a burst
/// of new clients cannot evict each other in a loop.
pub const RENEGOTIATE_AFTER: Duration = Duration::from_secs(600);

struct Entry {
    id: u64,
    last_active: Instant,
    evict: Arc<Notify>,
}

struct State {
    next_id: u64,
    entries: Vec<Entry>,
}

/// Bounded set of live subscriptions, ordered by last client activity.
pub struct Registry {
    capacity: usize,
    renegotiate_after: Duration,
    state: Mutex<State>,
}

/// A held subscription slot. Dropping it frees the slot, so a connection that
/// ends for any reason — EOF, error, idle, eviction — releases automatically.
pub struct Lease {
    registry: Arc<Registry>,
    pub id: u64,
    /// Notified when this subscription has been chosen for renegotiation. The
    /// serving task should tell the client and close.
    pub evict: Arc<Notify>,
}

impl Drop for Lease {
    fn drop(&mut self) {
        self.registry.release(self.id);
    }
}

impl Registry {
    pub fn new(capacity: usize, renegotiate_after: Duration) -> Arc<Self> {
        Arc::new(Self {
            capacity: capacity.max(1),
            renegotiate_after,
            state: Mutex::new(State {
                next_id: 1,
                entries: Vec::new(),
            }),
        })
    }

    /// Take a slot, evicting the least-recently-active entry if that is the only
    /// way and it has been quiet long enough. `None` means every slot is held by
    /// a subscription too recently active to disturb.
    pub fn admit(self: &Arc<Self>) -> Option<Lease> {
        let now = Instant::now();
        let mut st = self.state.lock().ok()?;

        if st.entries.len() >= self.capacity {
            // Least-recently-active occupant. `min_by_key` returns the FIRST
            // minimum, so equal timestamps break toward the oldest entry, which
            // is the one that has been unproven longest.
            let victim = st
                .entries
                .iter()
                .enumerate()
                .min_by_key(|(_, e)| e.last_active)
                .map(|(i, e)| (i, e.last_active, e.evict.clone()))?;
            let (idx, last_active, evict) = victim;
            if now.saturating_duration_since(last_active) < self.renegotiate_after {
                return None; // everyone here is demonstrably in use
            }
            st.entries.remove(idx);
            // Wake the evicted task AFTER removing it, so the slot is already
            // free and its own Lease drop is a no-op.
            evict.notify_one();
        }

        let id = st.next_id;
        st.next_id += 1;
        let evict = Arc::new(Notify::new());
        st.entries.push(Entry {
            id,
            last_active: now,
            evict: evict.clone(),
        });
        Some(Lease {
            registry: self.clone(),
            id,
            evict,
        })
    }

    /// Record that the client behind `id` said something.
    pub fn touch(&self, id: u64) {
        if let Ok(mut st) = self.state.lock() {
            let now = Instant::now();
            if let Some(e) = st.entries.iter_mut().find(|e| e.id == id) {
                e.last_active = now;
            }
        }
    }

    fn release(&self, id: u64) {
        if let Ok(mut st) = self.state.lock() {
            st.entries.retain(|e| e.id != id);
        }
    }

    pub fn len(&self) -> usize {
        self.state.lock().map(|s| s.entries.len()).unwrap_or(0)
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    pub fn capacity(&self) -> usize {
        self.capacity
    }
}

#[cfg(test)]
#[path = "subscriptions_tests.rs"]
mod tests;
