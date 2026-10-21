//! Getting an alarm to the owner's phone.
//!
//! # Why not the log
//!
//! The hot-channel loop used to report a failure with one line on the
//! daemon's stdout. A failure that only exists in a log is a failure nobody
//! hears: the loop was enabled, scheduled, and pushing to nothing for 36 days
//! and the only evidence was a file nobody read. So a failed run POSTs to the
//! estate's own push endpoint, the same one the rest of the estate uses
//! (`routines` posts its dead-scheduler alarm there).
//!
//! # The channel
//!
//! Deliberately just a URL. The body is plain text and the endpoint is
//! whatever the operator configured, so ntfy, a Slack or Discord webhook, a
//! Telegram bot URL and Pushover all work without this file knowing about any
//! of them. The URL is a bearer capability, so it lives in the estate's
//! existing secrets file (`~/.routines/env`, key `ROUTINES_PUSH_URL`) and in
//! the environment — NOT in this repo and NOT in the divoom settings.
//!
//! Off means off: with no endpoint configured there is nowhere to post, and
//! the loop says so — loudly, once per run — instead of pretending the alarm
//! went somewhere.

use serde_json::{json, Value};
use std::path::PathBuf;
use std::time::Duration;

/// The environment key holding the push endpoint.
pub const PUSH_URL_ENV: &str = "ROUTINES_PUSH_URL";

/// The estate's secrets file, where the endpoint lives when it is not in the
/// environment.
pub const ESTATE_ENV_FILE: &str = ".routines/env";

/// A failure's priority. `high`, deliberately not `urgent`: urgent punches
/// through Do Not Disturb, and whether a picture frame's daily art push is
/// allowed to wake someone at 3am is the operator's call.
pub const PRIORITY_FAILURE: &str = "high";

/// A recovery's priority — quiet, because good news that buzzes as hard as
/// bad news is how an operator learns to silence the channel.
pub const PRIORITY_RECOVERY: &str = "default";

/// A POST that hangs must not hold the loop's slot.
const TIMEOUT: Duration = Duration::from_secs(10);

/// Where the push endpoint comes from, if it is configured at all.
///
/// The environment first (a launchd job or a shell can set it), then the
/// estate's secrets file. The second is the same file `routines` reads, so
/// this daemon uses the estate's channel rather than inventing a second one.
#[must_use]
pub fn push_url() -> Option<String> {
    if let Ok(url) = std::env::var(PUSH_URL_ENV) {
        let url = url.trim().to_string();
        if !url.is_empty() {
            return Some(url);
        }
    }
    let path = estate_env_path()?;
    let text = std::fs::read_to_string(path).ok()?;
    env_value(&text, PUSH_URL_ENV)
}

/// The estate's secrets file, if this home has one.
#[must_use]
pub fn estate_env_path() -> Option<PathBuf> {
    let home = std::env::var("HOME").ok()?;
    let mut path = PathBuf::from(home);
    for part in ESTATE_ENV_FILE.split('/') {
        path.push(part);
    }
    Some(path)
}

/// One `KEY=VALUE` out of an env file.
fn env_value(text: &str, key: &str) -> Option<String> {
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let Some((name, value)) = line.split_once('=') else {
            continue;
        };
        if name.trim() == key {
            let value = value.trim();
            if !value.is_empty() {
                return Some(value.to_string());
            }
        }
    }
    None
}

/// POST `body` to the owner's phone, and say whether it landed.
///
/// A 2xx is the only success. Anything else is reported with its status, so a
/// revoked token or a typo'd topic reads as a broken channel rather than a
/// quiet one — the distinction this whole path exists to preserve.
///
/// # Errors
///
/// When no endpoint is configured, or the endpoint did not accept the post.
pub async fn notify_owner(title: &str, body: &str, priority: &str) -> Result<(), String> {
    let Some(url) = push_url() else {
        return Err(format!(
            "no owner-alert channel configured ({PUSH_URL_ENV} is unset and {ESTATE_ENV_FILE} has no such key)"
        ));
    };
    let client = reqwest::Client::builder()
        .timeout(TIMEOUT)
        .build()
        .map_err(|e| format!("cannot build the alert client: {e}"))?;
    let response = client
        .post(&url)
        .header("Title", title)
        .header("Priority", priority)
        .body(body.to_string())
        .send()
        .await
        .map_err(|e| format!("the alert did not reach {url}: {e}"))?;
    let status = response.status();
    if status.is_success() {
        Ok(())
    } else {
        Err(format!(
            "the alert endpoint {url} answered HTTP {}",
            status.as_u16()
        ))
    }
}

/// Where the loop remembers the last run's outcome.
#[must_use]
pub fn state_path() -> Option<PathBuf> {
    Some(crate::cloud::config_dir()?.join("hotchannel_state.json"))
}

/// The last run's outcome: `"ok"`, `"failed"`, or `None` when the loop has
/// never run (or the state was lost).
#[must_use]
pub fn last_outcome() -> Option<String> {
    let path = state_path()?;
    let text = std::fs::read_to_string(path).ok()?;
    let value: Value = serde_json::from_str(&text).ok()?;
    value
        .get("last_outcome")
        .and_then(Value::as_str)
        .map(str::to_string)
}

/// When the last run happened, in unix seconds.
#[must_use]
pub fn last_run_at() -> Option<u64> {
    let path = state_path()?;
    let text = std::fs::read_to_string(path).ok()?;
    let value: Value = serde_json::from_str(&text).ok()?;
    value.get("last_run_utc").and_then(Value::as_u64)
}

/// Remember the last run's outcome, so the next one can tell a recovery from
/// a first run.
///
/// # Errors
///
/// When the state file cannot be written.
pub fn record_outcome(outcome: &str, detail: &str) -> Result<(), String> {
    record_outcome_with(outcome, detail, &Value::Null)
}

/// Remember the last run's outcome AND what each device holds.
///
/// The state has to say WHICH happened, not only that the run was "ok": the
/// owner's question about a push is whether the art landed on the device, and
/// that is the difference between the files a device was SHOWN and the files
/// it STORED.
///
/// # Errors
///
/// When the state file cannot be written.
pub fn record_outcome_with(outcome: &str, detail: &str, devices: &Value) -> Result<(), String> {
    let Some(path) = state_path() else {
        return Err("no config directory to record the run's outcome in".to_string());
    };
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let state = json!({
        "last_outcome": outcome,
        "last_detail": detail,
        "last_run_utc": crate::civil_time::unix_seconds(),
        "devices": devices,
    });
    let text = serde_json::to_string_pretty(&state).map_err(|e| e.to_string())?;
    std::fs::write(&path, text + "\n").map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_endpoint_comes_out_of_the_estates_env_file() {
        let text = "# comment\nOTHER=1\nROUTINES_PUSH_URL=https://ntfy.sh/topic\n";
        assert_eq!(
            env_value(text, PUSH_URL_ENV),
            Some("https://ntfy.sh/topic".to_string())
        );
    }

    #[test]
    fn a_missing_endpoint_is_not_an_empty_one() {
        assert_eq!(env_value("OTHER=1\n", PUSH_URL_ENV), None);
        assert_eq!(env_value("", PUSH_URL_ENV), None);
        assert_eq!(env_value("ROUTINES_PUSH_URL=   \n", PUSH_URL_ENV), None);
    }
}
