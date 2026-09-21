//! Wall configuration against the daemon's fleet: transport reuse and
//! coordinate binding. Split from `multi_device_routing.rs` (file-size cap).

use divoomd::daemon::Daemon;
use divoomd::protocol::make_request;
use divoomd::socket_server::Handler;
use serde_json::json;

#[tokio::test]
async fn test_wall_configure_reuses_daemon_transports_and_binds_coordinates() {
    let d = Daemon::new();

    // 1. Connect DEV_A into daemon fleet
    let conn = d
        .handle(make_request(
            "connect",
            Some(json!({"mock": true, "mac": "DEV_A"})),
            None,
        ))
        .await;
    assert_eq!(conn["success"], json!(true));

    // 2. Configure a wall containing DEV_A
    let wall_res = d
        .handle(make_request(
            "wall_configure",
            Some(json!({
                "slots": {
                    "DEV_A": { "x": 10, "y": 20, "size": 16, "width": 16, "height": 16 }
                }
            })),
            None,
        ))
        .await;
    assert_eq!(wall_res["success"], json!(true));
    assert_eq!(wall_res["wall"], json!(true));

    // 3. Verify slot coordinates and device presence
    {
        // The wall lock is held for one read that copies the slot facts out;
        // the assertions run on the copy.
        let slots: Vec<(String, i32, i32, i32, bool)> = d
            .wall
            .lock()
            .await
            .as_ref()
            .expect("wall should be configured")
            .devices
            .iter()
            .map(|s| (s.mac.clone(), s.x, s.y, s.size, s.device.is_some()))
            .collect();
        assert_eq!(
            slots,
            vec![("DEV_A".to_string(), 10, 20, 16, true)],
            "(mac, x, y, size, device present)"
        );
    }

    // 4. Tear down wall with empty slots
    let teardown = d
        .handle(make_request(
            "wall_configure",
            Some(json!({"slots": {}})),
            None,
        ))
        .await;
    assert_eq!(teardown["success"], json!(true));

    // DEV_A must still be preserved in daemon.devices
    assert!(d.fleet.connected("DEV_A").await.is_some());
}
