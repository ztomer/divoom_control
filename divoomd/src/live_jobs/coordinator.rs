//! Live-widget job coordination: task handles + per-device activity map.
//! Pulled out of mod.rs to keep both files under the 500-LOC ground rule.

use crate::daemon::Daemon;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};
use tokio::sync::Mutex;
use tokio::task::JoinHandle;

/// Shared map of running job handles, keyed by (mac, job kind). Factor of the
/// struct field type to keep clippy::type_complexity quiet on the field.
type JobTasks = Arc<Mutex<HashMap<(String, String), JoinHandle<()>>>>;

#[derive(serde::Serialize, Clone)]
struct ActivityEntry {
    name: String,
    kind: String,
    preview: Option<String>,
    at: u64,
    state: String,
}

pub struct LiveJobCoordinator {
    tasks: JobTasks,
    activity: Arc<Mutex<HashMap<String, ActivityEntry>>>,
    params: Arc<Mutex<HashMap<(String, String), Value>>>,
    /// Last published health per (mac, kind) — the RESYNC path for
    /// `live_job_state`.
    ///
    /// R67: `JobHealth` deliberately emits only on TRANSITIONS, so a UI that
    /// subscribes after a job is already running sees nothing at all and cannot
    /// tell "healthy" from "never started". That is the same hole C6 left in the
    /// hot channel — the push was added and the pull was not kept — so
    /// `list()` reports the current state alongside each job.
    health: Arc<Mutex<HashMap<(String, String), Value>>>,
}

impl Default for LiveJobCoordinator {
    fn default() -> Self {
        Self::new()
    }
}

impl LiveJobCoordinator {
    pub fn new() -> Self {
        Self {
            tasks: Arc::new(Mutex::new(HashMap::new())),
            activity: Arc::new(Mutex::new(HashMap::new())),
            params: Arc::new(Mutex::new(HashMap::new())),
            health: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    /// Record a job's latest health, so `list()` can answer a late subscriber.
    pub async fn record_health(&self, mac: &str, kind: &str, state: Value) {
        self.health
            .lock()
            .await
            .insert((mac.to_string(), kind.to_string()), state);
    }

    /// Forget a stopped job's health — a state left behind after the job is
    /// gone is worse than none, because it reads as current.
    pub async fn forget_health(&self, mac: &str, kind: &str) {
        self.health
            .lock()
            .await
            .remove(&(mac.to_string(), kind.to_string()));
    }

    fn now_secs() -> u64 {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs()
    }

    pub async fn start(
        &self,
        daemon: Arc<Daemon>,
        mac: String,
        kind: String,
        params: Value,
    ) -> Result<(), String> {
        self.stop(&daemon, &mac, &kind).await;

        let daemon_weak = Arc::downgrade(&daemon);
        let mac_clone = mac.clone();
        let params_clone = params.clone();

        let handle = match kind.as_str() {
            "sysmon" => tokio::spawn(super::run_sysmon(daemon_weak, mac_clone, params_clone)),
            "stocks" => tokio::spawn(super::run_stocks(daemon_weak, mac_clone, params_clone)),
            "weather" => tokio::spawn(super::run_weather(daemon_weak, mac_clone, params_clone)),
            "music" => tokio::spawn(super::run_music(daemon_weak, mac_clone, params_clone)),
            _ => return Err(format!("unknown live job kind: {}", kind)),
        };

        self.tasks
            .lock()
            .await
            .insert((mac.clone(), kind.clone()), handle);
        self.params
            .lock()
            .await
            .insert((mac.clone(), kind.clone()), params.clone());

        let dev_name = params
            .get("device_name")
            .and_then(|v| v.as_str())
            .unwrap_or("Divoom")
            .to_string();
        self.activity.lock().await.insert(
            mac,
            ActivityEntry {
                name: dev_name,
                kind,
                preview: None,
                at: Self::now_secs(),
                state: "active".to_string(),
            },
        );

        Ok(())
    }

    pub async fn stop(&self, _daemon: &Daemon, mac: &str, kind: &str) -> bool {
        self.forget_health(mac, kind).await;
        let key = (mac.to_string(), kind.to_string());
        let handle = self.tasks.lock().await.remove(&key);
        if let Some(h) = handle {
            h.abort();
            self.params.lock().await.remove(&key);

            let has_other = self.tasks.lock().await.keys().any(|(m, _)| m == mac);
            if !has_other {
                if let Some(entry) = self.activity.lock().await.get_mut(mac) {
                    entry.kind = "idle".to_string();
                    entry.at = Self::now_secs();
                }
            }
            true
        } else {
            false
        }
    }

    pub async fn stop_all(&self, _daemon: &Daemon) {
        let mut tasks = self.tasks.lock().await;
        for (_, handle) in tasks.drain() {
            handle.abort();
        }
        self.params.lock().await.clear();
        self.activity.lock().await.clear();
    }

    pub async fn stop_all_for_device(&self, daemon: &Daemon, mac: &str) -> usize {
        let keys: Vec<(String, String)> = self
            .tasks
            .lock()
            .await
            .keys()
            .filter(|(m, _)| m == mac)
            .cloned()
            .collect();
        let count = keys.len();
        for (m, k) in keys {
            self.stop(daemon, &m, &k).await;
        }
        count
    }

    pub async fn list(&self, mac: Option<&str>) -> Vec<Value> {
        let tasks = self.tasks.lock().await;
        let health = self.health.lock().await;
        let mut list = Vec::new();
        for (m, k) in tasks.keys() {
            if mac.is_none() || mac == Some(m) {
                let mut entry = json!({
                    "mac": m,
                    "kind": k,
                    "done": false,
                    "cancelled": false,
                });
                // The resync half of the event stream: `live_job_state` fires
                // only on transitions, so a client that subscribed late learns
                // the current state from here instead of guessing.
                match health.get(&(m.clone(), k.clone())) {
                    Some(state) => {
                        entry["state"] = state.get("state").cloned().unwrap_or(json!("running"));
                        if let Some(detail) = state.get("detail") {
                            entry["detail"] = detail.clone();
                        }
                    }
                    // Started, but has not completed a cycle yet. Saying
                    // "starting" is honest; claiming "running" would not be.
                    None => entry["state"] = json!("starting"),
                }
                list.push(entry);
            }
        }
        list
    }

    pub async fn get_device_activity(&self) -> Value {
        let activity = self.activity.lock().await;
        let snap: HashMap<String, ActivityEntry> = activity.clone();
        json!({
            "success": true,
            "activity": snap,
        })
    }

    pub async fn set_device_activity(
        &self,
        mac: String,
        kind: String,
        name: Option<String>,
        preview: Option<String>,
    ) {
        let mut act = self.activity.lock().await;
        let entry = act.entry(mac).or_insert(ActivityEntry {
            name: name.clone().unwrap_or_else(|| "Divoom".to_string()),
            kind: kind.clone(),
            preview: None,
            at: Self::now_secs(),
            state: "active".to_string(),
        });
        entry.kind = kind;
        if let Some(n) = name {
            entry.name = n;
        }
        if let Some(p) = preview {
            entry.preview = Some(p);
        }
        entry.at = Self::now_secs();
    }
}
