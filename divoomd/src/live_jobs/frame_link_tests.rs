//! A live widget is the most common writer to a panel, so it is usually how
//! a dropped link is noticed at all (P2.8).
//!
//! Before this, a live frame whose command could not be sent was a `false`
//! and nothing else: the panel kept reading as connected, no drop was
//! reported, and the job carried on saying "running" at a panel that was
//! gone. The `device_call` path learned the same thing and reported it; this
//! path now reports it too, through the same two broadcasts.

use std::sync::atomic::AtomicBool;
use std::sync::Arc;

use serde_json::json;

use super::frame::{push_live_frame, LiveFrame};
use crate::daemon::Daemon;
use crate::daemon_connect::status_payload;
use crate::mock_transport::MockTransport;
use crate::protocol::make_request;
use crate::socket_server::Handler;

const PANEL: &str = "P28_LIVE";

async fn daemon_with_panel() -> Arc<Daemon> {
    let d = Arc::new(Daemon::new());
    let reply = d
        .handle(make_request(
            "connect",
            Some(json!({ "mock": true, "mac": PANEL })),
            None,
        ))
        .await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    d
}

async fn mock_of(d: &Daemon) -> MockTransport {
    let dev = d.fleet.get(PANEL).await.expect("the panel is in the fleet");
    let transport = dev.transport().await.expect("the panel is linked");
    match &*transport {
        crate::daemon::DeviceTransport::Mock(m) => m.clone(),
        _ => panic!("expected the mock transport"),
    }
}

/// A frame that cannot be sent retires the link: the panel stops reading as
/// connected, and the drop is on the bus.
#[tokio::test]
async fn a_live_frame_that_cannot_be_sent_retires_the_link() {
    let d = daemon_with_panel().await;
    let mock = mock_of(&d).await;
    let mut rx = d.tx.subscribe();
    // The panel's link goes away between the connect and the frame.
    mock.set_failing(true);

    let alive = Arc::new(AtomicBool::new(true));
    let landed = push_live_frame(
        &d,
        PANEL,
        "sysmon",
        &alive,
        LiveFrame {
            rgb: vec![0u8; 2 * 2 * 3],
            w: 2,
            h: 2,
            time_ms: 100,
        },
    )
    .await;
    assert!(!landed, "the frame could not be sent");

    let named = d
        .handle(make_request(
            "device_status",
            Some(json!({ "mac": PANEL })),
            None,
        ))
        .await;
    assert_eq!(
        named["connected"],
        json!(false),
        "the dropped panel still reads as connected: {named}"
    );

    let mut disconnected = false;
    while let Ok(ev) = rx.try_recv() {
        if ev["type"] == json!("status") && ev["connected"] == json!(false) {
            assert_eq!(ev["state"], json!("disconnected"), "{ev}");
            disconnected = true;
        }
    }
    assert!(disconnected, "the drop was not reported on the bus");
}

/// The drop is reported the way the daemon reports every other one: the same
/// status shape a user-initiated disconnect sends.
#[tokio::test]
async fn the_reported_drop_is_the_shape_the_daemon_uses() {
    let d = daemon_with_panel().await;
    let mock = mock_of(&d).await;
    mock.set_failing(true);
    let alive = Arc::new(AtomicBool::new(true));
    let _ = push_live_frame(
        &d,
        PANEL,
        "sysmon",
        &alive,
        LiveFrame {
            rgb: vec![0u8; 2 * 2 * 3],
            w: 2,
            h: 2,
            time_ms: 100,
        },
    )
    .await;

    let expected = status_payload(false, Some(PANEL), Some("disconnected"));
    assert_eq!(expected["type"], json!("status"));
    assert_eq!(expected["connected"], json!(false));
    assert_eq!(expected["mac"], json!(PANEL));
}
