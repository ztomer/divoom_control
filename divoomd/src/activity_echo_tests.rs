//! A client's menubar thumbnail is echoed as a THUMBNAIL (DV.CLOCKTHUMB).
//!
//! The GUI records its channel with `set_device_activity` and a 36 px PNG for
//! the menubar's tile. The daemon broadcast that PNG back as `preview`, the
//! same field a live job's frame rides in, so the bench drew the tile -- a
//! blurred, upscaled clock -- over the crisp one its own renderer draws. The
//! echo now says what its pixels are, and a live job's frame does not.

use crate::daemon::Daemon;
use crate::protocol::make_request;
use crate::socket_server::Handler;
use serde_json::{json, Value};

const PANEL: &str = "AA:00:00:00:00:01";

async fn activity_after(args: Value) -> Value {
    let d = Daemon::new();
    let reply = d
        .handle(make_request(
            "connect",
            Some(json!({"mock": true, "mac": PANEL, "name": "Ditoo-Plus"})),
            None,
        ))
        .await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    let mut rx = d.tx.subscribe();
    let reply = d
        .handle(make_request("set_device_activity", Some(args), None))
        .await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    let mut seen = None;
    while let Ok(ev) = rx.try_recv() {
        if ev["type"] == json!("activity") {
            seen = Some(ev);
        }
    }
    seen.expect("set_device_activity published no activity event")
}

#[tokio::test]
async fn a_recorded_thumbnail_is_echoed_as_a_thumbnail() {
    let ev = activity_after(json!({
        "mac": PANEL, "kind": "clock", "name": "Ditoo-Plus", "preview": "data:image/png;base64,AA=="
    }))
    .await;
    assert_eq!(ev["preview"], json!("data:image/png;base64,AA=="), "{ev}");
    assert_eq!(ev["preview_is"], json!("thumbnail"), "{ev}");
}

#[tokio::test]
async fn a_record_without_pixels_names_no_preview() {
    let ev = activity_after(json!({"mac": PANEL, "kind": "clock"})).await;
    assert!(ev.get("preview").is_none(), "{ev}");
    assert!(ev.get("preview_is").is_none(), "{ev}");
}
