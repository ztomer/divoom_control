//! A panel on Wi-Fi is refused as a wall slot, and every client is told why
//! (P6.1).
//!
//! The daemon draws images only through the Bluetooth 0x8B stream; a LAN
//! transport has no `send_command` and no `stream_animation_8b`. A wall with a
//! LAN slot used to cut that slot's piece, fail to send it, and report the
//! whole wall as failed with the reason thrown away. Now the slot is left out
//! up front, `wall_configure` names it with the reason, and `device_status`
//! says so for the panel before anyone builds a wall.

use crate::daemon::{Daemon, DeviceTransport};
use crate::protocol::make_request;
use crate::socket_server::Handler;
use crate::wall::LAN_SLOT_REFUSAL;
use serde_json::json;
use std::sync::Arc;

const A: &str = "AA:00:00:00:00:01";
const LAN: &str = "LAN:127.0.0.1";

async fn a_mock_and_a_lan_panel() -> Daemon {
    let d = Daemon::new();
    let reply = d
        .handle(make_request(
            "connect",
            Some(json!({"mock": true, "mac": A, "name": "Ditoo-Plus"})),
            None,
        ))
        .await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    let lan = crate::lan::LanTransport::new("127.0.0.1", 0);
    d.fleet
        .adopt(LAN, Arc::new(DeviceTransport::Lan(lan)))
        .await;
    d
}

#[tokio::test]
async fn wall_configure_leaves_a_lan_panel_out_and_says_why() {
    let d = a_mock_and_a_lan_panel().await;
    let reply = d
        .handle(make_request(
            "wall_configure",
            Some(json!({"slots": {
                A: {"x": 0, "y": 0, "size": 16},
                LAN: {"x": 1, "y": 0, "size": 16},
            }})),
            None,
        ))
        .await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    assert_eq!(reply["refused"][LAN], json!(LAN_SLOT_REFUSAL), "{reply}");
    assert!(
        reply.get("degraded").is_none(),
        "a refusal is not a fault: {reply}"
    );
    let macs: Vec<String> = d
        .wall
        .lock()
        .await
        .as_ref()
        .map(|w| w.devices.iter().map(|s| s.mac.clone()).collect())
        .unwrap_or_default();
    assert_eq!(
        macs,
        vec![A.to_string()],
        "only the Bluetooth panel is a slot"
    );
}

#[tokio::test]
async fn a_wall_of_only_lan_panels_is_refused_with_the_reason() {
    let d = a_mock_and_a_lan_panel().await;
    let reply = d
        .handle(make_request(
            "wall_configure",
            Some(json!({"slots": {LAN: {"x": 0, "y": 0, "size": 16}}})),
            None,
        ))
        .await;
    assert_eq!(reply["success"], json!(false), "{reply}");
    let error = reply["error"].as_str().unwrap_or_default();
    assert!(error.contains(LAN_SLOT_REFUSAL), "{reply}");
}

#[tokio::test]
async fn device_status_says_which_panel_cannot_be_a_wall_slot() {
    let d = a_mock_and_a_lan_panel().await;
    let st = d.handle(make_request("device_status", None, None)).await;
    let devices = st["devices"].as_array().cloned().unwrap_or_default();
    let refusal_of = |mac: &str| {
        devices
            .iter()
            .find(|e| e["mac"] == json!(mac))
            .map(|e| e["wall_refusal"].clone())
    };
    assert_eq!(refusal_of(LAN), Some(json!(LAN_SLOT_REFUSAL)), "{st}");
    assert_eq!(refusal_of(A), Some(json!(null)), "{st}");
}
