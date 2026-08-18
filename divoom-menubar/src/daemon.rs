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

/// Active devices the daemon knows about → `(name, kind)` rows for the menu
/// (parity with the pyobjc menubar's activity tiles; lightweight, no BLE scan).
pub fn device_activity() -> Vec<(String, String)> {
    let Some(v) = request("get_device_activity", json!({})) else {
        return Vec::new();
    };
    let Some(map) = v.get("activity").and_then(|a| a.as_object()) else {
        return Vec::new();
    };
    let mut rows: Vec<(String, String)> = map
        .values()
        .map(|d| {
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
            (name, kind)
        })
        .collect();
    rows.sort();
    rows
}

/// Whether the notification listener is running (menu label state).
pub fn notifications_running() -> bool {
    let Some(v) = request("notification_status", json!({})) else {
        return false;
    };
    v.get("running")
        .and_then(|r| r.as_bool())
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
mod tests {
    use super::*;
    use std::io::{BufRead, BufReader, Write};
    use std::os::unix::net::UnixListener;
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::{Arc, Mutex};
    use std::thread;
    use std::time::Duration;

    // `socket_path()` reads the process-global DIVOOM_SOCKET env var; cargo
    // test runs tests in parallel threads by default, so any test that sets
    // it must serialize against every other one that does, or they race.
    static ENV_LOCK: Mutex<()> = Mutex::new(());

    /// Spawns a fake daemon on a unique socket path: replies `reply` to a
    /// plain request, or for `subscribe` streams `events` (newline-delimited)
    /// then keeps the connection open (idle) until the test tears it down.
    struct FakeDaemon {
        socket_path: String,
        _guard: std::sync::MutexGuard<'static, ()>,
    }

    impl FakeDaemon {
        fn start(reply: Value, subscribe_events: Vec<Value>) -> FakeDaemon {
            let guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
            let path = format!(
                "/tmp/divoom_menubar_test_{}_{:?}.sock",
                std::process::id(),
                thread::current().id()
            );
            let _ = std::fs::remove_file(&path);
            let listener = UnixListener::bind(&path).expect("bind fake daemon socket");
            std::env::set_var("DIVOOM_SOCKET", &path);

            thread::spawn(move || {
                for stream in listener.incoming() {
                    let Ok(mut stream) = stream else { continue };
                    let mut reader = BufReader::new(stream.try_clone().unwrap());
                    let mut line = String::new();
                    if reader.read_line(&mut line).unwrap_or(0) == 0 {
                        continue;
                    }
                    let req: Value = serde_json::from_str(&line).unwrap_or(json!({}));
                    if req.get("command").and_then(|c| c.as_str()) == Some("subscribe") {
                        for ev in &subscribe_events {
                            let mut out = serde_json::to_vec(ev).unwrap();
                            out.push(b'\n');
                            if stream.write_all(&out).is_err() {
                                break;
                            }
                        }
                        // Hold the connection open briefly so the reader's
                        // should_stop() polling loop gets a chance to run
                        // before EOF would otherwise end the test early.
                        thread::sleep(Duration::from_millis(300));
                    } else {
                        let mut out = serde_json::to_vec(&reply).unwrap();
                        out.push(b'\n');
                        let _ = stream.write_all(&out);
                    }
                }
            });

            FakeDaemon {
                socket_path: path,
                _guard: guard,
            }
        }
    }

    impl Drop for FakeDaemon {
        fn drop(&mut self) {
            let _ = std::fs::remove_file(&self.socket_path);
        }
    }

    #[test]
    fn connection_state_reads_the_field_from_device_status() {
        let _daemon = FakeDaemon::start(
            json!({"success": true, "connected": true, "connection_state": "degraded"}),
            vec![],
        );
        assert_eq!(connection_state().as_deref(), Some("degraded"));
    }

    #[test]
    fn connection_state_is_none_when_daemon_unreachable() {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        std::env::set_var("DIVOOM_SOCKET", "/tmp/divoom_menubar_test_nonexistent.sock");
        assert_eq!(connection_state(), None);
    }

    #[test]
    fn subscribe_delivers_every_broadcast_event_in_order() {
        let events = vec![
            json!({"type": "status", "state": "degraded", "connected": true}),
            json!({"type": "status", "state": "disconnected", "connected": false}),
            json!({"type": "owned_devices", "devices": []}),
        ];
        let daemon = FakeDaemon::start(json!({}), events.clone());

        let received = Arc::new(Mutex::new(Vec::new()));
        let stop = Arc::new(AtomicBool::new(false));
        let received_cl = received.clone();
        let stop_cl = stop.clone();
        std::env::set_var("DIVOOM_SOCKET", &daemon.socket_path);
        let handle = thread::spawn(move || {
            subscribe(
                |ev| received_cl.lock().unwrap().push(ev),
                || stop_cl.load(Ordering::Relaxed),
            )
        });
        thread::sleep(Duration::from_millis(400));
        stop.store(true, Ordering::Relaxed);
        let connected = handle.join().unwrap();

        assert!(connected, "subscribe should report it connected");
        assert_eq!(*received.lock().unwrap(), events);
    }
}
