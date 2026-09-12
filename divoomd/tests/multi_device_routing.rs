//! Integration tests for multi-device concurrent routing and per-device command queues.
#![expect(
    clippy::too_many_lines,
    clippy::significant_drop_tightening,
    reason = "integration scenario orchestrates multi-device dispatch and inspects lock guards"
)]

use divoomd::daemon::{Daemon, DeviceTransport};
use divoomd::protocol::make_request;
use divoomd::socket_server::Handler;
use serde_json::json;

/// The mock transport behind a connected device.
async fn transport_of(d: &Daemon, mac: &str) -> std::sync::Arc<DeviceTransport> {
    d.fleet
        .get(mac)
        .await
        .expect("device known")
        .transport()
        .await
        .expect("device connected")
}

#[tokio::test]
async fn test_concurrent_multi_device_routing() {
    let d = Daemon::new();

    // 1. Connect Device A and Device B with mock transports
    let conn_a = d
        .handle(make_request(
            "connect",
            Some(json!({"mock": true, "mac": "DEV_A"})),
            None,
        ))
        .await;
    assert_eq!(conn_a["success"], json!(true));
    assert_eq!(conn_a["mac"], json!("DEV_A"));

    let conn_b = d
        .handle(make_request(
            "connect",
            Some(json!({"mock": true, "mac": "DEV_B"})),
            None,
        ))
        .await;
    assert_eq!(conn_b["success"], json!(true));
    assert_eq!(conn_b["mac"], json!("DEV_B"));

    // Verify both are present in the devices registry
    assert!(d.fleet.connected("DEV_A").await.is_some());
    assert!(d.fleet.connected("DEV_B").await.is_some());

    // 2. Issue targeted device_call to DEV_A
    let call_a = d
        .handle(make_request(
            "device_call",
            Some(json!({
                "mac": "DEV_A",
                "method": "display.set_clock_rich",
                "kwargs": {
                    "style": 1,
                    "color": "#ff0000"
                }
            })),
            None,
        ))
        .await;
    assert_eq!(call_a["success"], json!(true));

    // 3. Issue targeted device_call to DEV_B
    let call_b = d
        .handle(make_request(
            "device_call",
            Some(json!({
                "mac": "DEV_B",
                "method": "display.set_clock_rich",
                "kwargs": {
                    "style": 3,
                    "color": "#0000ff"
                }
            })),
            None,
        ))
        .await;
    assert_eq!(call_b["success"], json!(true));

    // 4. Verify commands reached DEV_A and DEV_B independently
    {
        let trans_a = transport_of(&d, "DEV_A").await;
        let trans_b = transport_of(&d, "DEV_B").await;

        if let (DeviceTransport::Mock(ref mock_a), DeviceTransport::Mock(ref mock_b)) =
            (&*trans_a, &*trans_b)
        {
            let cmds_a = mock_a.sent_commands.lock().unwrap();
            let cmds_b = mock_b.sent_commands.lock().unwrap();
            assert_eq!(cmds_a.len(), 1);
            assert_eq!(cmds_b.len(), 1);
            assert_eq!(cmds_a[0].0, 0x45);
            assert_eq!(cmds_b[0].0, 0x45);
            // Red vs Blue payload check
            assert_eq!(cmds_a[0].1[7..10], [0xFF, 0x00, 0x00]);
            assert_eq!(cmds_b[0].1[7..10], [0x00, 0x00, 0xFF]);
        } else {
            panic!("expected mock transports");
        }
    }

    // 5. Per-device queue isolation: lock DEV_A exclusively
    let q_a = d
        .fleet
        .get("DEV_A")
        .await
        .unwrap()
        .link()
        .await
        .unwrap()
        .queue
        .clone();
    let acq = q_a.acquire_now("TOKEN_FOR_A");
    assert!(acq.is_ok());

    // Call to DEV_A with mismatched token is rejected
    let call_a_foreign = d
        .handle(make_request(
            "device_call",
            Some(json!({
                "mac": "DEV_A",
                "token": "FOREIGN_TOKEN",
                "method": "display.set_clock_rich",
                "kwargs": { "style": 0 }
            })),
            None,
        ))
        .await;
    assert_eq!(call_a_foreign["success"], json!(false));
    assert!(call_a_foreign["error"]
        .as_str()
        .unwrap()
        .contains("exclusively held"));

    // Call to DEV_B is NOT blocked by DEV_A's exclusive lock!
    let call_b_unblocked = d
        .handle(make_request(
            "device_call",
            Some(json!({
                "mac": "DEV_B",
                "token": "ANY_TOKEN",
                "method": "display.set_clock_rich",
                "kwargs": { "style": 5 }
            })),
            None,
        ))
        .await;
    assert_eq!(call_b_unblocked["success"], json!(true));
}

#[tokio::test]
async fn test_live_job_persists_across_device_switch() {
    use std::sync::Arc;
    let d = Arc::new(Daemon::new());
    d.initialize_self_weak(Arc::downgrade(&d));

    // 1. Connect Device A
    let conn_a = d
        .handle(make_request(
            "connect",
            Some(json!({"mock": true, "mac": "DEV_A"})),
            None,
        ))
        .await;
    assert_eq!(conn_a["success"], json!(true));

    // 2. Start sysmon live job on DEV_A
    let job_res = d
        .handle(make_request(
            "live_job_start",
            Some(json!({
                "kind": "sysmon",
                "mac": "DEV_A",
                "interval_s": 1.0,
                "params": {"size": 16}
            })),
            None,
        ))
        .await;
    assert_eq!(job_res["success"], json!(true));

    // 3. Connect Device B (which becomes active in single-device view)
    let conn_b = d
        .handle(make_request(
            "connect",
            Some(json!({"mock": true, "mac": "DEV_B"})),
            None,
        ))
        .await;
    assert_eq!(conn_b["success"], json!(true));

    // 4. Verify DEV_A's transport is still in `d.devices`
    assert!(d.fleet.connected("DEV_A").await.is_some());
    assert!(d.fleet.connected("DEV_B").await.is_some());

    // Wait 1.5s for sysmon loop to tick on DEV_A
    tokio::time::sleep(tokio::time::Duration::from_millis(1500)).await;

    // 5. Verify DEV_A's mock transport received sysmon frames (when native encoder is available)
    if d.encoder().is_some() {
        let trans_a = transport_of(&d, "DEV_A").await;
        if let DeviceTransport::Mock(ref mock_a) = &*trans_a {
            let cmds = mock_a.sent_commands.lock().unwrap();
            assert!(
                !cmds.is_empty(),
                "DEV_A should continue receiving live frames while DEV_B is connected"
            );
        }
    }

    // Verify the live job is registered in d.live_jobs
    {
        let jobs = d.live_jobs.list(Some("DEV_A")).await;
        assert_eq!(jobs.len(), 1);
        assert_eq!(jobs[0]["kind"], "sysmon");
        assert_eq!(jobs[0]["mac"], "DEV_A");
    }

    // Stop live job
    let stop_res = d
        .handle(make_request(
            "live_job_stop",
            Some(json!({"kind": "sysmon", "mac": "DEV_A"})),
            None,
        ))
        .await;
    assert_eq!(stop_res["success"], json!(true));
}

#[tokio::test]
async fn test_device_call_preempts_conflicting_live_jobs() {
    use std::sync::Arc;
    let d = Arc::new(Daemon::new());
    d.initialize_self_weak(Arc::downgrade(&d));

    // 1. Connect DEV_A
    let conn = d
        .handle(make_request(
            "connect",
            Some(json!({"mock": true, "mac": "DEV_A"})),
            None,
        ))
        .await;
    assert_eq!(conn["success"], json!(true));

    // 2. Start sysmon live job on DEV_A
    let job_res = d
        .handle(make_request(
            "live_job_start",
            Some(json!({
                "kind": "sysmon",
                "mac": "DEV_A",
                "interval_s": 1.0,
                "params": {"size": 16}
            })),
            None,
        ))
        .await;
    assert_eq!(job_res["success"], json!(true));

    // Verify job is running
    assert_eq!(d.live_jobs.list(Some("DEV_A")).await.len(), 1);

    // 3. Send a display-disruptive device call (e.g. switch_channel)
    let call = d
        .handle(make_request(
            "device_call",
            Some(json!({
                "mac": "DEV_A",
                "method": "display.switch_channel",
                "kwargs": {"channel": "clock"}
            })),
            None,
        ))
        .await;
    assert_eq!(call["success"], json!(true));

    // 4. Verify sysmon was cleanly preempted and is no longer running on DEV_A
    assert_eq!(
        d.live_jobs.list(Some("DEV_A")).await.len(),
        0,
        "Live job on DEV_A should have been preempted by switch_channel"
    );
}

#[tokio::test]
async fn test_device_call_set_screen_on_and_standby_preemption() {
    use std::sync::Arc;
    let d = Arc::new(Daemon::new());
    d.initialize_self_weak(Arc::downgrade(&d));

    // 1. Connect DEV_A
    let conn = d
        .handle(make_request(
            "connect",
            Some(json!({"mock": true, "mac": "DEV_A"})),
            None,
        ))
        .await;
    assert_eq!(conn["success"], json!(true));

    // 2. Start sysmon live job on DEV_A
    let job_res = d
        .handle(make_request(
            "live_job_start",
            Some(json!({
                "kind": "sysmon",
                "mac": "DEV_A",
                "interval_s": 1.0,
                "params": {"size": 16}
            })),
            None,
        ))
        .await;
    assert_eq!(job_res["success"], json!(true));
    assert_eq!(d.live_jobs.list(Some("DEV_A")).await.len(), 1);

    // 3. Send system.set_screen_on with on: false
    let off_call = d
        .handle(make_request(
            "device_call",
            Some(json!({
                "mac": "DEV_A",
                "method": "system.set_screen_on",
                "kwargs": {"on": false}
            })),
            None,
        ))
        .await;
    assert_eq!(off_call["success"], json!(true));

    // 4. Verify live job was preempted by standby/screen-off
    assert_eq!(
        d.live_jobs.list(Some("DEV_A")).await.len(),
        0,
        "Live job should be stopped when display power is turned off"
    );

    // 5. Verify 0x74 with 0 was sent to mock device
    {
        let trans_a = transport_of(&d, "DEV_A").await;
        if let DeviceTransport::Mock(ref mock) = &*trans_a {
            let cmds = mock.sent_commands.lock().unwrap();
            let last_cmd = cmds.last().expect("command should be recorded");
            assert_eq!(last_cmd.0, 0x74);
            assert_eq!(last_cmd.1, [0x00]);
        }
    }

    // 6. Send system.set_screen_on with on: true and explicit brightness: 80
    let on_call = d
        .handle(make_request(
            "device_call",
            Some(json!({
                "mac": "DEV_A",
                "method": "system.set_screen_on",
                "kwargs": {"on": true, "brightness": 80}
            })),
            None,
        ))
        .await;
    assert_eq!(on_call["success"], json!(true));

    {
        let trans_a = transport_of(&d, "DEV_A").await;
        if let DeviceTransport::Mock(ref mock) = &*trans_a {
            let cmds = mock.sent_commands.lock().unwrap();
            let last_cmd = cmds.last().expect("command should be recorded");
            assert_eq!(last_cmd.0, 0x74);
            assert_eq!(last_cmd.1, [80]);
        }
    }
}

#[tokio::test]
async fn test_set_device_activity_broadcasts_event() {
    let d = Daemon::new();
    let mut rx = d.subscribe().expect("broadcast subscriber available");

    let res = d
        .handle(make_request(
            "set_device_activity",
            Some(json!({
                "mac": "AA:BB:CC:DD:EE:FF",
                "kind": "custom_art",
                "name": "Ditoo Pro",
                "preview": "data:image/png;base64,mock"
            })),
            None,
        ))
        .await;
    assert_eq!(res["success"], json!(true));

    // Verify broadcast event was received
    let ev = rx.recv().await.expect("event should be broadcast");
    assert_eq!(ev["type"], json!("activity"));
    assert_eq!(ev["mac"], json!("AA:BB:CC:DD:EE:FF"));
    assert_eq!(ev["kind"], json!("custom_art"));
    assert_eq!(ev["name"], json!("Ditoo Pro"));
    assert_eq!(ev["preview"], json!("data:image/png;base64,mock"));
}

#[tokio::test]
async fn test_disconnect_stops_live_jobs_and_drains_devices() {
    use std::sync::Arc;
    let d = Arc::new(Daemon::new());
    d.initialize_self_weak(Arc::downgrade(&d));

    // Connect DEV_A and DEV_B
    let _ = d
        .handle(make_request(
            "connect",
            Some(json!({"mock": true, "mac": "DEV_A"})),
            None,
        ))
        .await;
    let _ = d
        .handle(make_request(
            "connect",
            Some(json!({"mock": true, "mac": "DEV_B"})),
            None,
        ))
        .await;

    // Start sysmon on DEV_A
    let start_res = d
        .handle(make_request(
            "live_job_start",
            Some(json!({"kind": "sysmon", "mac": "DEV_A", "interval_s": 1.0})),
            None,
        ))
        .await;
    assert_eq!(start_res["success"], json!(true));
    assert_eq!(d.live_jobs.list(None).await.len(), 1);

    // Issue disconnect command
    let disc_res = d.handle(make_request("disconnect", None, None)).await;
    assert_eq!(disc_res["success"], json!(true));

    // Assert live jobs were cleanly stopped and devices cleared
    assert_eq!(d.live_jobs.list(None).await.len(), 0);
    assert!(d.fleet.linked().await.is_empty());
    let st = d.handle(make_request("device_status", None, None)).await;
    assert_eq!(st["connected"], json!(false));
}
