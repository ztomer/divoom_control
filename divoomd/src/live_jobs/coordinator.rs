//! Live-widget job coordination, as a facade over the fleet.
//!
//! The state lives on each [`crate::device::Device`] (its one live job and
//! its activity record); this type only spawns the runner for a kind and
//! forwards to the device. It used to own four maps keyed by `(mac, kind)`
//! next to the daemon's own device maps, which is how a stopped job's frame
//! could still land and how two kinds could alternate on one screen.

use crate::daemon::Daemon;
use crate::device::Fleet;
use serde_json::{json, Value};
use std::sync::atomic::AtomicBool;
use std::sync::Arc;

pub struct LiveJobCoordinator {
    fleet: Arc<Fleet>,
}

impl LiveJobCoordinator {
    #[must_use]
    pub const fn new(fleet: Arc<Fleet>) -> Self {
        Self { fleet }
    }

    /// Record a job's latest health, so `list()` can answer a late subscriber.
    pub async fn record_health(&self, mac: &str, kind: &str, state: Value) {
        if let Some(d) = self.fleet.get(mac).await {
            d.record_health(kind, state).await;
        }
    }

    /// Start `kind` on `mac`, retiring whatever live job the panel had. A
    /// job may be started for a panel that is not linked right now; it
    /// reports `waiting_for_device` until the link comes back.
    ///
    /// # Errors
    ///
    /// When the live-job kind is unknown, and when a job needs a platform
    /// facility that is absent -- the music job needs macOS `MediaRemote` and
    /// says so rather than starting and rendering nothing.
    pub async fn start(
        &self,
        daemon: Arc<Daemon>,
        mac: String,
        kind: String,
        params: Value,
    ) -> Result<(), String> {
        let alive = Arc::new(AtomicBool::new(true));
        let daemon_weak = Arc::downgrade(&daemon);
        let mac_clone = mac.clone();
        let params_clone = params.clone();
        let alive_clone = alive.clone();

        let handle = match kind.as_str() {
            "sysmon" => tokio::spawn(super::run_sysmon(
                daemon_weak,
                mac_clone,
                params_clone,
                alive_clone,
            )),
            "stocks" => tokio::spawn(super::run_stocks(
                daemon_weak,
                mac_clone,
                params_clone,
                alive_clone,
            )),
            "weather" => tokio::spawn(super::run_weather(
                daemon_weak,
                mac_clone,
                params_clone,
                alive_clone,
            )),
            #[cfg(target_os = "macos")]
            "music" => tokio::spawn(super::run_music(
                daemon_weak,
                mac_clone,
                params_clone,
                alive_clone,
            )),
            // Known, but unavailable here — saying "unknown" would be a lie,
            // and the caller could not tell a typo from a platform limit.
            #[cfg(not(target_os = "macos"))]
            "music" => {
                return Err("the music live job needs macOS MediaRemote for \
                            now-playing and album art"
                    .to_string())
            }
            _ => return Err(format!("unknown live job kind: {kind}")),
        };

        let dev = self.fleet.get_or_create(&mac).await;
        let dev_name = params
            .get("device_name")
            .and_then(|v| v.as_str())
            .map(str::to_string);
        dev.install_live_job(&kind, params, alive, handle).await;
        if let Some(n) = dev_name {
            dev.set_activity(&kind, Some(n), None).await;
        }
        Ok(())
    }

    pub async fn stop(&self, _daemon: &Daemon, mac: &str, kind: &str) -> bool {
        match self.fleet.get(mac).await {
            Some(d) => d.stop_live_job(Some(kind)).await,
            None => false,
        }
    }

    pub async fn stop_all(&self, _daemon: &Daemon) {
        for d in self.fleet.all().await {
            d.stop_live_job(None).await;
        }
    }

    pub async fn stop_all_for_device(&self, _daemon: &Daemon, mac: &str) -> usize {
        match self.fleet.get(mac).await {
            Some(d) => usize::from(d.stop_live_job(None).await),
            None => 0,
        }
    }

    pub async fn list(&self, mac: Option<&str>) -> Vec<Value> {
        self.fleet.live_jobs(mac).await
    }

    pub async fn get_device_activity(&self) -> Value {
        json!({
            "success": true,
            "activity": self.fleet.activity_snapshot().await,
        })
    }

    pub async fn set_device_activity(
        &self,
        mac: String,
        kind: String,
        name: Option<String>,
        preview: Option<String>,
    ) {
        let dev = self.fleet.get_or_create(&mac).await;
        dev.set_activity(&kind, name, preview).await;
    }
}
