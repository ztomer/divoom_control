//! Live-widget job coordination, as a facade over the fleet.
//!
//! The state lives on each [`crate::device::Device`] (its one live job and
//! its activity record); this type only spawns the runner for a kind and
//! forwards to the device. It used to own four maps keyed by `(mac, kind)`
//! next to the daemon's own device maps, which is how a stopped job's frame
//! could still land and how two kinds could alternate on one screen.

use crate::daemon::Daemon;
use crate::device::Fleet;
use crate::protocol::{CodedError, ErrorCode};
use serde_json::{json, Value};
use std::sync::atomic::AtomicBool;
use std::sync::Arc;

pub struct LiveJobCoordinator {
    fleet: Arc<Fleet>,
    /// Test seam: parks `start` between the panel lookup and the install, so
    /// a test can run a `disconnect` in exactly that window (P5.9).
    #[cfg(test)]
    pub(crate) pause_before_install: crate::test_pause::PausePoint,
}

impl LiveJobCoordinator {
    #[must_use]
    pub const fn new(fleet: Arc<Fleet>) -> Self {
        Self {
            fleet,
            #[cfg(test)]
            pause_before_install: crate::test_pause::PausePoint::new(),
        }
    }

    /// Record a job's latest health, so `list()` can answer a late subscriber.
    pub async fn record_health(&self, mac: &str, kind: &str, state: Value) {
        if let Some(d) = self.fleet.get(mac).await {
            d.record_health(kind, state).await;
        }
    }

    /// Start `kind` on `mac`, retiring whatever live job the panel had. A
    /// job may be started for a panel that is not linked right now -- one
    /// that linked and dropped; it reports `waiting_for_device` until the
    /// link comes back.
    ///
    /// # Errors
    ///
    /// `unknown_device` when no link ever made `mac` a fleet entry, or when a
    /// `disconnect` forgot it while this call was starting the job (a job
    /// there would paint nothing and report success -- P5.8; `MatrixWall`
    /// is one such id, since a job runs on one panel's link); `bad_request`
    /// when the kind is unknown; `unsupported` when a job needs a platform
    /// facility that is absent -- the music job needs macOS `MediaRemote` and
    /// says so rather than starting and rendering nothing.
    pub async fn start(
        &self,
        daemon: Arc<Daemon>,
        mac: String,
        kind: String,
        params: Value,
    ) -> Result<(), CodedError> {
        // Looked up before anything is spawned: a refusal leaves no task.
        let dev = self.fleet.known(&mac).await?;
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
                return Err(CodedError::new(
                    ErrorCode::Unsupported,
                    "the music live job needs macOS MediaRemote for \
                     now-playing and album art",
                ))
            }
            _ => {
                return Err(CodedError::new(
                    ErrorCode::BadRequest,
                    format!("unknown live job kind: {kind}"),
                ))
            }
        };

        let dev_name = params
            .get("device_name")
            .and_then(|v| v.as_str())
            .map(str::to_string);
        #[cfg(test)]
        self.pause_before_install.wait_if_armed().await;
        // A `disconnect` may have forgotten the panel since the lookup; the
        // device refuses the job then (and stops it), so nothing runs on a
        // panel the fleet no longer holds (P5.9).
        dev.install_live_job(&kind, params, alive, handle)
            .await
            .map_err(|_| Fleet::unknown(&mac))?;
        if let Some(n) = dev_name {
            dev.set_activity(&kind, Some(n), None)
                .await
                .map_err(|_| Fleet::unknown(&mac))?;
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

    /// Record what `mac` is showing, for the menubar's tile.
    ///
    /// # Errors
    ///
    /// `unknown_device` when no link ever made `mac` a fleet entry, or a
    /// `disconnect` forgot it between the lookup and the record: a record
    /// for it would be a menubar tile for a panel that does not exist.
    pub async fn set_device_activity(
        &self,
        mac: &str,
        kind: &str,
        name: Option<String>,
        preview: Option<String>,
    ) -> Result<(), CodedError> {
        self.fleet
            .known(mac)
            .await?
            .set_activity(kind, name, preview)
            .await
            .map_err(|_| Fleet::unknown(mac))
    }
}

#[cfg(test)]
mod race_tests;

#[cfg(test)]
mod tests {
    /// Every kind the tools offer has a `start` arm, so an advertised kind
    /// can never answer "unknown live job kind".
    #[test]
    fn every_advertised_kind_is_started_by_name() {
        let src = include_str!("coordinator.rs");
        let body = &src[..src.find("#[cfg(test)]\nmod tests").expect("tests marker")];
        for kind in super::super::JOB_KINDS {
            assert!(
                body.contains(&format!("\"{kind}\" =>")),
                "{kind} is advertised but has no start arm"
            );
        }
    }
}
