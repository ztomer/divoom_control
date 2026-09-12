//! The fleet: single owner of "which devices exist". No "current" device.

use std::collections::HashMap;
use std::sync::Arc;

use serde_json::Value;
use tokio::sync::Mutex;

use super::{Activity, Device, Link};
use crate::daemon::DeviceTransport;

fn key(id: &str) -> String {
    id.to_ascii_uppercase()
}

/// Every device this daemon knows. There is no "current" device: a request
/// names its panel, or there is exactly one linked panel, or it is refused.
#[derive(Default)]
pub struct Fleet {
    devices: Mutex<HashMap<String, Arc<Device>>>,
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

    /// `(connected, id)` without awaiting, for callers that cannot (the
    /// socket server's initial status is synchronous). `id` is the single
    /// linked panel's, absent when none or several are linked. A contended
    /// lock reads as disconnected for this snapshot only.
    #[must_use]
    pub fn status_now(&self) -> (bool, Option<String>) {
        let Ok(devices) = self.devices.try_lock() else {
            return (false, None);
        };
        let linked: Vec<&Arc<Device>> = devices
            .values()
            .filter(|d| d.link.try_lock().is_ok_and(|l| l.is_some()))
            .collect();
        match linked.as_slice() {
            [] => (false, None),
            [one] => (true, Some(one.id.clone())),
            _ => (true, None),
        }
    }

    /// Take ownership of a freshly connected transport under `id`: the
    /// device keeps its identity (and live job); the old link is retired.
    pub async fn adopt(&self, id: &str, transport: Arc<DeviceTransport>) -> Arc<Device> {
        let dev = self.get_or_create(id).await;
        dev.attach(transport).await;
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

    /// The panel a request means. An explicit `id` names it. Without one
    /// there is exactly one honest answer: the single linked panel. With
    /// several linked, the caller has to say which -- "whichever connected
    /// last" is the guess that put a push on the wrong panel (2026-09-12).
    ///
    /// # Errors
    ///
    /// The three things a caller can act on: that panel is not connected,
    /// nothing is connected, or several are and `mac` is required.
    pub async fn resolve_target(&self, id: Option<&str>) -> Result<Arc<Device>, String> {
        if let Some(i) = id {
            return self
                .connected(i)
                .await
                .ok_or_else(|| format!("device '{i}' not connected"));
        }
        let mut linked = self.linked().await;
        match linked.len() {
            0 => Err("no device connected".to_string()),
            1 => Ok(linked.remove(0)),
            n => Err(format!(
                "{n} panels connected; pass 'mac' to say which ({})",
                linked
                    .iter()
                    .map(|d| d.id.as_str())
                    .collect::<Vec<_>>()
                    .join(", ")
            )),
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
        d.detach().await
    }

    /// Forget one device entirely: its job stopped, its link retired (and
    /// returned so the caller can hang up), its activity gone.
    pub async fn remove(&self, id: &str) -> Option<Arc<Link>> {
        let removed = self.devices.lock().await.remove(&key(id))?;
        removed.stop_live_job(None).await;
        removed.detach().await
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
