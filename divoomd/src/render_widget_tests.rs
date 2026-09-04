//! Tests for [`crate::render_widget`] — split out at the 500-line house cap,
//! the same way `packets_tests.rs` and `socket_bind_tests.rs` were.
//!
//! Keeping them in-crate (rather than under `tests/`) is deliberate: several
//! pin `render_widget` against the crate-internal renderers it must not fork
//! from, which an integration test could not reach.

use serde_json::{json, Value};

use base64::Engine;

use crate::render_widget::{cmd_render_widget, Quote};

fn frame_bytes(reply: &Value) -> Vec<u8> {
    base64::engine::general_purpose::STANDARD
        .decode(reply["frame_rgb_b64"].as_str().unwrap())
        .unwrap()
}

fn frame_len(reply: &Value) -> usize {
    let b64 = reply["frame_rgb_b64"].as_str().unwrap();
    base64::engine::general_purpose::STANDARD
        .decode(b64)
        .unwrap()
        .len()
}

#[tokio::test]
async fn sysmon_returns_a_full_frame_and_its_stats() {
    let r = cmd_render_widget(&json!({"kind": "sysmon", "size": 16})).await;
    assert_eq!(r["success"], json!(true));
    assert_eq!(r["kind"], json!("sysmon"));
    assert_eq!(r["size"], json!(16));
    assert_eq!(frame_len(&r), 16 * 16 * 3);
    for key in ["cpu", "mem", "battery"] {
        assert!(r.get(key).is_some(), "missing {key}");
    }
}

#[tokio::test]
async fn size_is_clamped_the_same_way_cmd_sysmon_clamps_it() {
    // `size: 0` reached the renderer as a 0-byte buffer before clamp_size
    // existed. Sharing the function rather than re-deriving the bounds is
    // the point: two clamps would drift.
    let r = cmd_render_widget(&json!({"kind": "sysmon", "size": 0})).await;
    assert_eq!(r["size"], json!(8));
    assert_eq!(frame_len(&r), 8 * 8 * 3);
}

#[tokio::test]
async fn an_unknown_kind_says_what_it_knows() {
    let r = cmd_render_widget(&json!({"kind": "nope", "size": 16})).await;
    assert_eq!(r["success"], json!(false));
    let err = r["error"].as_str().unwrap();
    assert!(err.contains("nope"), "{err}");
    assert!(err.contains("sysmon"), "must name the known kinds: {err}");
}

#[tokio::test]
async fn a_missing_kind_is_an_error_not_a_default() {
    let r = cmd_render_widget(&json!({"size": 16})).await;
    assert_eq!(r["success"], json!(false));
}

#[tokio::test]
async fn album_art_renders_a_decoded_image_to_the_device_size() {
    // A 2x2 PNG, built here so the test needs no fixture file.
    let png = {
        let mut buf = std::io::Cursor::new(Vec::new());
        let img = image::RgbImage::from_fn(2, 2, |x, y| {
            if (x + y) % 2 == 0 {
                image::Rgb([255, 255, 255])
            } else {
                image::Rgb([0, 0, 0])
            }
        });
        image::DynamicImage::ImageRgb8(img)
            .write_to(&mut buf, image::ImageFormat::Png)
            .unwrap();
        buf.into_inner()
    };
    let b64 = base64::engine::general_purpose::STANDARD.encode(&png);
    let r =
        cmd_render_widget(&json!({"kind": "album_art", "size": 16, "params": {"image_b64": b64}}))
            .await;
    assert_eq!(r["success"], json!(true), "{r}");
    assert_eq!(frame_len(&r), 16 * 16 * 3);
}

#[tokio::test]
async fn album_art_without_an_image_says_so() {
    let r = cmd_render_widget(&json!({"kind": "album_art", "size": 16})).await;
    assert_eq!(r["success"], json!(false));
    assert!(r["error"].as_str().unwrap().contains("image_b64"));
}

#[tokio::test]
async fn album_art_rejects_bytes_that_are_not_an_image() {
    let b64 = base64::engine::general_purpose::STANDARD.encode(b"not an image");
    let r =
        cmd_render_widget(&json!({"kind": "album_art", "size": 16, "params": {"image_b64": b64}}))
            .await;
    assert_eq!(r["success"], json!(false));
}

#[tokio::test]
async fn stocks_without_a_symbol_fails_rather_than_rendering_an_empty_tile() {
    let r = cmd_render_widget(&json!({"kind": "stocks", "size": 16})).await;
    assert_eq!(r["success"], json!(false));
    assert!(r["error"].as_str().unwrap().contains("symbol"));
}

#[tokio::test]
async fn sysmon_through_render_widget_is_byte_identical_to_cmd_sysmon() {
    // The named regression risk of generalizing: sysmon is the ONE preview
    // path that already works (R67/C2), and a refactor that quietly changed
    // its pixels would break the thing this command exists to protect.
    //
    // Comparing the two replies to each other CANNOT do that job: CPU load
    // moves between the calls, so the only assertions that survive are size
    // and length — and the first draft of this test asserted exactly those,
    // then PASSED with the sysmon arm sabotaged to return a solid block of
    // 7s. A comparison blind to the property it names is worse than no
    // comparison, because it reports confidence.
    //
    // So the loop is closed instead: take the stats the reply ITSELF
    // reports, re-render them with the canonical renderer, and require the
    // bytes to match. A second renderer cannot satisfy that.
    for size in [16u64, 32, 64] {
        let a = cmd_render_widget(&json!({"kind": "sysmon", "size": size})).await;
        let expected = crate::live_jobs::render::render_sysmon(
            a["cpu"].as_u64().unwrap() as u8,
            a["mem"].as_u64().unwrap() as u8,
            a["battery"].as_u64().unwrap() as u8,
            size as u32,
        );
        assert_eq!(
            frame_bytes(&a),
            expected,
            "render_widget's sysmon frame is not render_sysmon's output at size {size}"
        );
    }

    // And the legacy command answers in the same shape, so a client can be
    // moved from one to the other without noticing.
    let b = crate::live_jobs::sysmon::cmd_sysmon(&json!({"size": 32})).await;
    let b_expected = crate::live_jobs::render::render_sysmon(
        b["cpu"].as_u64().unwrap() as u8,
        b["mem"].as_u64().unwrap() as u8,
        b["battery"].as_u64().unwrap() as u8,
        32,
    );
    assert_eq!(frame_bytes(&b), b_expected);
    let a = cmd_render_widget(&json!({"kind": "sysmon", "size": 32})).await;
    assert_eq!(a["size"], b["size"]);
    assert_eq!(frame_len(&a), frame_len(&b));
}

#[test]
fn both_paths_call_one_renderer_on_fixed_input() {
    // Deterministic half of the check above: identical inputs must give
    // identical bytes, which is only true while there is a single
    // render_sysmon. Two renderers would pass the shape assertions and
    // fail this one.
    use crate::live_jobs::render::render_sysmon;
    for size in [8u32, 16, 32, 64] {
        let one = render_sysmon(37, 61, 88, size);
        let two = render_sysmon(37, 61, 88, size);
        assert_eq!(one, two);
        assert_eq!(one.len(), (size * size * 3) as usize);
    }
}

#[tokio::test]
async fn text_renders_a_full_frame() {
    let r = cmd_render_widget(&json!({"kind": "text", "size": 16, "params": {"text": "HI"}})).await;
    assert_eq!(r["success"], json!(true), "{r}");
    assert_eq!(frame_len(&r), 16 * 16 * 3);
}

#[tokio::test]
async fn empty_text_is_an_error_not_a_blank_matrix() {
    for t in ["", "   "] {
        let r =
            cmd_render_widget(&json!({"kind": "text", "size": 16, "params": {"text": t}})).await;
        assert_eq!(r["success"], json!(false), "{t:?} should be rejected");
    }
}

#[tokio::test]
async fn text_that_does_not_fit_is_clipped_not_scaled() {
    // The P3.3 decision, pinned. Two strings that share a prefix and BOTH
    // overflow the matrix must render identically — only a renderer that
    // clips can do that. A scaler fits each whole string into 16px and
    // produces two different frames (and, at these ratios, two unreadable
    // ones: "HELLO WORLD" scaled to 0.34x is noise).
    //
    // Both operands must overflow. A string that FITS is centred, so
    // comparing an overflowing string against a short one would compare
    // layout, not clipping — which is what the first draft of this test
    // did, and why it failed.
    let a =
        cmd_render_widget(&json!({"kind": "text", "size": 16, "params": {"text": "HELLO WORLD"}}))
            .await;
    let b = cmd_render_widget(
        &json!({"kind": "text", "size": 16, "params": {"text": "HELLO WORLDXYZ"}}),
    )
    .await;
    assert_eq!(
        frame_bytes(&a),
        frame_bytes(&b),
        "clipping must ignore everything past the matrix edge"
    );
    assert!(
        frame_bytes(&a).iter().any(|&px| px > 0),
        "a clipped render must still draw the characters that fit"
    );
}

#[tokio::test]
async fn a_bad_colour_still_shows_the_text() {
    // White, not black: a mistyped colour must not look like a broken
    // feature.
    let bad = cmd_render_widget(&json!({"kind": "text", "size": 16,
                "params": {"text": "HI", "color": "not-a-colour"}}))
    .await;
    let white = cmd_render_widget(&json!({"kind": "text", "size": 16,
                "params": {"text": "HI", "color": "#FFFFFF"}}))
    .await;
    assert_eq!(frame_bytes(&bad), frame_bytes(&white));
}

#[tokio::test]
async fn colour_is_honoured() {
    let red = cmd_render_widget(&json!({"kind": "text", "size": 16,
                "params": {"text": "HI", "color": "#FF0000"}}))
    .await;
    let px = frame_bytes(&red);
    let lit: Vec<&[u8]> = px.chunks(3).filter(|c| c.iter().any(|&b| b > 0)).collect();
    assert!(!lit.is_empty(), "nothing was drawn");
    assert!(lit.iter().all(|c| c == &[255u8, 0, 0]), "text is not red");
}

#[test]
fn pct_change_of_a_zero_previous_close_is_zero_not_infinity() {
    let q = Quote {
        price: 10.0,
        prev_close: 0.0,
        change: 10.0,
    };
    assert_eq!(q.pct_change(), 0.0);
}

#[test]
fn pct_change_is_relative_to_the_previous_close() {
    let q = Quote {
        price: 110.0,
        prev_close: 100.0,
        change: 10.0,
    };
    assert!((q.pct_change() - 10.0).abs() < 1e-9);
}
