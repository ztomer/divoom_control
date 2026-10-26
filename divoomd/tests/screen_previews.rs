//! `screen_previews` answers what each panel shows, from the frames the
//! daemon streamed to it, and says WHY when it has no frame (WG.5a).
//!
//! Through the real dispatcher onto mock panels. Both directions: a frame
//! comes back as the very pixels that were pushed, and every absent state
//! (nothing sent, device-rendered, undecoded, offline, unknown) carries no
//! frame and a reason -- never a blank image that looks like data.

use std::sync::Arc;
use std::time::Duration;

use base64::Engine;
use divoomd::daemon::Daemon;
use divoomd::protocol::make_request;
use divoomd::socket_server::Handler;
use serde_json::{json, Value};

const MAC: &str = "SCREEN_A";

async fn ask(d: &Daemon, command: &str, args: Value) -> Value {
    d.handle(make_request(command, Some(args), None)).await
}

async fn linked(macs: &[(&str, &str)]) -> Arc<Daemon> {
    let d = Arc::new(Daemon::new());
    d.initialize_self_weak(Arc::downgrade(&d));
    for (mac, name) in macs {
        let reply = ask(
            &d,
            "connect",
            json!({ "mock": true, "mac": mac, "name": name }),
        )
        .await;
        assert_eq!(reply["success"], json!(true), "{reply}");
    }
    d
}

/// The one entry for `mac`.
async fn entry(d: &Daemon, mac: &str) -> Value {
    let reply = ask(d, "screen_previews", json!({ "mac": mac })).await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    let devices = reply["devices"].as_array().expect("devices").clone();
    assert_eq!(devices.len(), 1, "{reply}");
    devices[0].clone()
}

/// An entry with no pixels, and the reason it has none.
fn assert_absent(got: &Value, state: &str) {
    assert_eq!(got["state"], json!(state), "{got}");
    assert!(got["frame"].is_null(), "no frame without pixels: {got}");
    let why = got["reason"].as_str().unwrap_or_default();
    assert!(why.len() > 20, "an absent state says why: {got}");
}

/// The RGB pixels a `data:image/png` URL holds.
fn pixels_of(data_url: &str) -> (u32, u32, Vec<u8>) {
    let b64 = data_url
        .strip_prefix("data:image/png;base64,")
        .expect("a PNG data URL");
    let png = base64::engine::general_purpose::STANDARD
        .decode(b64)
        .expect("base64");
    let img = image::load_from_memory(&png).expect("a PNG").to_rgb8();
    (img.width(), img.height(), img.into_raw())
}

/// A 16x16 frame with a different colour in every pixel row.
fn gradient() -> Vec<u8> {
    (0..16u8)
        .flat_map(|y| (0..16u8).flat_map(move |x| [y * 15, x * 15, 200]))
        .collect()
}

async fn push(d: &Daemon, rgb: &[u8]) -> Value {
    let b64 = base64::engine::general_purpose::STANDARD.encode(rgb);
    ask(
        d,
        "device_call",
        json!({ "mac": MAC, "method": "show_image", "args": [],
                "kwargs": { "w": 16, "h": 16, "frames": [{ "rgb_b64": b64, "time_ms": 100 }] } }),
    )
    .await
}

#[tokio::test]
async fn a_pushed_image_comes_back_as_the_same_pixels() {
    let d = linked(&[(MAC, "Ditoo-Pro")]).await;
    assert_absent(&entry(&d, MAC).await, "nothing_sent");

    let rgb = gradient();
    let reply = push(&d, &rgb).await;
    assert_eq!(reply["success"], json!(true), "{reply}");

    let got = entry(&d, MAC).await;
    assert_eq!(got["state"], json!("frame"), "{got}");
    assert!(got["reason"].is_null(), "{got}");
    assert_eq!(got["id"], json!(MAC));
    assert_eq!(got["name"], json!("Ditoo-Pro"));
    assert_eq!(got["width"], json!(16), "the panel's size: {got}");
    assert_eq!(got["source"], json!("show_image"));
    assert!(
        got["age_s"]
            .as_f64()
            .is_some_and(|a| (0.0..5.0).contains(&a)),
        "{got}"
    );
    let frame = &got["frame"];
    assert_eq!(
        (frame["width"].clone(), frame["frames"].clone()),
        (json!(16), json!(1))
    );
    assert_eq!(frame["mime"], json!("image/png"));
    let (w, h, got) = pixels_of(frame["data_url"].as_str().expect("data_url"));
    assert_eq!((w, h), (16, 16));
    assert_eq!(got, rgb, "the preview is the pixels the panel was sent");
}

#[tokio::test]
async fn a_repaint_without_pixels_retires_the_frame() {
    let d = linked(&[(MAC, "Ditoo-Pro")]).await;
    assert_eq!(push(&d, &gradient()).await["success"], json!(true));

    let reply = ask(
        &d,
        "device_call",
        json!({ "mac": MAC, "method": "show_clock", "args": [] }),
    )
    .await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    let got = entry(&d, MAC).await;
    assert_absent(&got, "device_rendered");
    assert_eq!(got["source"], json!("show_clock"));

    let blob = vec![0xAAu8, 7, 0, 100, 0, 0, 0];
    let b64 = base64::engine::general_purpose::STANDARD.encode(blob);
    let reply = ask(
        &d,
        "device_call",
        json!({ "mac": MAC, "method": "animation.stream_animation_8b", "args": [],
                "blobs": { "0": b64 } }),
    )
    .await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    assert_absent(&entry(&d, MAC).await, "undecoded");
}

#[tokio::test]
async fn a_non_display_call_leaves_the_frame() {
    let d = linked(&[(MAC, "Ditoo-Pro")]).await;
    assert_eq!(push(&d, &gradient()).await["success"], json!(true));
    let reply = ask(
        &d,
        "device_call",
        json!({ "mac": MAC, "method": "set_volume", "args": [5] }),
    )
    .await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    assert_eq!(entry(&d, MAC).await["state"], json!("frame"));
}

#[tokio::test]
async fn a_live_widget_frame_is_recorded_when_it_lands() {
    let d = linked(&[(MAC, "Ditoo-Pro")]).await;
    let reply = ask(
        &d,
        "live_job_start",
        json!({ "mac": MAC, "kind": "sysmon", "params": { "size": 16 } }),
    )
    .await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    let mut got = Value::Null;
    for _ in 0..100 {
        got = entry(&d, MAC).await;
        if got["state"] == json!("frame") {
            break;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    assert_eq!(got["state"], json!("frame"), "{got}");
    assert_eq!(got["source"], json!("sysmon"));
    let (w, h, _) = pixels_of(got["frame"]["data_url"].as_str().expect("data_url"));
    assert_eq!((w, h), (16, 16));
    let _ = ask(&d, "live_job_stop", json!({ "mac": MAC, "kind": "sysmon" })).await;
}

#[tokio::test]
async fn an_offline_panel_says_so_and_shows_no_stale_frame() {
    let d = linked(&[(MAC, "Ditoo-Pro"), ("SCREEN_B", "Pixoo64")]).await;
    assert_eq!(push(&d, &gradient()).await["success"], json!(true));
    let reply = ask(&d, "mock_simulate_drop", json!({ "mac": MAC })).await;
    assert_eq!(reply["success"], json!(true), "{reply}");

    let all = ask(&d, "screen_previews", json!({})).await;
    let devices = all["devices"].as_array().expect("devices");
    assert_eq!(devices.len(), 2, "every panel the fleet holds: {all}");
    let a = devices
        .iter()
        .find(|got| got["id"] == json!(MAC))
        .expect("A listed");
    assert_absent(a, "offline");
    assert_eq!(a["connected"], json!(false));
    assert!(a["age_s"].is_null(), "{a}");
    let b = devices
        .iter()
        .find(|got| got["id"] == json!("SCREEN_B"))
        .expect("B listed");
    assert_absent(b, "nothing_sent");
    assert_eq!(b["width"], json!(64), "a Pixoo64 is 64 px: {b}");

    // A new link is a screen the daemon has not drawn on.
    let reply = ask(
        &d,
        "connect",
        json!({ "mock": true, "mac": MAC, "name": "Ditoo-Pro" }),
    )
    .await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    assert_absent(&entry(&d, MAC).await, "nothing_sent");
}

#[tokio::test]
async fn an_unknown_panel_is_refused_by_name() {
    let d = linked(&[(MAC, "Ditoo-Pro")]).await;
    let reply = ask(&d, "screen_previews", json!({ "mac": "NEVER_LINKED" })).await;
    assert_eq!(reply["success"], json!(false), "{reply}");
    assert_eq!(reply["code"], json!("unknown_device"), "{reply}");
    assert!(reply["error"]
        .as_str()
        .unwrap_or_default()
        .contains("NEVER_LINKED"));
}

#[tokio::test]
async fn reading_previews_sends_nothing_to_any_panel() {
    let d = linked(&[(MAC, "Ditoo-Pro")]).await;
    let before = ask(&d, "mock_sent", json!({ "mac": MAC })).await;
    for _ in 0..3 {
        let _ = ask(&d, "screen_previews", json!({})).await;
    }
    let after = ask(&d, "mock_sent", json!({ "mac": MAC })).await;
    assert_eq!(before, after, "a read is not a write");
}
