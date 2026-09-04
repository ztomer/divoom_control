//! macOS notification monitor.
//!
//! Polls the macOS Notification Center SQLite database for new app notifications,
//! parses binary plists using the `plist` crate, routes app bundle IDs to slots 1-14,
//! and forwards them to the connected Divoom device via ANCS `0x50` command.
//!
//! Exposes status events and counters to match Python parity.
//!
//! DB access lives in `notification_db.rs`, routing-rule load/save/match in
//! `notification_routing.rs` (both split out to stay under the 500-LOC house
//! limit) — this file keeps the monitor state/loop and device-forwarding.

use serde_json::{json, Value};
use std::collections::HashSet;
use std::sync::Arc;
use tokio::sync::Mutex;

use crate::daemon::Daemon;
use crate::notification_db::{
    fetch_new_records, find_notification_db_path, initial_max_delivered_date,
    parse_notification_record,
};
use crate::notification_routing::{load_routing_rules, route_app, save_routing_rules};

// ── state ─────────────────────────────────────────────────────────────────

struct MonitorState {
    running: bool,
    seen_ids: HashSet<String>,
    task: Option<tokio::task::JoinHandle<()>>,
    seen_count: usize,
    routed_count: usize,
    dropped_count: usize,
    last_seen_date: f64,
    db_error_streak: usize,
    last_db_error: Option<String>,
    rules: Vec<(String, u8)>,
}

impl MonitorState {
    fn new() -> Self {
        MonitorState {
            running: false,
            seen_ids: HashSet::new(),
            task: None,
            seen_count: 0,
            routed_count: 0,
            dropped_count: 0,
            last_seen_date: 0.0,
            db_error_streak: 0,
            last_db_error: None,
            rules: load_routing_rules(),
        }
    }
}

static MONITOR: std::sync::OnceLock<Arc<Mutex<MonitorState>>> = std::sync::OnceLock::new();

fn state() -> Arc<Mutex<MonitorState>> {
    MONITOR
        .get_or_init(|| Arc::new(Mutex::new(MonitorState::new())))
        .clone()
}

// ── public API ────────────────────────────────────────────────────────────

/// Start the background notification monitor.
pub async fn start_monitor(daemon: Arc<Daemon>) {
    let st = state();
    let mut guard = st.lock().await;
    if guard.running {
        return;
    }

    // Probe database existence and accessibility
    let db_path = match find_notification_db_path() {
        Some(p) => p,
        None => {
            guard.last_db_error = Some("macOS Notification Center DB not found".to_string());
            guard.db_error_streak = 5;
            let _ = daemon.tx.send(notif_status_event(&guard));
            return;
        }
    };

    // Test if we can open and read
    match rusqlite::Connection::open_with_flags(
        &db_path,
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
    ) {
        Ok(conn) => {
            if let Err(e) = conn.execute("SELECT 1", []) {
                guard.last_db_error = Some(format!("Database read failed (FDA permission?): {e}"));
                guard.db_error_streak = 5;
                let _ = daemon.tx.send(notif_status_event(&guard));
                return;
            }
        }
        Err(e) => {
            guard.last_db_error = Some(format!("Database open failed: {e}"));
            guard.db_error_streak = 5;
            let _ = daemon.tx.send(notif_status_event(&guard));
            return;
        }
    }

    guard.running = true;
    guard.seen_ids.clear();
    guard.last_seen_date = initial_max_delivered_date(&db_path);
    guard.db_error_streak = 0;
    guard.last_db_error = None;

    let st_clone = st.clone();
    let daemon_clone = daemon.clone();
    let handle = tokio::spawn(async move {
        monitor_loop(daemon_clone, st_clone, db_path).await;
    });
    guard.task = Some(handle);
    eprintln!("[macos_notifications] monitor started");

    let _ = daemon.tx.send(notif_status_event(&guard));
}

/// Stop the background notification monitor.
pub async fn stop_monitor() {
    let st = state();
    let mut guard = st.lock().await;
    guard.running = false;
    if let Some(h) = guard.task.take() {
        h.abort();
    }
    eprintln!("[macos_notifications] monitor stopped");
}

fn status_event_payload(guard: &MonitorState) -> Value {
    let state_str = if guard.running {
        if guard.db_error_streak >= 5 {
            "error"
        } else {
            "active"
        }
    } else {
        "idle"
    };
    let mut ev = json!({
        "type": "status",
        "state": state_str,
        "counters": {
            "seen": guard.seen_count,
            "routed": guard.routed_count,
            "dropped": guard.dropped_count,
        }
    });
    if let Some(ref err) = guard.last_db_error {
        if guard.db_error_streak >= 5 {
            ev["error"] = json!(err);
        }
    }
    ev
}

/// Broadcast flavour of the monitor status (R59): a distinct event type so the
/// GUI doesn't confuse it with the device *connection* `status` event. The
/// request/response `notification_status` command keeps `type:"status"` (the
/// web UI's `refreshMacNotifStatus` parses that reply); the push stream uses
/// `notif_status` so `window.Divoom.onNotifStatus` can update live.
fn notif_status_event(guard: &MonitorState) -> Value {
    let mut ev = status_event_payload(guard);
    ev["type"] = json!("notif_status");
    ev
}

pub async fn status_event() -> Value {
    let st = state();
    let guard = st.lock().await;
    status_event_payload(&guard)
}

pub async fn notification_status() -> Value {
    let st = state();
    let guard = st.lock().await;
    let mut res = status_event_payload(&guard);
    res["success"] = json!(true);
    res
}

pub async fn set_routing(args: &Value) -> Value {
    let rules_val = match args.get("rules") {
        Some(v) => v,
        None => return json!({"success": false, "error": "set_routing requires 'rules'"}),
    };
    let mut new_rules = Vec::new();
    if let Some(arr) = rules_val.as_array() {
        for entry in arr {
            if let Some(pair) = entry.as_array() {
                if pair.len() == 2 {
                    if let (Some(s), Some(t)) = (pair[0].as_str(), pair[1].as_u64()) {
                        new_rules.push((s.to_lowercase(), t as u8));
                    }
                }
            }
        }
    }

    if let Err(e) = save_routing_rules(&new_rules) {
        return json!({"success": false, "error": format!("failed to save routing: {}", e)});
    }

    let st = state();
    let mut guard = st.lock().await;
    guard.rules = new_rules;

    json!({"success": true})
}

// ── monitor loop ──────────────────────────────────────────────────────────

const POLL_INTERVAL_MS: u64 = 1000;

async fn monitor_loop(
    daemon: Arc<Daemon>,
    st: Arc<Mutex<MonitorState>>,
    db_path: std::path::PathBuf,
) {
    loop {
        {
            let guard = st.lock().await;
            if !guard.running {
                return;
            }
        }
        tokio::time::sleep(tokio::time::Duration::from_millis(POLL_INTERVAL_MS)).await;

        let (last_seen, rules) = {
            let guard = st.lock().await;
            (guard.last_seen_date, guard.rules.clone())
        };

        match fetch_new_records(&db_path, last_seen) {
            Ok(records) => {
                let mut guard = st.lock().await;
                guard.db_error_streak = 0;
                guard.last_db_error = None;

                for (raw, delivered) in records {
                    if delivered > guard.last_seen_date {
                        guard.last_seen_date = delivered;
                    }
                    guard.seen_count += 1;

                    let parsed = match parse_notification_record(&raw) {
                        Some(p) => p,
                        None => {
                            guard.dropped_count += 1;
                            continue;
                        }
                    };

                    let (app, title, body) = parsed;
                    let app_type = match route_app(&app, &rules) {
                        Some(t) => t,
                        None => {
                            guard.dropped_count += 1;
                            continue;
                        }
                    };

                    let dup_key = format!("{}:{}:{}", delivered, app, title);
                    if guard.seen_ids.contains(&dup_key) {
                        guard.dropped_count += 1;
                        continue;
                    }
                    guard.seen_ids.insert(dup_key);

                    let text = if !title.is_empty() {
                        title.split('\n').next().unwrap_or("").trim().to_string()
                    } else if !body.is_empty() {
                        body.split('\n').next().unwrap_or("").trim().to_string()
                    } else {
                        "".to_string()
                    };

                    let routed = forward_notification(&daemon, app_type, &text).await;
                    if routed {
                        guard.routed_count += 1;
                    } else {
                        guard.dropped_count += 1;
                    }

                    let notif_ev = json!({
                        "type": "notification",
                        "app_type": app_type as u64,
                        "title": title,
                        "body": body,
                        "routed": routed
                    });
                    let _ = daemon.tx.send(notif_ev);

                    let _ = daemon.tx.send(notif_status_event(&guard));
                }
            }
            Err(e) => {
                let mut guard = st.lock().await;
                guard.db_error_streak += 1;
                guard.last_db_error = Some(e.clone());
                if guard.db_error_streak == 1 {
                    eprintln!("[macos_notifications] query error (streak 1): {e}");
                }
                if guard.db_error_streak >= 5 {
                    let _ = daemon.tx.send(notif_status_event(&guard));
                }
            }
        }
    }
}

// ── forward one notification to the device ────────────────────────────────

async fn forward_notification(daemon: &Daemon, app_type: u8, text: &str) -> bool {
    let mut payload = Vec::new();
    if text.is_empty() {
        let wire = if app_type >= 8 {
            app_type + 1
        } else {
            app_type
        };
        payload.push(wire);
    } else {
        let mut text_bytes = text.as_bytes().to_vec();
        if text_bytes.len() > 128 {
            text_bytes.truncate(128);
        }
        payload.push(app_type);
        payload.push(text_bytes.len() as u8);
        payload.extend_from_slice(&text_bytes);
    }

    #[cfg(feature = "ble")]
    {
        let guard = daemon.device.lock().await;
        if let Some(ref dev) = *guard {
            match &**dev {
                crate::daemon::DeviceTransport::Ble(ref ble) => {
                    return ble.send_command(0x50, &payload, true).await.is_ok();
                }
                crate::daemon::DeviceTransport::Spp(ref spp) => {
                    return spp.send_command(0x50, &payload, true).await.is_ok();
                }
                crate::daemon::DeviceTransport::Lan(_) => {}
                crate::daemon::DeviceTransport::Mock(ref mock) => {
                    return mock.send_command(0x50, &payload, true).await.is_ok();
                }
            }
        }
    }
    #[cfg(not(feature = "ble"))]
    {
        let _ = (daemon, payload);
    }
    false
}
