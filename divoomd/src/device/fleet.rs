//! The fleet: single owner of "which devices exist" and "which one is current".

use std::collections::HashMap;
use std::sync::Arc;

use serde_json::Value;
use tokio::sync::Mutex;

use super::{Activity, Device, Link};
use crate::daemon::DeviceTransport;

fn key(id: &str) -> String {
    id.to_ascii_uppercase()
}

/// Every device this daemon knows, plus which one a mac-less request means.
#[derive(Default)]
pub struct Fleet {
    devices: Mutex<HashMap<String, Arc<Device>>>,
    /// Canonical key of the "current" device -- the one a request with no
    /// `mac` addresses. The most recently adopted device becomes current.
    current: Mutex<Option<String>>,
}

impl Fleet {
    /// The device for `id`, created (unconnected) if the fleet has never
    /// heard of it. Activity and live jobs can exist for a panel the daemon
    /// is not currently linked to.
    pub async fn get_or_create(&self, id: &str) -> Arc<Device> {
        self.devices
            .lock()
            .await
            .entry(key(id))
            .or_insert_with(|| Device::new(id))
            .clone()
    }

    /// Declare `id` before any connection (the `--mac` the daemon was
    /// started for). Synchronous because it runs inside `Daemon::new`,
    /// before there is a runtime to await on; nothing else holds the locks
    /// yet.
    ///
    /// # Panics
    ///
    /// If called while another task holds the fleet's locks -- it is meant
    /// for construction only.
    pub fn preset(&self, id: &str) {
        let mut devices = self
            .devices
            .try_lock()
            .expect("fleet preset runs before any task");
        devices.entry(key(id)).or_insert_with(|| Device::new(id));
        drop(devices);
        *self
            .current
            .try_lock()
            .expect("fleet preset runs before any task") = Some(key(id));
    }

    /// `(connected, current id)` without awaiting, for callers that cannot
    /// (the socket server's initial status is synchronous). A contended lock
    /// reads as disconnected for this snapshot only.
    #[must_use]
    pub fn status_now(&self) -> (bool, Option<String>) {
        let Ok(cur) = self.current.try_lock() else {
            return (false, None);
        };
        let Some(k) = cur.clone() else {
            return (false, None);
        };
        let Ok(devices) = self.devices.try_lock() else {
            return (false, None);
        };
        let Some(d) = devices.get(&k) else {
            return (false, None);
        };
        let connected = d.link.try_lock().is_ok_and(|l| l.is_some());
        (connected, Some(d.id.clone()))
    }

    /// Take ownership of a freshly connected transport under `id`: the
    /// device keeps its identity (and live job), the old link is retired,
    /// and the device becomes current.
    pub async fn adopt(&self, id: &str, transport: Arc<DeviceTransport>) -> Arc<Device> {
        let dev = self.get_or_create(id).await;
        dev.attach(transport).await;
        *self.current.lock().await = Some(key(id));
        dev
    }

    pub async fn get(&self, id: &str) -> Option<Arc<Device>> {
        self.devices.lock().await.get(&key(id)).cloned()
    }

    /// The device for `id` only if it is connected right now.
    pub async fn connected(&self, id: &str) -> Option<Arc<Device>> {
        let d = self.get(id).await?;
        if d.is_connected().await {
            Some(d)
        } else {
            None
        }
    }

    pub async fn current(&self) -> Option<Arc<Device>> {
        let k = self.current.lock().await.clone()?;
        self.devices.lock().await.get(&k).cloned()
    }

    /// The current device's id as the client knows it.
    pub async fn current_id(&self) -> Option<String> {
        self.current().await.map(|d| d.id.clone())
    }

    /// An explicit id, else the current device.
    pub async fn resolve(&self, id: Option<&str>) -> Option<Arc<Device>> {
        match id {
            Some(i) => self.get(i).await,
            None => self.current().await,
        }
    }

    pub async fn all(&self) -> Vec<Arc<Device>> {
        self.devices.lock().await.values().cloned().collect()
    }

    /// Every connected device.
    pub async fn linked(&self) -> Vec<Arc<Device>> {
        let mut out = Vec::new();
        for d in self.all().await {
            if d.is_connected().await {
                out.push(d);
            }
        }
        out
    }

    /// Ids of every connected device, as their clients know them.
    pub async fn ids(&self) -> Vec<String> {
        self.linked().await.iter().map(|d| d.id.clone()).collect()
    }

    /// Drop the connection to `id`; the device, its job and its activity
    /// stay (the job waits for the panel to come back).
    pub async fn detach(&self, id: &str) -> Option<Arc<Link>> {
        let d = self.get(id).await?;
        let link = d.detach().await;
        let mut cur = self.current.lock().await;
        if cur.as_deref() == Some(key(id).as_str()) {
            *cur = None;
        }
        link
    }

    /// Forget one device entirely: its job stopped, its link retired (and
    /// returned so the caller can hang up), its activity gone. If it was
    /// current, the fleet has no current device afterwards.
    pub async fn remove(&self, id: &str) -> Option<Arc<Link>> {
        let removed = self.devices.lock().await.remove(&key(id))?;
        removed.stop_live_job(None).await;
        let link = removed.detach().await;
        let mut cur = self.current.lock().await;
        if cur.as_deref() == Some(key(id).as_str()) {
            *cur = None;
        }
        link
    }

    /// Forget every device: jobs stopped, links retired, activity gone.
    pub async fn drain(&self) -> Vec<Arc<Link>> {
        let drained: Vec<Arc<Device>> = self.devices.lock().await.drain().map(|(_, d)| d).collect();
        let mut links = Vec::new();
        for d in &drained {
            d.stop_live_job(None).await;
            if let Some(l) = d.detach().await {
                links.push(l);
            }
        }
        *self.current.lock().await = None;
        links
    }

    /// `live_job_list`: every running job, or only `mac`'s.
    pub async fn live_jobs(&self, mac: Option<&str>) -> Vec<Value> {
        let devices = match mac {
            Some(m) => self.get(m).await.into_iter().collect(),
            None => self.all().await,
        };
        let mut out = Vec::new();
        for d in devices {
            if let Some(e) = d.live_job_entry().await {
                out.push(e);
            }
        }
        out
    }

    /// `get_device_activity`: every panel's last-known activity, keyed by id.
    pub async fn activity_snapshot(&self) -> HashMap<String, Activity> {
        let mut out = HashMap::new();
        for d in self.all().await {
            if let Some(a) = d.activity().await {
                out.insert(d.id.clone(), a);
            }
        }
        out
    }
}
