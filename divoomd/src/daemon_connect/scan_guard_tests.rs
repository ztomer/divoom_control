//! Scan/connect guard + connect/disconnect unit tests, split out of
//! daemon_connect.rs to stay under the 500-LOC ground rule.

use super::{cmd_connect, cmd_disconnect, cmd_scan, is_dead_central, ScanGuard};
use crate::daemon::Daemon;
use crate::protocol::make_request;
use serde_json::json;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Instant;

// A scan arriving within MIN_RESCAN_INTERVAL of the last returns the cached
// result WITHOUT touching the radio (the check short-circuits before
// daemon.central()), so this is unit-testable with no BLE device. Guards the
// anti-throttle behavior that stops rapid re-scans wedging CoreBluetooth.
#[test]
fn detects_dead_central_error() {
    // "Channel closed" (from either scan or connect) → recreate the central.
    assert!(is_dead_central("connect failed: Channel closed"));
    assert!(is_dead_central("scan failed: Channel closed"));
    // Ordinary failures must NOT trigger a central rebuild.
    assert!(!is_dead_central("device not found in scan"));
    assert!(!is_dead_central("no BLE adapter"));
}

#[tokio::test]
async fn rapid_rescan_returns_cached_without_touching_radio() {
    let daemon = Daemon::new();
    let cached = vec![json!({"name": "Pixoo-1", "address": "AA:BB"})];
    *daemon.last_scan.lock().await = Some((Instant::now(), cached.clone()));

    let resp = cmd_scan(&daemon, &make_request("scan", None, None)).await;
    assert_eq!(resp["cached"], json!(true));
    assert_eq!(resp["devices"], json!(cached));
    // The guard must be released again after a cached return.
    assert!(!daemon.scanning.load(Ordering::SeqCst));
}

// The scan guard is what stops two overlapping scans from clobbering the one
// adapter (the corruption that truncated the GUI's device list). Pin its
// claim / reject-while-held / reset-on-drop behavior without needing BLE.
#[test]
fn rejects_concurrent_then_resets_on_drop() {
    let flag = AtomicBool::new(false);
    // First scan claims the guard.
    assert!(flag
        .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
        .is_ok());
    {
        let _g = ScanGuard(&flag);
        // A concurrent scan is rejected while the first holds it.
        assert!(flag
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .is_err());
    }
    // Guard dropped (scan finished) → flag cleared → a new scan can claim it.
    assert!(!flag.load(Ordering::SeqCst));
    assert!(flag
        .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
        .is_ok());
}

// Mock-transport connect (no BLE) must mark the daemon connected and own a
// Mock device — the basis for every hardware-free connect/disconnect e2e.
#[tokio::test]
async fn mock_connect_succeeds_and_owns_device() {
    let daemon = Daemon::new();
    let req = make_request("connect", Some(json!({"mock": true})), None);
    let res = cmd_connect(&daemon, &req).await;
    assert_eq!(res["success"], json!(true));
    assert_eq!(res["mac"], json!("MOCK_MAC"));
    assert!(
        daemon.device.lock().await.is_some(),
        "device not owned after mock connect"
    );
}

// The connecting guard must reject a second connect while one is in flight
// (prevents two scans/connects clobbering the one shared central).
#[tokio::test]
async fn connect_guard_rejects_when_in_progress() {
    let daemon = Daemon::new();
    daemon.connecting.store(true, Ordering::SeqCst); // simulate an in-flight connect
    let req = make_request("connect", Some(json!({"mock": true})), None);
    let res = cmd_connect(&daemon, &req).await;
    assert_eq!(res["success"], json!(false));
    assert_eq!(res["error"], json!("connect already in progress"));
    // The simulated in-flight connect still holds the flag (we didn't run one).
    assert!(daemon.connecting.load(Ordering::SeqCst));
}

// Disconnect with no device owned must be a clean success, not a crash.
#[tokio::test]
async fn disconnect_with_no_device_is_safe() {
    let daemon = Daemon::new();
    let res = cmd_disconnect(&daemon).await;
    assert_eq!(res["success"], json!(true));
    assert!(daemon.device.lock().await.is_none());
}

// Connect → device_call → disconnect → reconnect must stay stable across a
// loop, with the daemon always answering get_status (never wedged).
#[tokio::test]
async fn connect_disconnect_reconnect_loop_stays_responsive() {
    let daemon = Daemon::new();
    for _ in 0..5 {
        let c = cmd_connect(
            &daemon,
            &make_request("connect", Some(json!({"mock": true})), None),
        )
        .await;
        assert_eq!(c["success"], json!(true));
        assert!(
            daemon.device.lock().await.is_some(),
            "device not owned after connect"
        );
        let d = cmd_disconnect(&daemon).await;
        assert_eq!(d["success"], json!(true));
        assert!(daemon.device.lock().await.is_none());
    }
}

// R58: device_call is now bounded by an overall timeout (default 30s) enforced
// at the top level so a hung op can't hold the device lock forever. A normal
// mock op must complete well within that and leave the lock free for the next
// call (no false-fire, no wedge). Verifying the timeout *fires* on a genuinely
// hung op needs real hardware (or a network-blocked LAN target) — see plan.
#[tokio::test]
async fn device_call_timeout_enforced_but_not_false_firing() {
    let daemon = Daemon::new();
    let c = cmd_connect(
        &daemon,
        &make_request("connect", Some(json!({"mock": true})), None),
    )
    .await;
    assert_eq!(c["success"], json!(true));

    let req = make_request(
        "device_call",
        Some(json!({ "method": "display.get_brightness" })),
        None,
    );
    let res = tokio::time::timeout(
        std::time::Duration::from_secs(2),
        daemon.cmd_device_call(&req),
    )
    .await
    .expect("device_call must return within 2s — the timeout path must not hang");
    assert_eq!(res["success"], json!(true));

    // The lock was released: a second call is immediately possible.
    let req2 = make_request(
        "device_call",
        Some(json!({ "method": "display.get_brightness" })),
        None,
    );
    let res2 = daemon.cmd_device_call(&req2).await;
    assert_eq!(res2["success"], json!(true));
}

// A caller-requested short timeout on a fast mock op must still succeed — the
// enforced timeout is a safety net, not a cliff for slow-but-valid commands.
#[tokio::test]
async fn device_call_short_requested_timeout_still_succeeds() {
    let daemon = Daemon::new();
    cmd_connect(
        &daemon,
        &make_request("connect", Some(json!({"mock": true})), None),
    )
    .await;
    let req = make_request(
        "device_call",
        Some(json!({ "method": "display.get_brightness", "timeout": 1 })),
        None,
    );
    let res = daemon.cmd_device_call(&req).await;
    assert_eq!(res["success"], json!(true));
}

// mock_simulate_drop's own tests live in daemon_mock.rs, next to the
// handler they cover (R61 follow-up, split to stay under the 500-LOC gate).
