//! Lean daemon socket client for the menubar — short-lived NDJSON request/response
//! over the same unix socket the GUI/daemon use (`{"command","args"}` + `\n`, one
//! JSON reply per line). The menubar only needs a handful of read/poll commands
//! plus notification start/stop and shutdown, so each call opens its own
//! connection (no persistent state to manage). Mirrors the Python
//! `daemon_protocol`/`menubar_client` wire format.

use serde_json::{json, Value};

/// Socket path (env override matches the GUI/daemon: `DIVOOM_SOCKET`).
pub fn socket_path() -> String {
    std::env::var("DIVOOM_SOCKET").unwrap_or_else(|_| "/tmp/divoom.sock".to_string())
}

/// One request → one reply. `None` if the daemon is unreachable or the reply
/// doesn't parse (the caller treats unreachable as "daemon offline").
#[cfg(unix)]
#[expect(
    clippy::needless_pass_by_value,
    reason = "the value is serialised into the request and never wanted again; borrowing puts an & on every call site to save a move of something the caller has finished with"
)]
pub fn request(command: &str, args: Value) -> Option<Value> {
    use std::io::{BufRead, BufReader, Write};
    use std::os::unix::net::UnixStream;
    use std::time::Duration;

    let stream = UnixStream::connect(socket_path()).ok()?;
    stream.set_read_timeout(Some(Duration::from_secs(6))).ok()?;
    stream
        .set_write_timeout(Some(Duration::from_secs(6)))
        .ok()?;
    let mut w = stream.try_clone().ok()?;
    let mut line = serde_json::to_vec(&json!({ "command": command, "args": args })).ok()?;
    line.push(b'\n');
    w.write_all(&line).ok()?;
    w.flush().ok()?;
    let mut reader = BufReader::new(stream);
    let mut buf = String::new();
    if reader.read_line(&mut buf).ok()? == 0 {
        return None;
    }
    serde_json::from_str(&buf).ok()
}

// Windows transport (daemon TCP+token) is deferred — same status as divoomd's own
// Windows support. The menubar still runs; it just reports the daemon offline.
#[cfg(not(unix))]
pub fn request(_command: &str, _args: Value) -> Option<Value> {
    None
}

/// Daemon liveness + state, for the status-coloured glyph.
pub enum Status {
    Offline,
    Idle,
    Active,
}

#[expect(
    clippy::option_if_let_else,
    reason = "a two-level lookup: the daemon answering at all, then what it said. `map_or_else` nests a closure in a closure to save one `match`"
)]
pub fn status() -> Status {
    match request("get_status", json!({})) {
        None => Status::Offline,
        Some(v) => match v.get("state").and_then(|s| s.as_str()) {
            Some("active") => Status::Active,
            _ => Status::Idle,
        },
    }
}

/// The daemon's honest device connection state (`device_status`'s
/// `connection_state` field): `Some("connected")`/`Some("degraded")`/
/// `Some("disconnected")`, or `None` if unreachable or no device is owned.
/// Mirrors the Python GUI's `ScannerMixin.get_connection_state` (R61
/// follow-up — the menubar previously never read this at all).
pub fn connection_state() -> Option<String> {
    let v = request("device_status", json!({}))?;
    v.get("connection_state")
        .and_then(|s| s.as_str())
        .map(str::to_string)
}

/// Open a `subscribe` stream and call `on_event` for each broadcast until the
/// connection closes or `should_stop()` returns true. Blocking — run on a
/// dedicated thread. Returns `true` if it connected at all (mirrors the
/// Python `DaemonClient.subscribe` this is a port of); `false` means the
/// daemon was unreachable, so the caller should back off before retrying.
#[cfg(unix)]
pub fn subscribe(mut on_event: impl FnMut(Value), should_stop: impl Fn() -> bool) -> bool {
    use std::io::{Read, Write};
    use std::os::unix::net::UnixStream;
    use std::time::Duration;

    let Ok(mut stream) = UnixStream::connect(socket_path()) else {
        return false;
    };
    if stream
        .set_read_timeout(Some(Duration::from_millis(500)))
        .is_err()
    {
        return false;
    }
    let req = match serde_json::to_vec(&json!({ "command": "subscribe" })) {
        Ok(mut v) => {
            v.push(b'\n');
            v
        }
        Err(_) => return false,
    };
    if stream.write_all(&req).is_err() {
        return false;
    }

    let mut buf = Vec::new();
    let mut chunk = [0u8; 4096];
    loop {
        if should_stop() {
            return true;
        }
        match stream.read(&mut chunk) {
            Ok(0) => return true, // daemon closed the stream
            Ok(n) => buf.extend_from_slice(&chunk[..n]),
            Err(e)
                if e.kind() == std::io::ErrorKind::WouldBlock
                    || e.kind() == std::io::ErrorKind::TimedOut =>
            {
                continue; // short read timeout so should_stop() stays responsive
            }
            Err(_) => return false,
        }
        // Cap the unparsed buffer, mirroring the Python client's guard
        // against a malformed/never-newline-terminated frame growing forever.
        if buf.len() > 16 * 1024 * 1024 {
            return false;
        }
        while let Some(pos) = buf.iter().position(|&b| b == b'\n') {
            let line: Vec<u8> = buf.drain(..=pos).collect();
            if let Ok(ev) = serde_json::from_slice::<Value>(&line[..line.len().saturating_sub(1)]) {
                on_event(ev);
            }
        }
    }
}

#[cfg(not(unix))]
pub fn subscribe(_on_event: impl FnMut(Value), _should_stop: impl Fn() -> bool) -> bool {
    false
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DeviceActivityItem {
    pub mac: String,
    pub name: String,
    pub kind: String,
    pub preview: Option<String>,
}

#[derive(Default, Clone, Debug)]
pub struct DaemonSnapshot {
    pub reachable: bool,
    pub connection_state: Option<String>,
    pub notifications_running: bool,
    pub devices: Vec<DeviceActivityItem>,
    pub last_event_at: Option<std::time::Instant>,
}

static SNAPSHOT: std::sync::Mutex<Option<DaemonSnapshot>> = std::sync::Mutex::new(None);

pub fn get_cached_snapshot() -> Option<DaemonSnapshot> {
    SNAPSHOT.lock().unwrap().clone()
}

#[expect(
    clippy::significant_drop_tightening,
    reason = "updates the cached DaemonSnapshot in place under the mutex lock"
)]
pub fn update_snapshot_from_event(ev: &Value) {
    let mut guard = SNAPSHOT.lock().unwrap();
    let snap = guard.get_or_insert_with(DaemonSnapshot::default);
    snap.reachable = true;
    snap.last_event_at = Some(std::time::Instant::now());

    if let Some(event_type) = ev
        .get("type")
        .or_else(|| ev.get("event"))
        .and_then(Value::as_str)
    {
        match event_type {
            "status" => {
                if let Some(st) = ev.get("state").and_then(Value::as_str) {
                    snap.connection_state = Some(st.to_string());
                } else if let Some(conn) = ev.get("connected").and_then(Value::as_bool) {
                    snap.connection_state = Some(if conn {
                        "connected".to_string()
                    } else {
                        "disconnected".to_string()
                    });
                }
            }
            "notification_status" => {
                snap.notifications_running =
                    ev.get("running").and_then(Value::as_bool).unwrap_or(false);
            }
            "owned_devices" => {
                if let Some(devs) = ev.get("devices").and_then(Value::as_array) {
                    snap.devices = devs
                        .iter()
                        .filter_map(|d| {
                            let mac = d
                                .get("mac")
                                .or_else(|| d.get("address"))
                                .and_then(Value::as_str)?;
                            let name = d
                                .get("name")
                                .and_then(Value::as_str)
                                .unwrap_or("Divoom")
                                .to_string();
                            let kind = d
                                .get("kind")
                                .and_then(Value::as_str)
                                .unwrap_or("")
                                .to_string();
                            let preview =
                                d.get("preview").and_then(Value::as_str).map(str::to_string);
                            Some(DeviceActivityItem {
                                mac: mac.to_string(),
                                name,
                                kind,
                                preview,
                            })
                        })
                        .collect();
                }
            }
            "activity" => {
                if let Some(mac) = ev.get("mac").and_then(Value::as_str) {
                    let name = ev
                        .get("name")
                        .and_then(Value::as_str)
                        .unwrap_or("Divoom")
                        .to_string();
                    let kind = ev
                        .get("kind")
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .to_string();
                    let preview = ev
                        .get("preview")
                        .and_then(Value::as_str)
                        .map(str::to_string);
                    if let Some(existing) = snap.devices.iter_mut().find(|d| d.mac == mac) {
                        existing.name = name;
                        existing.kind = kind;
                        if preview.is_some() {
                            existing.preview = preview;
                        }
                    } else {
                        snap.devices.push(DeviceActivityItem {
                            mac: mac.to_string(),
                            name,
                            kind,
                            preview,
                        });
                    }
                }
            }
            _ => {}
        }
    }
}

pub fn set_cached_snapshot(snap: DaemonSnapshot) {
    let mut guard = SNAPSHOT.lock().unwrap();
    *guard = Some(snap);
}

pub fn device_activity_items() -> Vec<DeviceActivityItem> {
    let Some(v) = request("get_device_activity", json!({})) else {
        return Vec::new();
    };
    let Some(map) = v.get("activity").and_then(|a| a.as_object()) else {
        return Vec::new();
    };
    let mut items: Vec<DeviceActivityItem> = map
        .iter()
        .map(|(mac, d)| {
            let name = d
                .get("name")
                .and_then(|n| n.as_str())
                .unwrap_or("Divoom")
                .to_string();
            let kind = d
                .get("kind")
                .and_then(|k| k.as_str())
                .unwrap_or("")
                .to_string();
            let preview = d
                .get("preview")
                .and_then(|p| p.as_str())
                .map(str::to_string);
            DeviceActivityItem {
                mac: mac.clone(),
                name,
                kind,
                preview,
            }
        })
        .collect();
    items.sort_by(|a, b| a.name.cmp(&b.name));
    items
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

#[cfg(all(test, unix))]
mod tests;
