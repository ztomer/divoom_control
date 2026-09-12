//! Wall configuration against the daemon's fleet: transport reuse and
//! coordinate binding. Split from `multi_device_routing.rs` (file-size cap).

use divoomd::daemon::Daemon;
use divoomd::protocol::make_request;
use divoomd::socket_server::Handler;
use serde_json::json;

#[tokio::test]
#[expect(
    clippy::significant_drop_tightening,
    reason = "the wall guard is inspected field by field; the scope block already bounds it"
)]
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
        let wall_guard = d.wall.lock().await;
        let wall = wall_guard.as_ref().expect("wall should be configured");
        assert_eq!(wall.devices.len(), 1);
        let slot = &wall.devices[0];
        assert_eq!(slot.mac, "DEV_A");
        assert_eq!(slot.x, 10);
        assert_eq!(slot.y, 20);
        assert_eq!(slot.size, 16);
        assert!(slot.device.is_some());
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
