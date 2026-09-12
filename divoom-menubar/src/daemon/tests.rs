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
    fn start(reply: Value, subscribe_events: Vec<Value>) -> Self {
        let guard = ENV_LOCK
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
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
                let req: Value = serde_json::from_str(&line).unwrap_or_else(|_| json!({}));
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

        Self {
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
    // Bound only to keep the fake daemon ALIVE for the test; its Drop
    // shuts it down.
    let _daemon = FakeDaemon::start(
        json!({"success": true, "connected": true, "connection_state": "degraded"}),
        vec![],
    );
    assert_eq!(connection_state().as_deref(), Some("degraded"));
}

#[test]
fn connection_state_is_none_when_daemon_unreachable() {
    let _guard = ENV_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    std::env::set_var("DIVOOM_SOCKET", "/tmp/divoom_menubar_test_nonexistent.sock");
    assert_eq!(connection_state(), None);
}

#[expect(
    clippy::significant_drop_tightening,
    reason = "an RAII fixture, not a lock: dropping it early shuts the fake daemon down before the subscriber connects, which the ordering assertion below then fails on"
)]
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

#[test]
fn snapshot_updates_from_stream_events() {
    let ev_status = json!({
        "type": "status",
        "connected": true,
        "connection_state": "connected"
    });
    update_snapshot_from_event(&ev_status);
    let snap = get_cached_snapshot().expect("snapshot should exist");
    assert!(snap.reachable);
    assert_eq!(snap.connection_state.as_deref(), Some("connected"));

    let ev_devices = json!({
        "type": "owned_devices",
        "devices": [
            {"mac": "11:22:33:44:55:66", "name": "Ditoo Pro", "kind": "ditoo_pro", "preview": "data:image/png;base64,xxx"}
        ]
    });
    update_snapshot_from_event(&ev_devices);
    let snap2 = get_cached_snapshot().expect("snapshot should exist");
    assert_eq!(snap2.devices.len(), 1);
    assert_eq!(snap2.devices[0].name, "Ditoo Pro");
    assert_eq!(snap2.devices[0].mac, "11:22:33:44:55:66");

    let ev_act = json!({
        "type": "activity",
        "mac": "11:22:33:44:55:66",
        "kind": "clock",
        "preview": "data:image/png;base64,yyy"
    });
    update_snapshot_from_event(&ev_act);
    let snap3 = get_cached_snapshot().expect("snapshot should exist");
    assert_eq!(snap3.devices[0].kind, "clock");
    assert_eq!(snap3.devices[0].name, "Ditoo Pro");
    assert_eq!(
        snap3.devices[0].preview.as_deref(),
        Some("data:image/png;base64,yyy")
    );
}
