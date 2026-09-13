//! The fleet: single owner of "which devices exist" and which one the user
//! has SELECTED. Selection is a user-interface fact (the panel the bench and
//! the menubar show as active), not a routing default that connection order
//! sets: a mac-less request goes to the selected panel only while that
//! panel is linked, else to the single linked panel, else it is refused.

use std::collections::HashMap;
use std::sync::Arc;

use serde_json::Value;
use tokio::sync::Mutex;

use super::{Activity, Device, Link};
use crate::daemon::DeviceTransport;

fn key(id: &str) -> String {
    id.to_ascii_uppercase()
}

/// Every device this daemon knows, and the one the user selected. A request
/// names its panel, or the selected panel is linked, or there is exactly
/// one linked panel, or it is refused.
#[derive(Default)]
pub struct Fleet {
    devices: Mutex<HashMap<String, Arc<Device>>>,
    /// The user's active panel, by id as the client gave it. Set by
    /// `select_device` (bench click, menubar), by the first link when nothing
    /// is selected, cleared when that device is forgotten.
    selected: std::sync::Mutex<Option<String>>,
}

impl Fleet {
    /// The selected panel's id, linked or not.
    #[must_use]
    pub fn selected_id(&self) -> Option<String> {
        self.selected
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
    }

    #[must_use]
    pub fn is_selected(&self, id: &str) -> bool {
        self.selected_id().is_some_and(|s| key(&s) == key(id))
    }

    /// Make `id` the active panel. Returns whether that changed anything.
    pub fn select(&self, id: &str) -> bool {
        let mut sel = self
            .selected
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if sel.as_deref().is_some_and(|s| key(s) == key(id)) {
            return false;
        }
        *sel = Some(id.to_string());
        true
    }

    fn unselect_if(&self, id: &str) {
        let mut sel = self
            .selected
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if sel.as_deref().is_some_and(|s| key(s) == key(id)) {
            *sel = None;
        }
    }

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
        if let Some(sel) = linked.iter().find(|d| self.is_selected(&d.id)) {
            return (true, Some(sel.id.clone()));
        }
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
        // The first panel to link is the active one until the user says
        // otherwise; a later link never steals the selection.
        if self.selected_id().is_none() {
            self.select(id);
        }
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

    /// The panel a request means. An explicit `id` names it. Without one:
    /// the SELECTED panel while it is linked, else the single linked panel.
    /// With several linked and no linked selection, the caller has to say
    /// which -- "whichever connected last" is the guess that put a push on
    /// the wrong panel (2026-09-12).
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
        if let Some(pos) = linked.iter().position(|d| self.is_selected(&d.id)) {
            return Ok(linked.remove(pos));
        }
        match linked.len() {
            0 => Err("no device connected".to_string()),
            1 => Ok(linked.remove(0)),
            n => {
                let names = linked
                    .iter()
                    .map(|d| d.id.as_str())
                    .collect::<Vec<_>>()
                    .join(", ");
                Err(self.selected_id().map_or_else(
                    || format!("{n} panels connected and none active; pass 'mac' to say which ({names})"),
                    |sel| format!(
                        "the active panel '{sel}' is not connected and {n} others are; \
                         pass 'mac' to say which ({names})"
                    ),
                ))
            }
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
        if self.is_selected(id) {
            // The active slot passes to a linked panel (lowest id, so the
            // choice is the same every time) rather than sitting empty.
            self.unselect_if(id);
            let mut linked = self.linked().await;
            linked.sort_by_key(|d| key(&d.id));
            if let Some(next) = linked.first() {
                self.select(&next.id);
            }
        }
        removed.stop_live_job(None).await;
        removed.detach().await
    }

    /// Forget every device: jobs stopped, links retired, activity gone.
    pub async fn drain(&self) -> Vec<Arc<Link>> {
        *self
            .selected
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = None;
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
