//! D14: pixel art is shown only on a panel of its own size, against the mock
//! panels (a 16x16 Ditoo-Plus and a 64x64 Pixoo64). No radio, no cloud.
//!
//! Both directions: art drawn for the other size is REFUSED and nothing is
//! streamed; art drawn for this size is sent; a picture (album art) is still
//! scaled to whatever panel it goes to.

use crate::art_source::Source;
use crate::daemon::{Daemon, DeviceTransport};
use crate::image_fit::Fit;
use crate::protocol::make_request;
use crate::socket_server::Handler;
use base64::Engine;
use serde_json::{json, Value};

const SMALL: &str = "AA:00:00:00:00:16";
const BIG: &str = "BB:00:00:00:00:64";

/// A `size`x`size` PNG with a few hard-edged colours, as pixel art is.
fn art(size: u32) -> Vec<u8> {
    let img = image::RgbImage::from_fn(size, size, |x, y| {
        if (x + y) % 2 == 0 {
            image::Rgb([255, 0, 0])
        } else {
            image::Rgb([0, 0, 255])
        }
    });
    let mut out = std::io::Cursor::new(Vec::new());
    image::DynamicImage::ImageRgb8(img)
        .write_to(&mut out, image::ImageFormat::Png)
        .expect("encode a png");
    out.into_inner()
}

async fn two_panels() -> Daemon {
    let d = Daemon::new();
    for (mac, name) in [(SMALL, "Ditoo-Plus"), (BIG, "Pixoo64")] {
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

/// The `0x8B` animation blobs the mock panel at `mac` was streamed.
async fn streamed(d: &Daemon, mac: &str) -> Vec<Vec<u8>> {
    let dev = d.fleet.get(mac).await.expect("the panel is in the fleet");
    let transport = dev.transport().await.expect("the panel is linked");
    let DeviceTransport::Mock(m) = &*transport else {
        panic!("expected the mock transport")
    };
    let blobs: Vec<Vec<u8>> = m
        .sent_commands
        .lock()
        .unwrap()
        .iter()
        .filter(|(cmd, _)| *cmd == 0x8b)
        .map(|(_, b)| b.clone())
        .collect();
    blobs
}

async fn show(d: &Daemon, mac: &str, img: &[u8], kwargs: Value) -> Value {
    d.handle(make_request(
        "device_call",
        Some(json!({
            "method": "display.show_image",
            "args": [],
            "kwargs": kwargs,
            "mac": mac,
            "blobs": {"0": base64::engine::general_purpose::STANDARD.encode(img)},
        })),
        None,
    ))
    .await
}

#[tokio::test]
async fn sixty_four_pixel_art_is_refused_on_a_sixteen_panel_and_nothing_is_streamed() {
    let d = two_panels().await;
    let reply = show(&d, SMALL, &art(64), json!({"art": "pixel"})).await;
    assert_eq!(reply["success"], json!(false), "{reply}");
    let why = reply["error"].as_str().unwrap_or_default();
    assert!(why.contains("64x64") && why.contains("16x16"), "{why}");
    assert_eq!(
        streamed(&d, SMALL).await.len(),
        0,
        "a refusal streams nothing"
    );
}

#[tokio::test]
async fn a_caller_size_cannot_override_the_panel_it_names() {
    // The old default was the caller's `size` (16) whatever the panel: a
    // 64x64 panel named by its model ignores a size that disagrees.
    let d = two_panels().await;
    let reply = show(&d, BIG, &art(16), json!({"art": "pixel", "size": 16})).await;
    assert_eq!(reply["success"], json!(false), "{reply}");
    assert_eq!(streamed(&d, BIG).await.len(), 0);
}

#[tokio::test]
async fn sixteen_pixel_art_is_refused_on_a_sixty_four_panel() {
    let d = two_panels().await;
    let reply = show(&d, BIG, &art(16), json!({"art": "pixel"})).await;
    assert_eq!(reply["success"], json!(false), "{reply}");
    assert_eq!(streamed(&d, BIG).await.len(), 0);
}

#[tokio::test]
async fn native_pixel_art_is_sent_to_each_panel_at_its_own_size() {
    let d = two_panels().await;
    for (mac, size) in [(SMALL, 16), (BIG, 64)] {
        let reply = show(&d, mac, &art(size), json!({"art": "pixel"})).await;
        assert_eq!(reply["success"], json!(true), "{mac}: {reply}");
        let blobs = streamed(&d, mac).await;
        assert_eq!(blobs.len(), 1, "{mac}: one stream");
    }
}

#[tokio::test]
async fn album_art_is_still_scaled_to_the_panel() {
    let d = two_panels().await;
    let reply = show(&d, SMALL, &art(64), json!({"art": "picture"})).await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    assert_eq!(streamed(&d, SMALL).await.len(), 1, "the picture is shown");
}

#[tokio::test]
async fn an_image_that_does_not_say_what_it_is_is_refused() {
    let d = two_panels().await;
    let reply = show(&d, SMALL, &art(16), json!({})).await;
    assert_eq!(reply["success"], json!(false), "{reply}");
    assert_eq!(streamed(&d, SMALL).await.len(), 0);
}

#[test]
fn prepare_never_scales_pixel_art_and_still_scales_a_picture() {
    let refused = crate::image_proc::prepare(art(64), Source::PixelArt, 16, 100)
        .expect_err("64x64 pixel art for a 16x16 panel");
    assert!(refused.contains("never rescaled"), "{refused}");

    let native = crate::image_proc::prepare(art(64), Source::PixelArt, 64, 100).expect("native");
    assert_eq!((native[0].1, native[0].2), (64, 64));

    let photo = crate::image_proc::prepare(art(64), Source::Picture(Fit::Exact), 16, 100)
        .expect("a picture is scaled");
    assert_eq!((photo[0].1, photo[0].2), (16, 16));
}

#[test]
fn custom_art_is_encoded_only_for_a_panel_of_its_own_size() {
    let why = crate::art::encode_custom_art(&art(64), 16).expect_err("64x64 art on a 16x16 page");
    assert!(why.contains("never rescaled"), "{why}");
    let frame = crate::art::encode_custom_art(&art(16), 16).expect("16x16 art on a 16x16 page");
    assert_eq!(
        frame.first(),
        Some(&0xAA),
        "the device's own frame encoding"
    );
}

#[test]
fn the_stored_gallery_page_takes_only_native_art() {
    let gif = crate::media::resolve_to_gif(&art(64)).expect("a png resolves as itself");
    assert!(crate::gallery_store::frames_for(&gif, 16).is_err());
    assert!(crate::gallery_store::frames_for(&gif, 64).is_ok());
}

fn wall_png(size: u32) -> String {
    static NEXT: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
    let n = NEXT.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
    let path = std::env::temp_dir().join(format!("divoom_d14_wall_{}_{n}.png", std::process::id()));
    std::fs::write(&path, art(size)).expect("write the test image");
    path.to_string_lossy().into_owned()
}

fn wall_streams(m: &crate::mock_transport::MockTransport) -> usize {
    m.sent_commands
        .lock()
        .unwrap()
        .iter()
        .filter(|(cmd, _)| *cmd == 0x8b)
        .count()
}

#[tokio::test]
async fn pixel_art_not_drawn_for_the_wall_is_refused_and_no_panel_is_streamed() {
    use crate::wall_outcome_tests::{mock_of, two_panel_wall, wall_call_kw, A, B};
    let d = two_panel_wall().await; // two 16x16 panels: a 32x16 canvas
    let path = wall_png(64);
    let reply = wall_call_kw(&d, "show_image", json!([path]), json!({"art": "pixel"})).await;
    assert_eq!(reply["success"], json!(false), "{reply}");
    let why = reply["error"].as_str().unwrap_or_default();
    assert!(why.contains("64x64") && why.contains("32x16"), "{why}");
    for mac in [A, B] {
        assert_eq!(
            wall_streams(&mock_of(&d, mac).await),
            0,
            "{mac} was streamed"
        );
    }

    // The same file as a picture is scaled across the wall, as before.
    let reply = wall_call_kw(&d, "show_image", json!([path]), json!({"art": "picture"})).await;
    assert_eq!(reply["success"], json!(true), "{reply}");
    for mac in [A, B] {
        assert_eq!(wall_streams(&mock_of(&d, mac).await), 1, "{mac}");
    }
    let _ = std::fs::remove_file(path);
}
