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

/// Everything the menubar knows about ONE panel. The single per-device
/// struct (2026-09-12): the link state used to be one field on the whole
/// snapshot, so four panels shared one "connected", and a status event for
/// one of them overwrote the others'.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DeviceView {
    pub mac: String,
    pub name: String,
    /// What the panel is showing (`clock`, `sysmon`, ...; `idle` when nothing).
    pub kind: String,
    pub preview: Option<String>,
    /// The daemon's link state for this panel (`active`, `degraded`,
    /// `disconnected`, ...) as last broadcast; `None` until one arrives.
    pub link: Option<String>,
    /// The ACTIVE panel: the one the bench shows and mac-less requests go
    /// to. One per fleet; set by the daemon's `selection`/`owned_devices`
    /// broadcasts and by `select_device`.
    pub selected: bool,
}

impl DeviceView {
    fn new(mac: &str, name: &str) -> Self {
        Self {
            mac: mac.to_string(),
            name: name.to_string(),
            kind: String::new(),
            preview: None,
            link: None,
            selected: false,
        }
    }
}

#[derive(Default, Clone, Debug)]
pub struct DaemonSnapshot {
    pub reachable: bool,
    pub notifications_running: bool,
    pub devices: Vec<DeviceView>,
    pub last_event_at: Option<std::time::Instant>,
    /// A status broadcast that named no device (the daemon's single-device
    /// era, or a fleet-wide disconnect). Consulted only when no device
    /// carries its own link state.
    fleet_link: Option<String>,
}

impl DaemonSnapshot {
    /// A snapshot assembled by polling (`device_status` + activity), for
    /// when the subscribe stream is stale. The polled `connection_state`
    /// names no device, so it lands as the fleet-wide word.
    #[must_use]
    pub fn polled(
        reachable: bool,
        connection_state: Option<&str>,
        notifications_running: bool,
        devices: Vec<DeviceView>,
    ) -> Self {
        Self {
            reachable,
            notifications_running,
            devices,
            last_event_at: Some(std::time::Instant::now()),
            fleet_link: connection_state.map(str::to_string),
        }
    }

    /// The one state the tray icon shows, DERIVED from the devices: any
    /// degraded panel wins, else any active one, else the fleet-wide word.
    #[must_use]
    pub fn connection_state(&self) -> Option<String> {
        let links: Vec<&str> = self
            .devices
            .iter()
            .filter_map(|d| d.link.as_deref())
            .collect();
        if links.contains(&"degraded") {
            return Some("degraded".to_string());
        }
        if let Some(l) = links.iter().find(|l| matches!(**l, "active" | "connected")) {
            return Some((*l).to_string());
        }
        links
            .first()
            .map(|l| (*l).to_string())
            .or_else(|| self.fleet_link.clone())
    }

    fn device_mut(&mut self, mac: &str) -> &mut DeviceView {
        let idx = self
            .devices
            .iter()
            .position(|d| d.mac.eq_ignore_ascii_case(mac))
            .unwrap_or_else(|| {
                self.devices.push(DeviceView::new(mac, "Divoom"));
                self.devices.len() - 1
            });
        &mut self.devices[idx]
    }
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

    let Some(event_type) = ev
        .get("type")
        .or_else(|| ev.get("event"))
        .and_then(Value::as_str)
    else {
        return;
    };
    match event_type {
        "status" => snap.apply_status(ev),
        "notification_status" => {
            snap.notifications_running =
                ev.get("running").and_then(Value::as_bool).unwrap_or(false);
        }
        "owned_devices" => snap.apply_owned_devices(ev),
        "activity" => snap.apply_activity(ev),
        "selection" => snap.apply_selection(ev.get("mac").and_then(Value::as_str)),
        _ => {}
    }
}

impl DaemonSnapshot {
    /// A `status` broadcast: per-device when it names a panel (`mac` or
    /// `lan_ip`), fleet-wide when it names nobody (a disconnect-all).
    fn apply_status(&mut self, ev: &Value) {
        let state = ev.get("state").and_then(Value::as_str).map_or_else(
            || {
                ev.get("connected").and_then(Value::as_bool).map(|c| {
                    if c {
                        "connected".to_string()
                    } else {
                        "disconnected".to_string()
                    }
                })
            },
            |st| Some(st.to_string()),
        );
        let Some(state) = state else { return };
        let id = ev
            .get("mac")
            .and_then(Value::as_str)
            .map(str::to_string)
            .or_else(|| {
                ev.get("lan_ip")
                    .and_then(Value::as_str)
                    .map(|ip| format!("LAN:{ip}"))
            });
        if let Some(mac) = id {
            // Per-device: only that panel's link moves.
            self.device_mut(&mac).link = Some(state);
        } else {
            for d in &mut self.devices {
                d.link = Some(state.clone());
            }
            self.fleet_link = Some(state);
        }
    }

    /// The daemon's full owned-device list replaces ours; a device that
    /// carries no `state` keeps the link we already knew for it.
    fn apply_owned_devices(&mut self, ev: &Value) {
        let Some(devs) = ev.get("devices").and_then(Value::as_array) else {
            return;
        };
        let previous = std::mem::take(&mut self.devices);
        self.devices = devs
            .iter()
            .filter_map(|d| {
                let mac = d
                    .get("mac")
                    .or_else(|| d.get("address"))
                    .and_then(Value::as_str)?;
                let text = |k: &str| d.get(k).and_then(Value::as_str).map(str::to_string);
                Some(DeviceView {
                    mac: mac.to_string(),
                    name: text("name").unwrap_or_else(|| "Divoom".to_string()),
                    kind: text("kind").unwrap_or_default(),
                    preview: text("preview"),
                    link: text("state").or_else(|| {
                        previous
                            .iter()
                            .find(|x| x.mac.eq_ignore_ascii_case(mac))
                            .and_then(|x| x.link.clone())
                    }),
                    selected: d.get("selected").and_then(Value::as_bool).unwrap_or(false),
                })
            })
            .collect();
    }

    /// A `selection` broadcast (or a polled `selected`): exactly one panel
    /// is active, and a panel the daemon names that this view has not seen
    /// yet is added so the mark never points at nothing.
    pub fn apply_selection(&mut self, mac: Option<&str>) {
        for d in &mut self.devices {
            d.selected = mac.is_some_and(|m| d.mac.eq_ignore_ascii_case(m));
        }
        if let Some(m) = mac {
            if !self.devices.iter().any(|d| d.selected) {
                let mut v = DeviceView::new(m, m);
                v.selected = true;
                self.devices.push(v);
            }
        }
    }

    fn apply_activity(&mut self, ev: &Value) {
        let Some(mac) = ev.get("mac").and_then(Value::as_str) else {
            return;
        };
        let name_opt = ev.get("name").and_then(Value::as_str);
        let kind = ev
            .get("kind")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        let preview = ev
            .get("preview")
            .and_then(Value::as_str)
            .map(str::to_string);
        let existing = self.device_mut(mac);
        if let Some(n) = name_opt {
            if !n.is_empty() {
                existing.name = n.to_string();
            }
        }
        existing.kind = kind;
        if preview.is_some() {
            existing.preview = preview;
        }
    }
}

pub fn set_cached_snapshot(snap: DaemonSnapshot) {
    let mut guard = SNAPSHOT.lock().unwrap();
    *guard = Some(snap);
}

/// The fleet as the daemon sees it, from the `owned_devices` command --
/// the same payload it broadcasts, so the polled fallback and the event
/// stream cannot disagree. Before 2026-09-12 this was rebuilt from
/// `get_device_activity`, which lists only panels with a live-widget
/// record: with two idle panels linked the tray said "No active devices".
pub fn owned_devices() -> Vec<DeviceView> {
    let Some(v) = request("owned_devices", json!({})) else {
        return Vec::new();
    };
    let mut snap = DaemonSnapshot::default();
    snap.apply_owned_devices(&v);
    snap.devices.sort_by(|a, b| a.name.cmp(&b.name));
    snap.devices
}

mod commands;
pub use commands::*;

#[cfg(all(test, unix))]
mod tests;
