//! The scheduled Monthly Best push.
//!
//! WHAT IT PUSHES: the cloud's "Recommend" gallery (classify 18) — what the
//! owner calls "monthly best" — to the devices the APP'S SETTINGS register,
//! over BLE.
//!
//! # The devices come from the settings, not from a second list
//!
//! The loop used to keep its own list (`hotchannel.json` → `targets`) and its
//! own per-device gallery (`device_galleries`). That list was EMPTY: the loop
//! was enabled, it was scheduled, and it fetched nothing and pushed nothing
//! — for 36 days, with nothing anywhere saying so. Meanwhile the app's
//! settings already knew the devices: `config.ini`'s `[gallery]` table is
//! keyed by device address and holds the gallery that device wants.
//!
//! So the fact lives in ONE place. The loop reads the settings (see
//! [`crate::settings_devices`]); `hotchannel.json` keeps only what is
//! genuinely the LOOP's own — whether it runs and how often. A stale
//! `hotchannel.json` that still carries the old keys is REPORTED and
//! IGNORED: it must never override the settings.
//!
//! # The cadence is a day, because the content is
//!
//! The source content is refreshed almost daily — the owner says so, and the
//! dates on the files themselves bear it out. The CATEGORY is called "monthly
//! best" because that is the CLOUD's name for it, not because the content
//! turns over monthly. A weekly push therefore leaves a device up to a week
//! behind, so the interval is 86400 seconds.
//!
//! # A failure is loud
//!
//! A failed run is not a line on the daemon's stdout: it POSTs to the estate's
//! own push endpoint, so it reaches the owner's phone (see
//! [`crate::owner_alert`]). A device that cannot be resolved, a category that
//! comes back empty, a connection that fails — each is a FAILURE of the run,
//! never a quiet skip.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::sync::Arc;
use std::time::Duration;
use tokio::time::sleep;

use crate::daemon::Daemon;

/// The loop's own settings: whether it runs, and how often.
///
/// The devices it pushes to are NOT here — they are the app's settings
/// (see [`crate::settings_devices`]). One home for the fact.
#[derive(Serialize, Deserialize, Clone, Debug, Default, PartialEq, Eq)]
pub struct HotchannelConfig {
    /// Whether the scheduled loop runs at all.
    #[serde(default)]
    pub enabled: bool,
    /// Seconds between runs.
    #[serde(default = "default_interval")]
    pub interval: u64,
}

/// The default seconds between runs: a day.
///
/// WHY DAILY: the "monthly best" content is refreshed almost daily, so a
/// weekly push leaves the device up to a week behind. The CATEGORY is called
/// "monthly best" because that is the cloud's name for it, not because the
/// content turns over monthly.
const fn default_interval() -> u64 {
    86_400
}

/// The keys `hotchannel.json` used to carry that no longer mean anything.
///
/// The devices used to be listed there, in a list nobody filled. The keys are
/// still READ (a file written by an older build must not break the daemon),
/// but they are IGNORED and REPORTED: a stale list must never override the
/// app's settings.
pub const LEGACY_KEYS: &[&str] = &["targets", "device_galleries", "classify"];

/// What the loader found in `hotchannel.json`.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct LoadedHotchannel {
    /// The loop's own settings.
    pub config: HotchannelConfig,
    /// The legacy keys the file still carries — reported, never used.
    pub legacy_keys: Vec<String>,
}

/// Read the loop's own settings, and report the file's stale keys.
///
/// A missing or unreadable file is "the loop is off" — the same answer the
/// default config gives — never a panic and never a silent "on".
#[must_use]
pub fn load_hotchannel_config() -> LoadedHotchannel {
    let Some(mut path) = crate::cloud::config_dir() else {
        return LoadedHotchannel::default();
    };
    path.push("hotchannel.json");
    let Ok(content) = std::fs::read_to_string(&path) else {
        return LoadedHotchannel::default();
    };
    let Ok(raw) = serde_json::from_str::<Value>(&content) else {
        return LoadedHotchannel::default();
    };

    let legacy_keys = raw
        .as_object()
        .map(|object| {
            LEGACY_KEYS
                .iter()
                .filter(|key| object.contains_key(**key))
                .map(|key| (*key).to_string())
                .collect()
        })
        .unwrap_or_default();

    let mut config: HotchannelConfig = serde_json::from_value(raw).unwrap_or_default();
    if config.interval == 0 {
        config.interval = default_interval();
    }
    config.interval = config.interval.clamp(60, 2_592_000); // 60s to 30 days

    LoadedHotchannel {
        config,
        legacy_keys,
    }
}

/// One device's outcome.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeviceOutcome {
    /// The device address the push went to.
    pub address: String,
    /// The gallery classify that was fetched for it.
    pub classify: i64,
    /// How many files the category offered.
    pub files: usize,
    /// How many of them the device SHOWED.
    pub pushed: usize,
    /// How many of them the device STORED — the art is in its own gallery.
    ///
    /// This is the number the run's failure turns on: the push's job is to
    /// leave the art on the device, so a device that stored NOTHING is a
    /// failed run even when it showed everything.
    pub stored: usize,
    /// What the device said it holds, when it answers the read-back.
    pub readback: Option<String>,
    /// Why the DEVICE failed: it could not be reached, or nothing could be
    /// stored on it. A device that failed is a failed run.
    pub error: Option<String>,
    /// The files that did not make it, when the device itself was reached.
    ///
    /// These are WARNINGS, not a failed run: a container format the decoder
    /// does not handle is a defect in the decoder, and a run that rings the
    /// owner's phone every day for it teaches them to ignore the channel.
    /// Each warning NAMES the file and says why it could not be shown — a
    /// run that quietly drops files says less than it does.
    pub warnings: Vec<String>,
}

impl DeviceOutcome {
    /// Whether the push to this device succeeded.
    #[must_use]
    pub const fn ok(&self) -> bool {
        self.error.is_none()
    }
}

/// One cycle's outcome.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CycleOutcome {
    /// What happened to each device.
    pub devices: Vec<DeviceOutcome>,
    /// Why the cycle failed, one line per reason. Empty means it worked.
    pub failures: Vec<String>,
}

impl CycleOutcome {
    /// Whether the cycle had no failures at all.
    #[must_use]
    pub const fn ok(&self) -> bool {
        self.failures.is_empty()
    }
}

/// Whether a cycle is due.
///
/// The daemon restarts often — the GUI owns it — and a restart must not
/// push: the CADENCE is the point. So a run that happened less than one
/// interval ago means the next one is not due yet, and the loop waits out
/// the remainder instead of pushing again.
#[must_use]
pub fn should_run_now(last_run_at: Option<u64>, now: u64, interval: u64) -> bool {
    last_run_at.is_none_or(|last| now.saturating_sub(last) >= interval)
}

/// The scheduled loop: wake up, push to every device the settings register,
/// report, sleep until the next run.
pub async fn monthly_best_loop_task(daemon: Arc<Daemon>) {
    // Wait a brief moment after startup before starting
    sleep(Duration::from_secs(5)).await;

    loop {
        let loaded = load_hotchannel_config();
        if !loaded.config.enabled {
            sleep(Duration::from_secs(30)).await;
            continue;
        }

        for key in &loaded.legacy_keys {
            println!(
                "divoomd: hotchannel.json still carries '{key}' — IGNORED. The hot \
                 channel's devices are the app's settings (config.ini [gallery]); \
                 a stale list must not override them."
            );
        }

        let interval_secs = loaded.config.interval;
        let now = crate::civil_time::unix_seconds();
        if !should_run_now(crate::owner_alert::last_run_at(), now, interval_secs) {
            let last = crate::owner_alert::last_run_at().unwrap_or(now);
            let since = now.saturating_sub(last);
            let wait = interval_secs.saturating_sub(since);
            println!(
                "divoomd: the last monthly best push was {since}s ago; the next one is in {wait}s."
            );
            sleep(Duration::from_secs(wait)).await;
            continue;
        }

        println!("divoomd: monthly best cycle started.");

        let outcome = run_cycle(&daemon).await;
        report_cycle(&outcome).await;

        println!("divoomd: sleeping for {interval_secs}s until the next monthly best cycle");
        sleep(Duration::from_secs(interval_secs)).await;
    }
}

/// The devices the loop pushes to, read from the app's settings, and the
/// failures the settings themselves carry.
///
/// Split out of [`run_cycle`] so the RESOLUTION — which devices, and what to
/// say about a settings entry the loop cannot read — can be pinned by a test
/// without a daemon, a radio or the cloud.
#[must_use]
pub fn resolve_targets() -> (Vec<crate::settings_devices::RegisteredDevice>, Vec<String>) {
    let settings = crate::settings_devices::registered_devices();
    let failures = settings
        .broken
        .iter()
        .map(|(key, value)| {
            format!(
                "the app's settings carry a gallery entry the loop cannot resolve: {key} = {value}"
            )
        })
        .collect();
    (settings.devices, failures)
}

/// The run's failures, one line per device that failed.
///
/// A device that failed is a FAILED RUN. It used to be printed and nothing
/// else: the line was in the log and the run's outcome said "ok" — the quiet
/// skip this whole round exists to end, found by the round's own observed run
/// (2026-10-21: "a9fccb71…: 3 of 10 file(s) did not reach the device" in the
/// log, and `last_outcome: ok` in the state file).
#[must_use]
pub fn device_failures(devices: &[DeviceOutcome]) -> Vec<String> {
    devices
        .iter()
        .filter_map(|d| d.error.as_ref().map(|e| format!("{}: {e}", d.address)))
        .collect()
}

/// Fold what happened to each device into the run's outcome.
///
/// The devices' failures BECOME the run's failures here, and nowhere else —
/// which is the whole point, and the thing the observed run found missing.
#[must_use]
pub fn fold_devices(devices: Vec<DeviceOutcome>, mut failures: Vec<String>) -> CycleOutcome {
    failures.extend(device_failures(&devices));
    CycleOutcome { devices, failures }
}

/// What each device holds, for the state file.
///
/// The state after a run must say WHICH happened: the files a device was
/// SHOWN, the files it STORED, and what the device said it holds. A state
/// that says only "ok" cannot answer the owner's question — did the art land?
#[must_use]
pub fn device_states(outcome: &CycleOutcome) -> Value {
    Value::Array(
        outcome
            .devices
            .iter()
            .map(|d| {
                json!({
                    "address": d.address,
                    "classify": d.classify,
                    "files": d.files,
                    "shown": d.pushed,
                    "stored": d.stored,
                    "readback": d.readback,
                    "error": d.error,
                    "warnings": d.warnings,
                })
            })
            .collect(),
    )
}

/// Run one cycle: every device the settings register, in order.
pub async fn run_cycle(daemon: &Daemon) -> CycleOutcome {
    let (devices, mut failures) = resolve_targets();
    let mut outcome = CycleOutcome::default();

    if devices.is_empty() {
        failures.push(
            "the app's settings register no devices (config.ini's [gallery] table is empty) — \
             the hot channel has nowhere to go"
                .to_string(),
        );
        outcome.failures = failures;
        return outcome;
    }

    println!(
        "divoomd: {} device(s) from the app's settings: {}",
        devices.len(),
        devices
            .iter()
            .map(|d| d.address.as_str())
            .collect::<Vec<_>>()
            .join(", ")
    );

    let mut outcomes = Vec::new();
    for device in &devices {
        let device_outcome = crate::monthly_best_push::push_to_device(daemon, device).await;
        if let Some(error) = &device_outcome.error {
            eprintln!("divoomd: {}: {error}", device.address);
        }
        for warning in &device_outcome.warnings {
            eprintln!("divoomd: {}: {warning}", device.address);
        }
        outcomes.push(device_outcome);
    }

    outcome = fold_devices(outcomes, failures);
    for failure in &outcome.failures {
        eprintln!("divoomd: {failure}");
    }
    outcome
}

/// Say what the cycle did, and — when it failed — get the failure to the
/// owner's phone.
///
/// A failure that only exists in a log is a failure nobody hears, so a failed
/// cycle POSTs to the estate's push endpoint. A cycle that succeeds after a
/// failed one posts a quiet recovery: the estate's own pattern, so the owner
/// learns the channel works again without a daily buzz.
pub async fn report_cycle(outcome: &CycleOutcome) {
    let previous = crate::owner_alert::last_outcome();
    let detail = outcome
        .failures
        .iter()
        .map(String::as_str)
        .collect::<Vec<_>>()
        .join("; ");
    let _ = crate::owner_alert::record_outcome_with(
        if outcome.ok() { "ok" } else { "failed" },
        &detail,
        &device_states(outcome),
    );

    if outcome.ok() {
        let pushed: usize = outcome.devices.iter().map(|d| d.pushed).sum();
        let stored: usize = outcome.devices.iter().map(|d| d.stored).sum();
        let files: usize = outcome.devices.iter().map(|d| d.files).sum();
        let warned: usize = outcome.devices.iter().map(|d| d.warnings.len()).sum();
        println!(
            "divoomd: monthly best cycle finished: {pushed} of {files} file(s) shown and \
             {stored} stored in {} device(s)' own gallery.",
            outcome.devices.len()
        );
        for device in &outcome.devices {
            match &device.readback {
                Some(what) => println!("divoomd: {} holds {what}", device.address),
                None => println!(
                    "divoomd: {}: the device did not answer the read-back query, so what it \
                     holds cannot be confirmed from this side",
                    device.address
                ),
            }
        }
        if warned > 0 {
            println!(
                "divoomd: {warned} file(s) could not be shown (the device was reached): \
                 the lines above name each file and the reason."
            );
        }
        if previous.as_deref() == Some("failed") {
            let body = format!(
                "The monthly best push works again: {} device(s), {pushed} file(s) shown, \
                 {stored} stored.",
                outcome.devices.len()
            );
            notify(
                "divoom: monthly best RECOVERED",
                &body,
                crate::owner_alert::PRIORITY_RECOVERY,
            )
            .await;
        }
        return;
    }

    let body = format!(
        "The monthly best push FAILED.\n{}",
        outcome.failures.join("\n")
    );
    println!(
        "divoomd: monthly best cycle FAILED: {}",
        outcome.failures.join("; ")
    );
    notify(
        "divoom: monthly best FAILED",
        &body,
        crate::owner_alert::PRIORITY_FAILURE,
    )
    .await;
}

/// Send one alert, and say so when the channel itself is broken.
///
/// A broken channel is a failure of the alarm, not of the art: it is printed
/// loudly, because the next thing the owner needs to know is that the phone is
/// not being rung.
async fn notify(title: &str, body: &str, priority: &str) {
    match crate::owner_alert::notify_owner(title, body, priority).await {
        Ok(()) => println!("divoomd: alert delivered: {title}"),
        Err(e) => eprintln!("divoomd: THE ALERT ITSELF FAILED: {e}"),
    }
}
