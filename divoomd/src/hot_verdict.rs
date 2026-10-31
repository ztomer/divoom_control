//! One lasting verdict per panel for its hot channel (U.5, P5.13 option A).
//!
//! The owner, 2026-10-26: "The hot channel update status is very unclear and
//! need to be rethought." Three paths updated a panel's hot art and kept three
//! records: the Update button's verdict lived 3 s on the button, then vanished;
//! its "Last checked" stamp was written only by a SUCCESSFUL button run, so a
//! failure left the old success showing; Sync Now's rows were never stored;
//! and the daily schedule's outcome lived in `hotchannel_state.json`, which no
//! screen read. The owner's last scheduled run failed on all four panels and
//! nothing said so. The owner picked option A, 2026-10-31: "A: verdict line
//! (Recommended)".
//!
//! So there is ONE record per panel, and every path writes it, failures
//! included: the button and Sync Now (`hot_update`, `by` naming which) and the
//! schedule (`monthly_best`). The newest run replaces the panel's verdict
//! whatever path ran it -- a failure replaces the earlier success. It lives in
//! `hotchannel_state.json` under `panels`, beside the schedule's own cadence
//! keys (`last_outcome`, `last_run_utc`), and every write is broadcast as a
//! `hot_status` event naming the panel, so the GUI's line changes when the
//! record does. The GUI only reads.
//!
//! ```text
//! "panels": { "<panel id>": {
//!     "at": 1793468518, "by": "schedule", "outcome": "failed",
//!     "error": "could not connect", "offered": 5, "fetched": 0, "delivered": 0 } }
//! ```
//!
//! `offered` is what the source offered (the hot manifest, or the gallery's
//! files), `fetched` what reached the daemon (downloaded, or shown), and
//! `delivered` what landed on the panel (files the panel asked for, or files
//! it stored). The words are the GUI's (`hot_verdict.js`).

use serde_json::{json, Map, Value};
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use crate::daemon::Daemon;
use crate::monthly_best::DeviceOutcome;

/// Which path ran the update.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RunBy {
    /// The Hot tab's Update Hot Channel button.
    Button,
    /// Schedule -> Auto-Sync -> Sync Now.
    SyncNow,
    /// The daily schedule.
    Schedule,
}

impl RunBy {
    /// The word stored and broadcast.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Button => "button",
            Self::SyncNow => "sync_now",
            Self::Schedule => "schedule",
        }
    }

    /// The path a `hot_update` request names; the button when it names none.
    /// The schedule is never a request's to claim.
    #[must_use]
    pub fn from_request(word: Option<&str>) -> Option<Self> {
        match word {
            None | Some("button") => Some(Self::Button),
            Some("sync_now") => Some(Self::SyncNow),
            Some(_) => None,
        }
    }
}

/// One run's verdict on one panel.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Verdict {
    /// When the run finished, in unix seconds.
    pub at: u64,
    /// Which path ran it.
    pub by: RunBy,
    /// Why it failed; `None` when it did not.
    pub error: Option<String>,
    /// What the source offered.
    pub offered: u64,
    /// What reached the daemon.
    pub fetched: u64,
    /// What landed on the panel.
    pub delivered: u64,
}

fn count(v: Option<&Value>) -> u64 {
    match v {
        Some(Value::Array(a)) => a.len() as u64,
        Some(v) => v.as_u64().unwrap_or(0),
        None => 0,
    }
}

impl Verdict {
    /// The verdict of a `hot_update` run (the button or Sync Now).
    #[must_use]
    pub fn from_hot_update(by: RunBy, at: u64, result: &Result<Value, String>) -> Self {
        match result {
            Ok(summary) => Self {
                at,
                by,
                error: None,
                offered: count(summary.get("manifest")),
                fetched: count(summary.get("downloaded")),
                delivered: count(summary.get("served")),
            },
            Err(e) => Self {
                at,
                by,
                error: Some(e.clone()),
                offered: 0,
                fetched: 0,
                delivered: 0,
            },
        }
    }

    /// The verdict of the schedule on one panel.
    #[must_use]
    pub fn from_schedule(at: u64, device: &DeviceOutcome) -> Self {
        Self {
            at,
            by: RunBy::Schedule,
            error: device.error.clone(),
            offered: device.files as u64,
            fetched: device.pushed as u64,
            delivered: device.stored as u64,
        }
    }

    /// The stored and broadcast form.
    #[must_use]
    pub fn to_json(&self) -> Value {
        json!({
            "at": self.at,
            "by": self.by.as_str(),
            "outcome": if self.error.is_some() { "failed" } else { "ok" },
            "error": self.error,
            "offered": self.offered,
            "fetched": self.fetched,
            "delivered": self.delivered,
        })
    }
}

/// Every writer of `hotchannel_state.json` takes this, so the schedule's
/// cadence keys and the panels' verdicts never overwrite each other.
static WRITE: Mutex<()> = Mutex::new(());

/// Where the state lives (the schedule's file).
#[must_use]
pub fn state_path() -> Option<PathBuf> {
    crate::owner_alert::state_path()
}

/// Read the state file as an object; missing or corrupt reads as empty.
#[must_use]
pub fn load(path: &Path) -> Map<String, Value> {
    std::fs::read_to_string(path)
        .ok()
        .and_then(|s| serde_json::from_str::<Value>(&s).ok())
        .and_then(|v| v.as_object().cloned())
        .unwrap_or_default()
}

/// Read-modify-write the state file under the one lock, atomically.
///
/// # Errors
///
/// When the file cannot be written.
pub fn update_at(path: &Path, change: impl FnOnce(&mut Map<String, Value>)) -> Result<(), String> {
    let _held = WRITE
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let mut state = load(path);
    change(&mut state);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let text = serde_json::to_string_pretty(&Value::Object(state)).map_err(|e| e.to_string())?;
    let tmp = path.with_extension("json.tmp");
    std::fs::write(&tmp, text + "\n").map_err(|e| e.to_string())?;
    std::fs::rename(&tmp, path).map_err(|e| e.to_string())
}

/// Replace `address`'s verdict in the file at `path`.
///
/// # Errors
///
/// When the file cannot be written.
pub fn record_at(path: &Path, address: &str, verdict: &Verdict) -> Result<(), String> {
    update_at(path, |state| {
        let panels = state
            .entry("panels")
            .or_insert_with(|| Value::Object(Map::new()));
        if !panels.is_object() {
            *panels = Value::Object(Map::new());
        }
        if let Some(panels) = panels.as_object_mut() {
            panels.retain(|k, _| !k.eq_ignore_ascii_case(address));
            panels.insert(address.to_string(), verdict.to_json());
        }
    })
}

/// The `hot_status` event for one panel's new verdict.
#[must_use]
pub fn event(address: &str, verdict: &Verdict) -> Value {
    json!({"type": "hot_status", "mac": address, "verdict": verdict.to_json()})
}

/// Record `address`'s verdict and tell every client.
///
/// A panel no real device ever reported keys nothing in the owner's state
/// (D.DV2): a test double's run is broadcast, never stored there.
pub fn record(daemon: &Daemon, address: &str, verdict: &Verdict) {
    if address.is_empty() {
        return;
    }
    if crate::reported_panels::Reported::load().admits(address) {
        match state_path() {
            Some(path) => {
                if let Err(e) = record_at(&path, address, verdict) {
                    eprintln!(
                        "divoomd: could not record the hot-channel verdict for {address}: {e}"
                    );
                }
            }
            None => eprintln!("divoomd: no config directory to record the hot-channel verdict in"),
        }
    }
    let _ = daemon.tx.send(event(address, verdict));
}

/// Fold the two records this one replaced into `panels`, once (U.5).
///
/// `hot_update_state.json` (the button's "Last checked" stamp, success only)
/// and the schedule's `devices` list each become the panel's verdict where it
/// is the newer of the two; then the old file is deleted and `devices`
/// dropped. A key no real device ever reported (the old file's `MatrixWall`)
/// is not carried over. Returns how many panels were carried over.
///
/// # Errors
///
/// When the state file cannot be written.
pub fn migrate_at(
    state: &Path,
    legacy: &Path,
    reported: &crate::reported_panels::Reported,
) -> Result<usize, String> {
    let old: Map<String, Value> = load(legacy);
    let has_devices = load(state).contains_key("devices");
    if old.is_empty() && !has_devices && !legacy.exists() {
        return Ok(0);
    }
    let mut carried = 0;
    update_at(state, |s| {
        let mut found: Vec<(String, Value)> = Vec::new();
        for (addr, e) in &old {
            found.push((
                addr.clone(),
                json!({
                    "at": count(e.get("checked_at")),
                    "by": RunBy::Button.as_str(),
                    "outcome": "ok",
                    "error": Value::Null,
                    "offered": count(e.get("manifest")),
                    "fetched": count(e.get("downloaded")),
                    "delivered": count(e.get("served")),
                }),
            ));
        }
        let run_at = count(s.get("last_run_utc"));
        for d in s
            .get("devices")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            let Some(addr) = d.get("address").and_then(Value::as_str) else {
                continue;
            };
            let error = d.get("error").filter(|e| !e.is_null()).cloned();
            found.push((
                addr.to_string(),
                json!({
                    "at": run_at,
                    "by": RunBy::Schedule.as_str(),
                    "outcome": if error.is_some() { "failed" } else { "ok" },
                    "error": error.unwrap_or(Value::Null),
                    "offered": count(d.get("files")),
                    "fetched": count(d.get("shown")),
                    "delivered": count(d.get("stored")),
                }),
            ));
        }
        s.remove("devices");
        let panels = s
            .entry("panels")
            .or_insert_with(|| Value::Object(Map::new()));
        let Some(panels) = panels.as_object_mut() else {
            return;
        };
        for (addr, v) in found {
            if !reported.admits(&addr) {
                continue;
            }
            let newer = panels
                .get(&addr)
                .is_none_or(|cur| count(cur.get("at")) < count(v.get("at")));
            if newer {
                if !panels.contains_key(&addr) {
                    carried += 1;
                }
                panels.insert(addr, v);
            }
        }
    })?;
    if legacy.exists() {
        std::fs::remove_file(legacy).map_err(|e| e.to_string())?;
    }
    Ok(carried)
}

/// [`migrate_at`] on the owner's files, at daemon start.
pub fn migrate() {
    let (Some(state), Some(dir)) = (state_path(), crate::cloud::config_dir()) else {
        return;
    };
    let legacy = dir.join("hot_update_state.json");
    match migrate_at(&state, &legacy, &crate::reported_panels::Reported::load()) {
        Ok(0) => {}
        Ok(n) => {
            println!(
                "divoomd: carried {n} panel(s)' hot-channel record into hotchannel_state.json"
            );
        }
        Err(e) => eprintln!("divoomd: could not carry the old hot-channel records over: {e}"),
    }
}

#[cfg(test)]
#[path = "hot_verdict_tests.rs"]
mod tests;
