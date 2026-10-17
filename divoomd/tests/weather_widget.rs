//! `render_widget {kind: "weather"}` draws the frame the weather job pushes (P3.3).
//!
//! Weather was the one widget the firmware drew, so it was the one widget with
//! no preview and a different look on every panel. Through the real
//! dispatcher, with the reading passed in (the network-free seam), the reply
//! must be a full frame that moves with the reading.

use base64::Engine;
use divoomd::daemon::Daemon;
use divoomd::protocol::make_request;
use divoomd::socket_server::Handler;
use serde_json::{json, Value};

async fn frame(d: &Daemon, size: u32, temperature_c: i64, weather: i64) -> (Value, Vec<u8>) {
    let r = d
        .handle(make_request(
            "render_widget",
            Some(json!({
                "kind": "weather",
                "size": size,
                "params": { "temperature_c": temperature_c, "weather": weather },
            })),
            None,
        ))
        .await;
    assert_eq!(r["success"], json!(true), "{r}");
    let b64 = r["frame_rgb_b64"].as_str().expect("a frame").to_string();
    let rgb = base64::engine::general_purpose::STANDARD
        .decode(b64)
        .expect("base64");
    (r, rgb)
}

#[tokio::test]
async fn the_weather_kind_renders_a_full_frame_that_follows_the_reading() {
    let d = Daemon::new();
    for size in [16u32, 32, 64] {
        let (reply, rgb) = frame(&d, size, 21, 1).await;
        assert_eq!(reply["kind"], "weather", "{reply}");
        assert_eq!(reply["size"], size, "{reply}");
        assert_eq!(reply["temperature_c"], 21, "{reply}");
        assert_eq!(rgb.len(), (size * size * 3) as usize);

        let (_, warmer) = frame(&d, size, 35, 1).await;
        assert_ne!(rgb, warmer, "{size}: the temperature is not drawn");
        let (_, rainy) = frame(&d, size, 21, 6).await;
        assert_ne!(rgb, rainy, "{size}: the condition is not drawn");
    }
}

#[tokio::test]
async fn an_out_of_range_reading_is_refused_not_wrapped() {
    let d = Daemon::new();
    let r = d
        .handle(make_request(
            "render_widget",
            Some(json!({
                "kind": "weather",
                "params": { "temperature_c": 300, "weather": 1 },
            })),
            None,
        ))
        .await;
    assert_eq!(r["success"], json!(false), "{r}");
    assert_eq!(r["code"], "bad_request", "{r}");
}
