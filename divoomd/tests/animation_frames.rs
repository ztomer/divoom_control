//! A multi-frame `show_image` streams every frame with its own timing (P4.4).
//!
//! Through the real dispatcher onto a mock panel: three frames of different
//! colours and durations go in, and the 0x8B blob the panel receives is read
//! back frame by frame -- `AA LLLL TTTT RR NN` headers, little-endian.

use base64::Engine;
use divoomd::daemon::{Daemon, DeviceTransport};
use divoomd::protocol::make_request;
use divoomd::socket_server::Handler;
use serde_json::json;

/// What the mock panel `mac` was sent, in order.
async fn recorded(d: &Daemon, mac: &str) -> Vec<(u8, Vec<u8>)> {
    let t = d
        .fleet
        .get(mac)
        .await
        .expect("device known")
        .transport()
        .await
        .expect("device connected");
    let DeviceTransport::Mock(ref mock) = *t else {
        panic!("not a mock panel");
    };
    let sent = mock.sent_commands.lock().unwrap().clone();
    sent
}

/// `(time_ms)` of every frame in a 0x8B animation blob.
fn frame_times(blob: &[u8]) -> Vec<u16> {
    let mut times = Vec::new();
    let mut at = 0;
    while at + 7 <= blob.len() {
        assert_eq!(blob[at], 0xAA, "frame {} starts at {at}", times.len());
        let len = usize::from(u16::from_le_bytes([blob[at + 1], blob[at + 2]]));
        times.push(u16::from_le_bytes([blob[at + 3], blob[at + 4]]));
        at += len;
    }
    assert_eq!(at, blob.len(), "the blob ends on a frame boundary");
    times
}

#[tokio::test]
async fn every_frame_reaches_the_panel_with_its_duration() {
    let d = Daemon::new();
    let r = d
        .handle(make_request(
            "connect",
            Some(json!({ "mock": true, "mac": "M" })),
            None,
        ))
        .await;
    assert_eq!(r["success"], json!(true), "{r}");

    let b64 = |c: u8| base64::engine::general_purpose::STANDARD.encode(vec![c; 16 * 16 * 3]);
    let reply = d
        .handle(make_request(
            "device_call",
            Some(json!({
                "mac": "M",
                "method": "show_image",
                "args": [],
                "kwargs": {
                    "w": 16, "h": 16,
                    "frames": [
                        { "rgb_b64": b64(10), "time_ms": 100 },
                        { "rgb_b64": b64(120), "time_ms": 250 },
                        { "rgb_b64": b64(240), "time_ms": 400 },
                    ],
                },
            })),
            None,
        ))
        .await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    assert_eq!(reply["frames"], json!(3), "{reply}");

    let sent = recorded(&d, "M").await;
    let blob = sent
        .iter()
        .rev()
        .find(|(id, _)| *id == 0x8B)
        .map(|(_, b)| b.clone())
        .expect("an 0x8B stream");
    assert_eq!(frame_times(&blob), vec![100, 250, 400]);
}

#[tokio::test]
async fn a_frame_of_the_wrong_length_is_refused_by_index() {
    let d = Daemon::new();
    d.handle(make_request(
        "connect",
        Some(json!({ "mock": true, "mac": "M" })),
        None,
    ))
    .await;
    let ok = base64::engine::general_purpose::STANDARD.encode(vec![0u8; 16 * 16 * 3]);
    let short = base64::engine::general_purpose::STANDARD.encode(vec![0u8; 10]);
    let reply = d
        .handle(make_request(
            "device_call",
            Some(json!({
                "mac": "M", "method": "show_image", "args": [],
                "kwargs": { "w": 16, "h": 16, "frames": [
                    { "rgb_b64": ok, "time_ms": 100 },
                    { "rgb_b64": short, "time_ms": 100 },
                ]},
            })),
            None,
        ))
        .await;
    assert_eq!(reply["success"], json!(false), "{reply}");
    assert!(
        reply["error"]
            .as_str()
            .is_some_and(|e| e.contains("frame 1")),
        "{reply}"
    );
}
