//! The write commands the menu sends (one short-lived request each).

use serde_json::json;

use super::request;

/// Make `mac` the active panel for every client (bench, menubar, CLI).
pub fn select_device(mac: &str) {
    let _ = request("select_device", json!({ "mac": mac }));
}

pub fn switch_channel(mac: &str, channel: &str) {
    let _ = request(
        "device_call",
        json!({
            "mac": mac,
            "method": "display.switch_channel",
            "kwargs": { "channel": channel }
        }),
    );
}

pub fn set_screen_power(mac: &str, on: bool) {
    let _ = request(
        "device_call",
        json!({
            "mac": mac,
            "method": "system.set_screen_on",
            "kwargs": { "on": on }
        }),
    );
}

/// Whether the notification listener is running (menu label state).
pub fn notifications_running() -> bool {
    let Some(v) = request("notification_status", json!({})) else {
        return false;
    };
    v.get("running")
        .and_then(serde_json::Value::as_bool)
        .or_else(|| {
            v.get("state")
                .and_then(|s| s.as_str())
                .map(|s| s == "running")
        })
        .unwrap_or(false)
}

pub fn start_notifications() {
    let _ = request("start_notifications", json!({}));
}

pub fn stop_notifications() {
    let _ = request("stop_notifications", json!({}));
}

pub fn shutdown() {
    let _ = request("shutdown", json!({}));
}
