//! One panel, one struct: identity, connection, live job, activity.
//!
//! Before this existed (2026-09-12) a device was five maps that happened to
//! share a key: `devices` (transport), `queues` (serialization), the legacy
//! single `device` + `device_id` pair, and the live-job coordinator's task /
//! params / health / activity tables. Every "widget keeps coming back" defect
//! in `tests/live_jobs_stress.rs` was two of those disagreeing: a mac-less
//! `device_call` riding the daemon-global queue while the live job for the
//! same panel rode the per-mac one; a frame queued by a job the user had
//! stopped landing anyway; a frame from a job that died with a disconnect
//! landing on the RECONNECTED panel because the queued closure re-resolved
//! the transport by mac and found the new one.
//!
//! The model that makes those states unrepresentable:
//!
//! * a [`Device`] is the panel's IDENTITY. It owns the live job and the
//!   activity record, so a widget survives a link blip;
//! * a [`Link`] is one CONNECTION to that panel: the transport and the ONE
//!   queue everything sent to it goes through. Queued work holds the `Link`
//!   it was queued on and is dropped if that link has been retired, so it can
//!   never land on a later connection;
//! * a [`LiveJob`] is the one live widget a screen can show. Its `alive` flag
//!   is cleared before its task is aborted, and every queued frame checks it;
//! * the [`Fleet`] is the single owner of "which devices exist" and "which one
//!   a mac-less request means".

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};
use tokio::sync::Mutex;
use tokio::task::JoinHandle;

use crate::command_queue::CommandQueue;
use crate::daemon::{DeviceTransport, EXCLUSIVE_TIMEOUT, ITEM_TIMEOUT};

/// One connection to a panel: its transport and its one serialization point.
pub struct Link {
    pub transport: Arc<DeviceTransport>,
    pub queue: CommandQueue,
    retired: AtomicBool,
}

impl Link {
    fn new(transport: Arc<DeviceTransport>) -> Arc<Self> {
        Arc::new(Self {
            transport,
            queue: CommandQueue::new(Some(EXCLUSIVE_TIMEOUT), Some(ITEM_TIMEOUT)),
            retired: AtomicBool::new(false),
        })
    }

    /// True once this connection has been replaced or dropped. Queued work
    /// that still holds this `Arc` must check it before touching the
    /// transport: the panel behind the id may now be a different connection.
    #[must_use]
    pub fn is_retired(&self) -> bool {
        self.retired.load(Ordering::SeqCst)
    }

    fn retire(&self) {
        self.retired.store(true, Ordering::SeqCst);
        // Pending items resolve to "did not execute" for their submitters.
        self.queue.stop();
    }

    /// Run one device op on this link's queue. `None` means it did not run
    /// (queue stopped, item timed out, or the link was retired first).
    pub async fn run<F, T>(&self, token: Option<String>, fut: F) -> Option<T>
    where
        F: std::future::Future<Output = T> + Send + 'static,
        T: Send + 'static,
    {
        if self.is_retired() {
            return None;
        }
        self.queue.run(token, fut).await
    }
}

/// The one live widget a screen can show.
pub struct LiveJob {
    pub kind: String,
    pub params: Value,
    handle: JoinHandle<()>,
    /// Cleared BEFORE the task is aborted. A frame the job already queued
    /// checks this and drops itself, so "stop" is a fence, not a request.
    alive: Arc<AtomicBool>,
    /// Last published health, the resync half of `live_job_state` (which
    /// fires only on transitions, so a late subscriber needs this).
    pub health: Option<Value>,
}

impl LiveJob {
    fn stop(self) {
        self.alive.store(false, Ordering::SeqCst);
        self.handle.abort();
    }
}

/// What the panel is showing, as last reported by whoever changed it.
#[derive(serde::Serialize, Clone, Debug)]
pub struct Activity {
    pub name: String,
    pub kind: String,
    pub preview: Option<String>,
    pub at: u64,
    pub state: String,
}

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

pub struct Device {
    /// The id as the client gave it (a `CoreBluetooth` UUID on macOS, a MAC
    /// elsewhere, `LAN:<ip>` for Wi-Fi). Kept verbatim for replies; the fleet
    /// indexes it case-insensitively.
    pub id: String,
    pub(super) link: Mutex<Option<Arc<Link>>>,
    live: Mutex<Option<LiveJob>>,
    activity: Mutex<Option<Activity>>,
}

impl Device {
    pub(super) fn new(id: &str) -> Arc<Self> {
        Arc::new(Self {
            id: id.to_string(),
            link: Mutex::new(None),
            live: Mutex::new(None),
            activity: Mutex::new(None),
        })
    }

    /// The current connection, if the panel is reachable right now.
    pub async fn link(&self) -> Option<Arc<Link>> {
        self.link.lock().await.clone()
    }

    pub async fn transport(&self) -> Option<Arc<DeviceTransport>> {
        self.link().await.map(|l| l.transport.clone())
    }

    pub async fn is_connected(&self) -> bool {
        self.link.lock().await.is_some()
    }

    /// Replace the connection. The old link is retired, so anything still
    /// queued on it is dropped rather than delivered to the new one.
    pub(super) async fn attach(&self, transport: Arc<DeviceTransport>) -> Arc<Link> {
        let link = Link::new(transport);
        let old = self.link.lock().await.replace(link.clone());
        if let Some(o) = old {
            o.retire();
        }
        link
    }

    pub(super) async fn detach(&self) -> Option<Arc<Link>> {
        let old = self.link.lock().await.take();
        if let Some(ref o) = old {
            o.retire();
        }
        old
    }

    // ── live job ──────────────────────────────────────────────────────

    /// Install `handle` as this panel's live widget, retiring any other.
    /// One screen shows one thing; two jobs would alternate frames.
    pub(crate) async fn install_live_job(
        &self,
        kind: &str,
        params: Value,
        alive: Arc<AtomicBool>,
        handle: JoinHandle<()>,
    ) {
        let old = self.live.lock().await.replace(LiveJob {
            kind: kind.to_string(),
            params,
            handle,
            alive,
            health: None,
        });
        if let Some(o) = old {
            o.stop();
        }
        self.set_activity_state(kind, "active").await;
    }

    /// Stop the live job of `kind` (or any job when `kind` is `None`).
    /// Returns whether one was running.
    pub(crate) async fn stop_live_job(&self, kind: Option<&str>) -> bool {
        let mut guard = self.live.lock().await;
        let matches = guard
            .as_ref()
            .is_some_and(|j| kind.is_none_or(|k| j.kind == k));
        if !matches {
            return false;
        }
        if let Some(job) = guard.take() {
            job.stop();
        }
        drop(guard);
        if let Some(a) = self.activity.lock().await.as_mut() {
            a.kind = "idle".to_string();
            a.at = now_secs();
        }
        true
    }

    pub async fn live_kind(&self) -> Option<String> {
        self.live.lock().await.as_ref().map(|j| j.kind.clone())
    }

    pub(crate) async fn record_health(&self, kind: &str, state: Value) {
        if let Some(j) = self.live.lock().await.as_mut() {
            if j.kind == kind {
                j.health = Some(state);
            }
        }
    }

    /// The `live_job_list` entry for this panel's job, if any.
    pub async fn live_job_entry(&self) -> Option<Value> {
        let (kind, health) = self
            .live
            .lock()
            .await
            .as_ref()
            .map(|j| (j.kind.clone(), j.health.clone()))?;
        let mut entry = json!({
            "mac": self.id,
            "kind": kind,
            "done": false,
            "cancelled": false,
        });
        match &health {
            Some(state) => {
                entry["state"] = state
                    .get("state")
                    .cloned()
                    .unwrap_or_else(|| json!("running"));
                if let Some(detail) = state.get("detail") {
                    entry["detail"] = detail.clone();
                }
            }
            // Started, but has not completed a cycle yet. Saying "starting"
            // is honest; claiming "running" would not be.
            None => entry["state"] = json!("starting"),
        }
        Some(entry)
    }

    // ── activity ──────────────────────────────────────────────────────

    async fn set_activity_state(&self, kind: &str, state: &str) {
        let mut guard = self.activity.lock().await;
        let a = guard.get_or_insert_with(|| Activity {
            name: "Divoom".to_string(),
            kind: kind.to_string(),
            preview: None,
            at: now_secs(),
            state: state.to_string(),
        });
        a.kind = kind.to_string();
        a.state = state.to_string();
        a.at = now_secs();
        drop(guard);
    }

    pub(crate) async fn set_activity(
        &self,
        kind: &str,
        name: Option<String>,
        preview: Option<String>,
    ) {
        let mut guard = self.activity.lock().await;
        let a = guard.get_or_insert_with(|| Activity {
            name: name.clone().unwrap_or_else(|| "Divoom".to_string()),
            kind: kind.to_string(),
            preview: None,
            at: now_secs(),
            state: "active".to_string(),
        });
        a.kind = kind.to_string();
        if let Some(n) = name {
            a.name = n;
        }
        if let Some(p) = preview {
            a.preview = Some(p);
        }
        a.at = now_secs();
        drop(guard);
    }

    pub async fn activity(&self) -> Option<Activity> {
        self.activity.lock().await.clone()
    }
}

mod fleet;
#[cfg(test)]
mod tests;

pub use fleet::Fleet;
