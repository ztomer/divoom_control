//! Brightness and volume are read and written PER PANEL through `device_call`'s
//! `mac` (P5.1).
//!
//! The GUI used to read both once at startup and write them with no mac, so
//! "the" panel was whichever one a mac-less request resolved to. It now names
//! the panel on every call; these pin that the daemon honours the name in both
//! directions, with two mock panels whose staged replies differ: a write lands
//! on the panel named and no other, and a read answers from the panel named.

use crate::daemon::{Daemon, DeviceTransport};
use crate::mock_transport::MockTransport;
use crate::protocol::make_request;
use crate::socket_server::Handler;
use serde_json::{json, Value};

const A: &str = "AA:00:00:00:00:01";
const B: &str = "BB:00:00:00:00:02";

async fn two_panels() -> Daemon {
    let d = Daemon::new();
    for (mac, name) in [(A, "Ditoo-Plus"), (B, "Pixoo64")] {
        let reply = d
            .handle(make_request(
                "connect",
                Some(json!({"mock": true, "mac": mac, "name": name})),
                None,
            ))
            .await;
        assert_eq!(reply["success"], json!(true), "{reply}");
    }
    d
}

async fn mock_of(d: &Daemon, mac: &str) -> MockTransport {
    let dev = d.fleet.get(mac).await.expect("the panel is in the fleet");
    let transport = dev.transport().await.expect("the panel is linked");
    match &*transport {
        DeviceTransport::Mock(m) => m.clone(),
        _ => panic!("expected the mock transport"),
    }
}

async fn call(d: &Daemon, method: &str, args: Value, mac: &str) -> Value {
    d.handle(make_request(
        "device_call",
        Some(json!({"method": method, "args": args, "mac": mac})),
        None,
    ))
    .await
}

/// Every command id one mock was asked to send, in order.
fn sent_ids(m: &MockTransport) -> Vec<(u8, Vec<u8>)> {
    m.sent_commands
        .lock()
        .map(|c| c.clone())
        .unwrap_or_default()
}

#[tokio::test]
async fn a_write_lands_on_the_panel_named_and_no_other() {
    let d = two_panels().await;
    let (a, b) = (mock_of(&d, A).await, mock_of(&d, B).await);

    let reply = call(&d, "device.set_brightness", json!([55]), B).await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    let reply = call(&d, "music.set_volume", json!([9]), A).await;
    assert_eq!(reply["success"], json!(true), "{reply}");

    assert_eq!(
        sent_ids(&b),
        vec![(0x74, vec![55])],
        "B got its brightness only"
    );
    assert_eq!(sent_ids(&a), vec![(0x08, vec![9])], "A got its volume only");
}

#[tokio::test]
async fn a_read_answers_from_the_panel_named() {
    let d = two_panels().await;
    let (a, b) = (mock_of(&d, A).await, mock_of(&d, B).await);
    // 0x46 (light mode) carries brightness at byte 6; 0x09 is the volume.
    for (m, brightness, volume) in [(&a, 30_u8, 5_u8), (&b, 90, 2)] {
        if let Ok(mut staged) = m.simulated_responses.lock() {
            staged.insert(0x46, vec![0, 0, 0, 0, 0, 0, brightness, 0]);
            staged.insert(0x09, vec![volume]);
        }
    }

    for (mac, brightness, volume) in [(A, 30, 5), (B, 90, 2), (A, 30, 5)] {
        let got = call(&d, "device.get_brightness", json!([]), mac).await;
        assert_eq!(got["result"], json!(brightness), "{mac}: {got}");
        let got = call(&d, "music.get_volume", json!([]), mac).await;
        assert_eq!(got["result"], json!(volume), "{mac}: {got}");
    }
}

#[tokio::test]
async fn device_status_describes_each_panel_by_its_own_name() {
    let d = two_panels().await;
    let st = d.handle(make_request("device_status", None, None)).await;
    let devices = st["devices"].as_array().cloned().unwrap_or_default();
    let width_of = |mac: &str| {
        devices
            .iter()
            .find(|e| e["mac"] == json!(mac))
            .map(|e| e["width"].clone())
    };
    assert_eq!(width_of(A), Some(json!(16)), "{st}");
    assert_eq!(width_of(B), Some(json!(64)), "{st}");
}
