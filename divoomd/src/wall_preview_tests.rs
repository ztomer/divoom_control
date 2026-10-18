//! The wall answers `get_last_previews` with each panel's cut (P6.5).
//!
//! After a wall push the GUI asks the wall for each panel's preview to draw
//! on the bench. The Rust wall never had the call -- it was dropped in the
//! port from the Python wall -- so it was refused `unsupported` and the
//! bench's previews were always empty, while the GUI tests faked the reply.
//! The previews are the frames the slicer produced for each slot, encoded,
//! never a second rendering of the image.

use crate::wall_outcome_tests::{mock_of, two_panel_wall, wall_call, A, B};
use base64::Engine as _;
use serde_json::{json, Value};

const RED: [u8; 3] = [220, 20, 20];
const BLUE: [u8; 3] = [20, 20, 220];

/// A fresh file per call (tests run concurrently): the wall's left half red,
/// its right half blue, so each panel's cut is one colour.
fn split_image(ext: &str, frames: usize) -> String {
    static NEXT: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
    let n = NEXT.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
    let name = format!("divoom_wall_preview_{}_{n}.{ext}", std::process::id());
    let path = std::env::temp_dir().join(name);
    let img = image::RgbaImage::from_fn(32, 16, |x, _| {
        let [r, g, b] = if x < 16 { RED } else { BLUE };
        image::Rgba([r, g, b, 255])
    });
    if frames > 1 {
        let file = std::fs::File::create(&path).expect("create the test gif");
        let mut enc = image::codecs::gif::GifEncoder::new(file);
        for _ in 0..frames {
            let frame = image::Frame::from_parts(
                img.clone(),
                0,
                0,
                image::Delay::from_numer_denom_ms(200, 1),
            );
            enc.encode_frame(frame).expect("encode a frame");
        }
    } else {
        img.save(&path).expect("write the test image");
    }
    path.to_string_lossy().into_owned()
}

async fn previews(d: &crate::daemon::Daemon) -> Value {
    let reply = wall_call(d, "get_last_previews", json!([])).await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    reply["result"].clone()
}

/// The image a preview data URL carries, and its MIME type.
fn decode(url: &Value) -> (String, image::DynamicImage) {
    let url = url.as_str().expect("a data URL");
    let (head, body) = url.split_once(";base64,").expect("a base64 data URL");
    let mime = head
        .strip_prefix("data:")
        .expect("data: scheme")
        .to_string();
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(body)
        .expect("valid base64");
    (mime, image::load_from_memory(&bytes).expect("an image"))
}

fn is_all(img: &image::DynamicImage, rgb: [u8; 3]) -> bool {
    img.to_rgb8().pixels().all(|p| p.0 == rgb)
}

#[tokio::test]
async fn each_panel_previews_its_own_cut_of_the_image() {
    let d = two_panel_wall().await;
    let path = split_image("png", 1);
    let reply = wall_call(&d, "show_image", json!([path])).await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    let got = previews(&d).await;
    let macs: Vec<&String> = got.as_object().expect("a map").keys().collect();
    assert_eq!(macs, vec![A, B], "one preview per slot: {got}");
    for (mac, colour) in [(A, RED), (B, BLUE)] {
        let (mime, img) = decode(&got[mac]);
        assert_eq!(mime, "image/png", "{mac}");
        assert_eq!(
            (img.width(), img.height()),
            (16, 16),
            "{mac}: the slot's size"
        );
        assert!(
            is_all(&img, colour),
            "{mac} previews its own half of the image"
        );
    }
    let _ = std::fs::remove_file(path);
}

#[tokio::test]
async fn an_animated_push_previews_as_an_animation() {
    let d = two_panel_wall().await;
    let path = split_image("gif", 3);
    let reply = wall_call(&d, "show_image", json!([path])).await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    let got = previews(&d).await;
    for (mac, colour) in [(A, RED), (B, BLUE)] {
        let (mime, img) = decode(&got[mac]);
        assert_eq!(mime, "image/gif", "{mac}");
        assert!(
            is_all(&img, colour),
            "{mac} previews its own half of the image"
        );
    }
    let _ = std::fs::remove_file(path);
}

#[tokio::test]
async fn a_panel_that_did_not_take_the_push_has_no_preview() {
    let d = two_panel_wall().await;
    let first = split_image("png", 1);
    let reply = wall_call(&d, "show_image", json!([first])).await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    mock_of(&d, B).await.set_failing(true);
    let second = split_image("png", 1);
    let reply = wall_call(&d, "show_image", json!([second])).await;
    assert_eq!(reply["success"], json!(false), "{reply}");
    let got = previews(&d).await;
    assert!(got.get(A).is_some(), "A took it: {got}");
    assert!(
        got.get(B).is_none(),
        "B did not take the second image, and its first is not what it shows now: {got}"
    );
    for p in [first, second] {
        let _ = std::fs::remove_file(p);
    }
}

#[tokio::test]
async fn a_wall_that_was_never_pushed_has_no_previews() {
    let d = two_panel_wall().await;
    assert_eq!(previews(&d).await, json!({}));
}
