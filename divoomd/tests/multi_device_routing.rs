//! Integration tests for multi-device concurrent routing and per-device command queues.

use divoomd::daemon::{Daemon, DeviceTransport};
use divoomd::protocol::make_request;
use divoomd::socket_server::Handler;
use serde_json::json;

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
    {
        let devices = d.devices.lock().await;
        assert!(devices.contains_key("DEV_A"));
        assert!(devices.contains_key("DEV_B"));
    }

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
        let devices = d.devices.lock().await;
        let trans_a = devices.get("DEV_A").unwrap();
        let trans_b = devices.get("DEV_B").unwrap();

        if let (DeviceTransport::Mock(ref mock_a), DeviceTransport::Mock(ref mock_b)) =
            (&**trans_a, &**trans_b)
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
    let q_a = d.get_device_queue("DEV_A").await;
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
    {
        let devices = d.devices.lock().await;
        assert!(devices.contains_key("DEV_A"));
        assert!(devices.contains_key("DEV_B"));
    }

    // Wait 1.5s for sysmon loop to tick on DEV_A
    tokio::time::sleep(tokio::time::Duration::from_millis(1500)).await;

    // 5. Verify DEV_A's mock transport received sysmon frames
    {
        let devices = d.devices.lock().await;
        let trans_a = devices.get("DEV_A").unwrap();
        if let DeviceTransport::Mock(ref mock_a) = &**trans_a {
            let cmds = mock_a.sent_commands.lock().unwrap();
            assert!(!cmds.is_empty(), "DEV_A should continue receiving live frames while DEV_B is connected");
        }
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
