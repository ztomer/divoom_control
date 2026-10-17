//! How long each socket command may run before the server answers for it.
//!
//! Before P2.3 nothing bounded `handler.handle(req)`: a command that never
//! returned held its connection permit for the life of the daemon, whether or
//! not anyone was still waiting. `device_call` bounds itself through the
//! command queue; cloud calls, `sync_artwork` and `render_widget` did not.
//!
//! Budgets are PER COMMAND, never one global: one number short enough to catch
//! a stalled `ping` would cut a legitimately slow `sync_artwork` (a cloud
//! download plus a BLE stream). Each budget sits well ABOVE the read timeout
//! the Python client already gives that command (`divoom_client/daemon_config.py`),
//! so in normal use the client gives up first and the deadline only ever
//! reclaims a slot nobody is waiting on. The deadline ends the wait, not the
//! work: a unit already handed to a device's queue still runs to completion
//! (the per-device rule), and only the connection is released.

use std::time::Duration;

use serde_json::Value;

/// Every command not named below: cloud browse, status reads, live-job
/// control, rendering. Three times the client's longest ordinary wait
/// (`cloud_timeout`, 40 s).
pub const DEFAULT_BUDGET: Duration = Duration::from_secs(120);

/// Commands that legitimately run longer than [`DEFAULT_BUDGET`].
///
/// A name here that is not a dispatch arm would silently fall back to the
/// default; `deadlines_tests.rs` reads the dispatcher and fails on one.
pub const BUDGETS: &[(&str, Duration)] = &[
    // Scan time is the caller's (capped at 90 s in `ble.rs`), and a dead
    // central is rebuilt and the scan run a second time.
    ("scan", Duration::from_secs(240)),
    // BLE connect is 20 s per attempt; the client waits 30 s.
    ("connect", Duration::from_secs(120)),
    ("disconnect", Duration::from_secs(120)),
    ("select_device", Duration::from_secs(120)),
    // Download plus a full animation stream; the client waits 120 s.
    ("sync_artwork", Duration::from_secs(600)),
    ("get_animated_preview", Duration::from_secs(600)),
    ("custom_art_push", Duration::from_secs(600)),
    ("custom_art_query_page", Duration::from_secs(600)),
    ("device_call", Duration::from_secs(600)),
    ("wall_configure", Duration::from_secs(600)),
];

/// The deadline for one command.
#[must_use]
pub fn budget(command: &str) -> Duration {
    BUDGETS
        .iter()
        .find(|(name, _)| *name == command)
        .map_or(DEFAULT_BUDGET, |(_, d)| *d)
}

/// The answer for a command that outran its budget (P2.3).
///
/// A stable `code` beside the prose (gRPC's `DEADLINE_EXCEEDED`), with the
/// budget it ran out of, so a client can tell "slow" from "refused" without
/// reading the message. The connection stays open: the deadline ended this
/// command, not the client's session.
pub(crate) fn exceeded(command: &str, budget: Duration) -> Value {
    eprintln!(
        "divoomd: `{command}` outran its {}ms deadline; answering for it",
        budget.as_millis()
    );
    let mut reply = crate::protocol::err_reply(&format!(
        "`{command}` did not finish within its {}ms deadline",
        budget.as_millis()
    ));
    if let Some(obj) = reply.as_object_mut() {
        obj.insert("code".into(), Value::String("deadline_exceeded".into()));
        obj.insert(
            "deadline_ms".into(),
            Value::from(u64::try_from(budget.as_millis()).unwrap_or(u64::MAX)),
        );
    }
    reply
}

#[cfg(test)]
#[path = "deadlines_tests.rs"]
mod tests;
