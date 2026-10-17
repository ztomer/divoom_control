//! Who is connected to the daemon, by kind, with ages.
//!
//! The 2026-09-07 wedge (every one of 64 connection permits held) is impossible
//! by construction now, but its CAUSE was never found: the only instrument was
//! killing the daemon, which destroyed the evidence. The connection semaphore
//! and the subscription registry each knew a count and nobody ever read it.
//!
//! This table is the one place that does. Every accepted connection registers
//! here for its lifetime (a [`Tracked`] guard; dropping it is the only way out,
//! so a connection that ends for ANY reason leaves the table), says what kind
//! it is, which command it is running, and when its peer last spoke.
//! `get_status` returns [`Connections::snapshot`], so a daemon that is filling
//! up can be asked who is holding it -- by peer pid on the unix socket --
//! without being killed.
//!
//! One table per daemon, shared by every listener (unix and TCP): the question
//! "who holds this daemon" has one answer, and each entry names its transport.

use std::collections::BTreeMap;
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};

use serde_json::{json, Value};
use tokio::time::Instant;

/// What a connection is doing with its slot.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    /// Request/reply: holds a slot only while it asks.
    Request,
    /// Long-lived by design: holds a slot for as long as it is subscribed.
    Subscription,
}

impl Kind {
    const fn name(self) -> &'static str {
        match self {
            Self::Request => "request",
            Self::Subscription => "subscription",
        }
    }
}

struct Conn {
    kind: Kind,
    transport: &'static str,
    pid: Option<i32>,
    opened: Instant,
    last_active: Instant,
    /// The command in flight, with when it started; `None` between requests.
    running: Option<(String, Instant)>,
}

#[derive(Default)]
struct State {
    next_id: u64,
    open: BTreeMap<u64, Conn>,
    /// Per transport: (connection cap, subscription budget).
    limits: BTreeMap<&'static str, (usize, usize)>,
}

/// The daemon's live connection table.
#[derive(Default)]
pub struct Connections {
    state: Mutex<State>,
}

/// One connection's entry, held for the connection's lifetime.
pub struct Tracked {
    table: Arc<Connections>,
    id: u64,
}

impl Connections {
    #[must_use]
    pub fn new() -> Arc<Self> {
        Arc::new(Self::default())
    }

    /// A poisoned lock still holds a usable table: every write here is a
    /// single field store, so there is no half-made invariant to protect, and
    /// refusing to report would hide exactly the state this exists to show.
    fn lock(&self) -> MutexGuard<'_, State> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// Register an accepted connection. It starts as a request; a subscribe
    /// re-kinds it ([`Tracked::mark_subscription`]).
    pub fn open(self: &Arc<Self>, transport: &'static str, pid: Option<i32>) -> Tracked {
        let now = Instant::now();
        let mut st = self.lock();
        st.next_id += 1;
        let id = st.next_id;
        st.open.insert(
            id,
            Conn {
                kind: Kind::Request,
                transport,
                pid,
                opened: now,
                last_active: now,
                running: None,
            },
        );
        drop(st);
        Tracked {
            table: self.clone(),
            id,
        }
    }

    /// Record a listener's budgets so the snapshot can say how full it is.
    pub fn set_limits(&self, transport: &'static str, connections: usize, subscriptions: usize) {
        self.lock()
            .limits
            .insert(transport, (connections, subscriptions));
    }

    /// How many open connections are of `kind`.
    #[must_use]
    pub fn count(&self, kind: Kind) -> usize {
        self.lock().open.values().filter(|c| c.kind == kind).count()
    }

    /// Everything a reader needs to say who holds the daemon: counts by kind,
    /// each listener's budget, and every open connection with its age, its
    /// peer's silence, and the command it is running.
    #[must_use]
    pub fn snapshot(&self) -> Value {
        let now = Instant::now();
        let st = self.lock();
        let ms = |since: Instant| {
            u64::try_from(now.saturating_duration_since(since).as_millis()).unwrap_or(u64::MAX)
        };
        let mut counts = BTreeMap::from([("request", 0usize), ("subscription", 0)]);
        let open: Vec<Value> = st
            .open
            .iter()
            .map(|(id, c)| {
                *counts.entry(c.kind.name()).or_default() += 1;
                json!({
                    "id": id,
                    "kind": c.kind.name(),
                    "transport": c.transport,
                    "pid": c.pid,
                    "age_ms": ms(c.opened),
                    "idle_ms": ms(c.last_active),
                    "command": c.running.as_ref().map(|(name, _)| name),
                    "command_ms": c.running.as_ref().map(|(_, at)| ms(*at)),
                })
            })
            .collect();
        let limits: serde_json::Map<String, Value> = st
            .limits
            .iter()
            .map(|(t, (c, s))| {
                (
                    (*t).to_string(),
                    json!({ "connections": c, "subscriptions": s }),
                )
            })
            .collect();
        drop(st);
        json!({ "counts": counts, "limits": limits, "open": open })
    }

    fn with(&self, id: u64, f: impl FnOnce(&mut Conn)) {
        if let Some(c) = self.lock().open.get_mut(&id) {
            f(c);
        }
    }
}

impl Tracked {
    /// The peer sent bytes: the only liveness evidence there is.
    pub fn touch(&self) {
        self.table.with(self.id, |c| c.last_active = Instant::now());
    }

    /// This connection is now a subscriber.
    pub fn mark_subscription(&self) {
        self.table.with(self.id, |c| c.kind = Kind::Subscription);
    }

    /// A command started (`Some`) or finished (`None`) on this connection.
    pub fn running(&self, command: Option<&str>) {
        self.table.with(self.id, |c| {
            c.running = command.map(|name| (name.to_string(), Instant::now()));
        });
    }
}

impl Drop for Tracked {
    fn drop(&mut self) {
        self.table.lock().open.remove(&self.id);
    }
}

#[cfg(test)]
#[path = "connections_tests.rs"]
mod tests;
